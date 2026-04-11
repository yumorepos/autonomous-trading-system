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

import logging

from config.runtime import LOGS_DIR

logger = logging.getLogger(__name__)

class _StdoutHandler(logging.StreamHandler):
    """Handler that always writes to the current sys.stdout (not the one at init time)."""
    def __init__(self):
        super().__init__()
    @property
    def stream(self):
        return sys.stdout
    @stream.setter
    def stream(self, _):
        pass

if not logger.handlers:
    _handler = _StdoutHandler()
    _handler.setFormatter(logging.Formatter('%(message)s'))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)

# Import HyperliquidClient from trading_engine
# (emergency fallback must be independent but can share client code)
import importlib.util
spec = importlib.util.spec_from_file_location("trading_engine", REPO_ROOT / "scripts" / "trading_engine.py")
trading_engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trading_engine)
HyperliquidClient = trading_engine.HyperliquidClient

# Import exit ownership manager
from scripts.exit_ownership import claim_exit, record_attempt, release_exit, list_active_exits

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
    
    # === COORDINATION: Check exit ownership ===
    # Respect owned exits to prevent race condition
    owned_exits = list_active_exits()
    
    # Get live positions from exchange
    positions = client.get_positions()
    
    if not positions:
        log_fallback_event({
            "event": "emergency_no_positions",
            "action": "none_needed",
        })
        logger.info("No positions to close")
        return
    
    # Filter out positions with active ownership
    positions_to_close = []
    positions_skipped = []
    
    for pos in positions:
        coin = pos["coin"]
        
        # Check if any owned exit matches this coin
        owned = next((exit for exit in owned_exits.values() if exit["symbol"] == coin), None)
        
        if owned:
            # Check if ownership is fresh
            start_time = datetime.fromisoformat(owned["start_time"])
            if start_time.tzinfo is None:
                start_time = start_time.replace(tzinfo=timezone.utc)
            
            age = (datetime.now(timezone.utc) - start_time).total_seconds()
            
            # Only skip if ownership is recent (<5 min)
            # After 5 min, assume owner is stuck and take over
            if age < 300:
                positions_skipped.append({
                    "coin": coin,
                    "owner": owned["owner"],
                    "reason": f"Owned by {owned['owner']} (started {age:.0f}s ago)",
                })
                continue
        
        # Try to claim ownership before closing
        trade_id = f"fallback-{coin.lower()}-{datetime.now(timezone.utc).isoformat()[:10]}"
        
        if not claim_exit(coin, trade_id, "fallback", pos["szi"], "EMERGENCY_FALLBACK"):
            positions_skipped.append({
                "coin": coin,
                "reason": "Failed to claim ownership (concurrent actor)",
            })
            continue
        
        positions_to_close.append((pos, trade_id))
    
    if positions_skipped:
        log_fallback_event({
            "event": "positions_skipped_ownership",
            "skipped": positions_skipped,
        })
        logger.warning(f"Skipped {len(positions_skipped)} positions (owned or concurrent)")
    
    if not positions_to_close:
        logger.info("No positions to close (all owned or concurrent)")
        return
    
    logger.error("=" * 70)
    logger.error("EMERGENCY FALLBACK ACTIVATED")
    logger.error("=" * 70)
    logger.error("")
    logger.error(f"Closing {len(positions_to_close)} positions...")
    if positions_skipped:
        logger.warning(f"Skipped {len(positions_skipped)} (engine actively exiting)")
    logger.error("")
    
    results = []
    
    for pos, trade_id in positions_to_close:
        coin = pos["coin"]
        logger.info(f"Closing {coin}...")
        
        # Force close (market order, no slippage check)
        response = client.market_close(coin)
        
        # Record attempt
        record_attempt(coin, trade_id, "ok" if response["status"] == "ok" else "error", response)
        
        result = {
            "coin": coin,
            "size": pos["szi"],
            "roe": pos["roe"],
            "pnl": pos["unrealized_pnl"],
            "response": response,
        }
        
        if response["status"] == "ok":
            logger.info(f"  {coin} closed")
            # Release ownership after success
            release_exit(coin, trade_id)
        else:
            logger.error(f"  {coin} FAILED: {response}")
            # Keep ownership (for retry or manual intervention)
        
        results.append(result)
    
    log_fallback_event({
        "event": "emergency_close_all",
        "positions_closed": len(positions_to_close),
        "positions_skipped": len(positions_skipped),
        "results": results,
    })
    
    logger.error("")
    logger.error("=" * 70)
    logger.error("EMERGENCY CLOSE COMPLETE")
    logger.error("=" * 70)

def main() -> None:
    """Main fallback check."""
    
    healthy, reason = check_engine_health()
    
    if healthy:
        # Engine is healthy, no action needed
        log_fallback_event({
            "event": "fallback_check_ok",
            "reason": reason,
        })
        logger.info(f"Engine healthy: {reason}")
        return
    
    # Engine is unhealthy
    log_fallback_event({
        "event": "CRITICAL_ENGINE_UNHEALTHY",
        "reason": reason,
        "action": "emergency_close_all",
    })
    
    logger.error("=" * 70)
    logger.error("CRITICAL: ENGINE UNHEALTHY")
    logger.error("=" * 70)
    logger.error("")
    logger.error(f"Reason: {reason}")
    logger.error("")
    logger.error("Activating emergency fallback...")
    logger.error("")
    
    emergency_close_all()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    main()
