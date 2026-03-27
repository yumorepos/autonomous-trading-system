#!/usr/bin/env python3
"""
EMERGENCY FALLBACK — External Capital Protection Layer

This is an INDEPENDENT process that monitors the trading engine.

If engine dies or heartbeat goes stale → FORCE CLOSE ALL POSITIONS

This is the last line of defense. It runs separately from the engine
to ensure capital is protected even if the engine crashes.

Triggers:
- Engine heartbeat >30 sec old (engine frozen or dead)
- Engine process not running
- Open positions exist without fresh heartbeat

Actions:
1. Force-close all open positions
2. Log emergency event
3. Alert user (future: Telegram notification)

Usage:
    python3 scripts/emergency_fallback.py  # Run once (check + exit if safe)
    
Schedule via cron (every minute):
    * * * * * cd ~/Projects/autonomous-trading-system && /usr/local/bin/python3 scripts/emergency_fallback.py >> workspace/logs/emergency-fallback.log 2>&1
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.runtime import LOGS_DIR

# Import HyperliquidClient from trading_engine
# (emergency fallback must be independent but can share client code)
import importlib.util
spec = importlib.util.spec_from_file_location("trading_engine", REPO_ROOT / "scripts" / "trading_engine.py")
trading_engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trading_engine)
HyperliquidClient = trading_engine.HyperliquidClient

STATE_FILE = LOGS_DIR / "trading_engine_state.json"
FALLBACK_LOG = LOGS_DIR / "emergency-fallback.jsonl"

HEARTBEAT_THRESHOLD_SEC = 30  # Engine must update heartbeat within 30 sec

def log_fallback_event(event: dict) -> None:
    """Log emergency fallback event."""
    event["timestamp"] = datetime.now(timezone.utc).isoformat()
    FALLBACK_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(FALLBACK_LOG, "a") as f:
        f.write(json.dumps(event) + "\n")

def check_engine_health() -> tuple[bool, str]:
    """Check if engine is healthy. Returns (healthy, reason)."""
    
    # Check 1: State file exists
    if not STATE_FILE.exists():
        return False, "State file missing (engine never started or crashed)"
    
    # Check 2: State file is valid JSON
    try:
        data = json.loads(STATE_FILE.read_text())
    except json.JSONDecodeError as e:
        return False, f"State file corrupted: {e}"
    
    # Check 3: Heartbeat exists
    if "heartbeat" not in data or not data["heartbeat"]:
        return False, "Heartbeat missing (engine never updated state)"
    
    # Check 4: Heartbeat is fresh
    hb_time = datetime.fromisoformat(data["heartbeat"])
    if hb_time.tzinfo is None:
        hb_time = hb_time.replace(tzinfo=timezone.utc)
    
    age_sec = (datetime.now(timezone.utc) - hb_time).total_seconds()
    
    if age_sec > HEARTBEAT_THRESHOLD_SEC:
        return False, f"Heartbeat stale ({age_sec:.0f}s old, threshold {HEARTBEAT_THRESHOLD_SEC}s)"
    
    # Check 5: Open positions exist
    if not data.get("open_positions"):
        return True, "No positions (no action needed)"
    
    return True, "Engine healthy"

def emergency_close_all() -> None:
    """Force-close all open positions (emergency only)."""
    
    client = HyperliquidClient()
    
    # === COORDINATION: Check if engine is actively exiting ===
    # Respect active exits to prevent race condition
    active_exits_file = LOGS_DIR / "active_exits.json"
    active_exits = {}
    
    if active_exits_file.exists():
        try:
            data = json.loads(active_exits_file.read_text())
            active_exits = data.get("active_exits", {})
        except Exception as e:
            log_fallback_event({"event": "coordination_check_failed", "error": str(e)})
    
    # Get live positions from exchange
    positions = client.get_positions()
    
    if not positions:
        log_fallback_event({
            "event": "emergency_no_positions",
            "action": "none_needed",
        })
        print("No positions to close")
        return
    
    # Filter out positions with active exits (engine is handling them)
    positions_to_close = []
    positions_skipped = []
    
    for pos in positions:
        coin = pos["coin"]
        if coin in active_exits:
            # Engine is actively retrying this exit, don't interfere
            exit_start = datetime.fromisoformat(active_exits[coin]["start_time"])
            if exit_start.tzinfo is None:
                exit_start = exit_start.replace(tzinfo=timezone.utc)
            
            age = (datetime.now(timezone.utc) - exit_start).total_seconds()
            
            # Only skip if exit started recently (<60 sec)
            # After 60 sec, assume engine is stuck and take over
            if age < 60:
                positions_skipped.append({
                    "coin": coin,
                    "reason": f"Engine actively exiting (started {age:.0f}s ago)",
                })
                continue
        
        positions_to_close.append(pos)
    
    if positions_skipped:
        log_fallback_event({
            "event": "positions_skipped_active_exit",
            "skipped": positions_skipped,
        })
        print(f"Skipped {len(positions_skipped)} positions (engine actively exiting)")
    
    if not positions_to_close:
        print("No positions to close (all handled by engine)")
        return
    
    print("=" * 70)
    print("🚨 EMERGENCY FALLBACK ACTIVATED")
    print("=" * 70)
    print()
    print(f"Closing {len(positions_to_close)} positions...")
    if positions_skipped:
        print(f"Skipped {len(positions_skipped)} (engine actively exiting)")
    print()
    
    results = []
    
    for pos in positions_to_close:
        coin = pos["coin"]
        print(f"Closing {coin}...")
        
        # Force close (market order, no slippage check)
        response = client.market_close(coin)
        
        result = {
            "coin": coin,
            "size": pos["szi"],
            "roe": pos["roe"],
            "pnl": pos["unrealized_pnl"],
            "response": response,
        }
        
        if response["status"] == "ok":
            print(f"  ✅ {coin} closed")
        else:
            print(f"  ❌ {coin} FAILED: {response}")
        
        results.append(result)
    
    log_fallback_event({
        "event": "emergency_close_all",
        "positions_closed": len(positions_to_close),
        "positions_skipped": len(positions_skipped),
        "results": results,
    })
    
    print()
    print("=" * 70)
    print("🚨 EMERGENCY CLOSE COMPLETE")
    print("=" * 70)

def main() -> None:
    """Main fallback check."""
    
    healthy, reason = check_engine_health()
    
    if healthy:
        # Engine is healthy, no action needed
        log_fallback_event({
            "event": "fallback_check_ok",
            "reason": reason,
        })
        print(f"✅ Engine healthy: {reason}")
        return
    
    # Engine is unhealthy
    log_fallback_event({
        "event": "CRITICAL_ENGINE_UNHEALTHY",
        "reason": reason,
        "action": "emergency_close_all",
    })
    
    print("=" * 70)
    print("🚨 CRITICAL: ENGINE UNHEALTHY")
    print("=" * 70)
    print()
    print(f"Reason: {reason}")
    print()
    print("Activating emergency fallback...")
    print()
    
    emergency_close_all()

if __name__ == "__main__":
    main()
