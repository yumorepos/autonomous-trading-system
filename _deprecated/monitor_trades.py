#!/usr/bin/env python3
"""
MONITOR TRADES — Token-efficient trade monitoring

Reads logs only on meaningful state changes.
Reports only material events (trades, retries, errors, drift).

Usage:
    python3 scripts/monitor_trades.py
"""

import json
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MISSION_FILE = REPO_ROOT / "CURRENT_MISSION.json"
LOG_FILE = REPO_ROOT / "workspace" / "logs" / "trading_engine.jsonl"

def load_mission():
    """Load mission or return None."""
    if not MISSION_FILE.exists():
        return None
    try:
        with open(MISSION_FILE) as f:
            return json.load(f)
    except:
        return None

def check_for_new_trades(since_timestamp):
    """Check logs for new trades since timestamp."""
    if not LOG_FILE.exists():
        return []
    
    trades = []
    since_dt = datetime.fromisoformat(since_timestamp.replace('Z', '+00:00'))
    
    with open(LOG_FILE) as f:
        for line in f:
            try:
                event = json.loads(line)
                event_time = datetime.fromisoformat(event["timestamp"].replace('Z', '+00:00'))
                
                if event_time <= since_dt:
                    continue
                
                # Track entry events
                if event.get("event") == "entry_executed":
                    trades.append({"type": "entry", "coin": event.get("coin"), "time": event["timestamp"]})
                
                # Track exit events
                if event.get("action") == "exit" and event.get("result") in ["EXECUTED", "FAILED_ALL_RETRIES"]:
                    trades.append({"type": "exit", "coin": event.get("coin"), "time": event["timestamp"], "result": event.get("result")})
            except:
                continue
    
    return trades

def main():
    mission = load_mission()
    if not mission or mission.get("status") != "active":
        print("No active mission")
        return
    
    # Check for new trades
    last_check = mission["progress"]["last_check"]
    new_trades = check_for_new_trades(last_check)
    
    if not new_trades:
        # No new trades, silent (token efficient)
        print("No new trades since last check")
        return
    
    # Material event detected, report
    print("=" * 70)
    print(f"  NEW ACTIVITY DETECTED ({len(new_trades)} events)")
    print("=" * 70)
    print()
    
    for trade in new_trades:
        print(f"{trade['time']}: {trade['type'].upper()} - {trade['coin']} - {trade.get('result', 'N/A')}")
    
    print()
    print("⚠️  Trades detected → full audit required")
    print("Run: python3 scripts/audit_trade.py <coin>")

if __name__ == "__main__":
    main()
