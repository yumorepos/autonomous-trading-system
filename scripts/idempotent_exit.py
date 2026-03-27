#!/usr/bin/env python3
"""
IDEMPOTENT EXIT COORDINATOR

Replaces execute_exit() with partial-fill aware, unknown-success handling version.

Features:
- Claims durable exit ownership (prevents concurrent actors)
- Re-queries exchange state before each retry (detects partial fills, unknown success)
- Loops until position is flat (handles partial fills)
- Records all attempts in ownership journal
- Releases ownership only when confirmed flat
"""

from __future__ import annotations

import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.exit_ownership import claim_exit, record_attempt, release_exit

# Inline log_event to avoid circular import
def log_event(event: dict) -> None:
    """Log event to trading engine log."""
    import json
    from datetime import datetime, timezone
    from pathlib import Path
    
    try:
        from config.runtime import LOGS_DIR
        log_file = LOGS_DIR / "trading_engine.jsonl"
    except ImportError:
        log_file = Path(__file__).parent.parent / "workspace" / "logs" / "trading_engine.jsonl"
    
    event["timestamp"] = datetime.now(timezone.utc).isoformat()
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with open(log_file, "a") as f:
        f.write(json.dumps(event) + "\n")

def execute_exit_idempotent(client, pos: dict, triggers: list[str], state, force: bool, dry_run: bool) -> dict:
    """
    Execute exit with idempotency + partial-fill handling.
    
    Args:
        client: HyperliquidClient instance
        pos: Position dict with coin, roe, unrealized_pnl, entry_price
        triggers: List of trigger reasons
        state: EngineState instance
        force: Force mode (skip checks)
        dry_run: Test mode
    
    Returns:
        Result dict with status, attempts, final state
    """
    coin = pos["coin"]
    
    result = {
        "action": "exit",
        "coin": coin,
        "triggers": triggers,
        "force": force,
        "dry_run": dry_run,
        "roe": pos["roe"],
        "pnl": pos["unrealized_pnl"],
    }
    
    # FORCE MODE: Skip all checks for risk exits
    if not force:
        # Check circuit breaker (only for non-forced exits)
        safe, reason = state.check_circuit_breaker(client.get_state()["account_value"])
        if not safe:
            result["result"] = "BLOCKED_CIRCUIT_BREAKER"
            result["reason"] = reason
            log_event(result)
            return result
    
    # Dry run
    if dry_run:
        result["result"] = "DRY_RUN"
        log_event(result)
        return result
    
    # === CLAIM EXIT OWNERSHIP ===
    trade_id = f"hl-{coin.lower()}-{state.data['open_positions'].get(coin, {}).get('entry_time', 'unknown')[:10]}"
    
    if not claim_exit(coin, trade_id, "engine", pos.get("szi", "unknown"), triggers[0] if triggers else "UNKNOWN"):
        # Another actor owns this exit
        result["result"] = "OWNERSHIP_CONFLICT"
        result["reason"] = "Another actor is handling this exit"
        log_event(result)
        return result
    
    # === IDEMPOTENT RETRY LOOP ===
    max_retries = 5 if force else 1
    retry_delay_sec = 1.0
    total_attempts = 0
    start_time = time.time()
    max_total_time_sec = 60  # Retry budget: 60 seconds total
    
    while total_attempts < max_retries:
        total_attempts += 1
        
        # Check retry budget
        elapsed = time.time() - start_time
        if elapsed > max_total_time_sec:
            log_event({
                "event": "CRITICAL_RETRY_BUDGET_EXHAUSTED",
                "coin": coin,
                "elapsed_sec": elapsed,
                "attempts": total_attempts,
            })
            release_exit(coin, trade_id)
            result["result"] = "RETRY_BUDGET_EXHAUSTED"
            result["escalated"] = True
            log_event(result)
            return result
        
        # === RE-QUERY EXCHANGE STATE (CRITICAL FOR UNKNOWN-SUCCESS DETECTION) ===
        # Before each retry, check current position state
        # This handles: partial fills, unknown success, concurrent closes
        
        # Brief wait to allow exchange state to settle (prevent stale cache)
        if total_attempts > 1:
            time.sleep(0.2)
        
        live_positions = client.get_positions()
        live_pos = next((p for p in live_positions if p["coin"] == coin), None)
        
        if not live_pos:
            # Position is flat (already closed, or never existed)
            log_event({
                "event": "exit_already_flat",
                "coin": coin,
                "attempt": total_attempts,
                "reason": "Position not found on exchange (already closed or unknown success)",
            })
            
            record_attempt(coin, trade_id, "ok", {"status": "already_flat", "query_result": "no_position"})
            result["result"] = "EXECUTED"
            result["already_flat"] = True
            break
        
        remaining_size = abs(float(live_pos["szi"]))
        
        if remaining_size == 0:
            # Position exists but size is 0 (closed)
            log_event({
                "event": "exit_already_flat",
                "coin": coin,
                "attempt": total_attempts,
                "reason": "Position size is 0 (already closed)",
            })
            
            record_attempt(coin, trade_id, "ok", {"status": "already_flat", "size": 0})
            result["result"] = "EXECUTED"
            result["already_flat"] = True
            break
        
        # Position still open, attempt close
        log_event({
            "event": "exit_attempt",
            "coin": coin,
            "attempt": total_attempts,
            "remaining_size": remaining_size,
        })
        
        response = client.market_close(coin)
        
        if response["status"] == "ok":
            # Success (or partial fill)
            record_attempt(coin, trade_id, "ok", response, remaining_size=str(remaining_size))
            
            # Re-query to confirm flat
            time.sleep(0.5)  # Brief settle time
            live_positions_after = client.get_positions()
            live_pos_after = next((p for p in live_positions_after if p["coin"] == coin), None)
            
            if not live_pos_after or abs(float(live_pos_after.get("szi", 0))) == 0:
                # Confirmed flat
                result["result"] = "EXECUTED"
                break
            else:
                # Partial fill, continue loop
                log_event({
                    "event": "partial_fill_detected",
                    "coin": coin,
                    "remaining": live_pos_after["szi"],
                })
                continue
        
        elif response["status"] == "error":
            # Definite error
            error_msg = response.get("response", "unknown")
            
            record_attempt(coin, trade_id, "error", response)
            
            if total_attempts < max_retries:
                # Add jitter to prevent thundering herd (AWS best practice)
                jitter = random.uniform(0, retry_delay_sec * 0.3)  # ±30% jitter
                actual_delay = retry_delay_sec + jitter
                
                log_event({
                    "event": "exit_retry",
                    "coin": coin,
                    "attempt": total_attempts,
                    "error": error_msg,
                    "retry_in_sec": actual_delay,
                })
                time.sleep(actual_delay)
                retry_delay_sec = min(retry_delay_sec * 2, 16)  # Cap at 16s
                continue
            else:
                # All retries exhausted
                log_event({
                    "event": "CRITICAL_EXIT_FAILED",
                    "coin": coin,
                    "attempts": total_attempts,
                    "last_error": error_msg,
                    "action": "ESCALATE_TO_EMERGENCY_FALLBACK",
                })
                
                # Release ownership so fallback can take over
                release_exit(coin, trade_id)
                
                result["result"] = "FAILED_ALL_RETRIES"
                result["escalated"] = True
                log_event(result)
                return result
        
        else:
            # Unknown status (timeout, network error)
            record_attempt(coin, trade_id, "unknown", response)
            
            log_event({
                "event": "exit_unknown_result",
                "coin": coin,
                "attempt": total_attempts,
                "response": response,
                "action": "re_query_next_attempt",
            })
            
            if total_attempts < max_retries:
                # Add jitter for unknown status retries
                jitter = random.uniform(0, retry_delay_sec * 0.3)
                actual_delay = retry_delay_sec + jitter
                
                time.sleep(actual_delay)
                retry_delay_sec = min(retry_delay_sec * 2, 16)  # Cap at 16s
                continue
            else:
                # Exhausted retries with unknown state
                # Release ownership and let fallback reconcile
                release_exit(coin, trade_id)
                
                result["result"] = "UNKNOWN_EXHAUSTED"
                result["escalated"] = True
                log_event(result)
                return result
    
    # === SUCCESS: POSITION FLAT ===
    if result.get("result") == "EXECUTED":
        # Get final price
        mid = client.get_mid(coin)
        if mid == 0.0:
            mid = pos.get("entry_price", 0)
            result["price_fallback"] = True
        result["exit_price"] = mid
        
        # Update state
        state.record_close(coin, pos["unrealized_pnl"])
        
        # Log to ledger (import here to avoid circular dependency)
        try:
            from scripts.trading_engine import log_to_ledger
            log_to_ledger(
                trade_id=trade_id,
                action="exit",
                exit_price=mid,
                exit_reason=triggers[0] if triggers else "MANUAL",
            )
        except Exception as e:
            log_event({"event": "ledger_log_failed", "error": str(e)})
        
        # Release ownership
        release_exit(coin, trade_id)
    
    result["total_attempts"] = total_attempts
    log_event(result)
    return result
