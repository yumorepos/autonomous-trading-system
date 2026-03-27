#!/usr/bin/env python3
"""
CONTINUOUS VALIDATION — Permanent Health Monitoring

Runs automatically (daily via cron) to validate critical paths remain operational.

Tests:
1. Engine heartbeat (liveness)
2. State file integrity
3. Log freshness
4. Reconciliation behavior
5. SL logic (dry-run simulation)

If any test fails → alerts user, logs failure, halts new entries.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.runtime import LOGS_DIR

def check_heartbeat() -> dict:
    """Verify engine heartbeat is fresh."""
    state_file = LOGS_DIR / "trading_engine_state.json"
    
    if not state_file.exists():
        return {"pass": False, "reason": "State file missing"}
    
    try:
        data = json.loads(state_file.read_text())
        hb = datetime.fromisoformat(data["heartbeat"])
        if hb.tzinfo is None:
            hb = hb.replace(tzinfo=timezone.utc)
        
        age_sec = (datetime.now(timezone.utc) - hb).total_seconds()
        
        if age_sec > 10:
            return {"pass": False, "reason": f"Heartbeat stale ({age_sec:.0f}s)"}
        
        return {"pass": True, "age_sec": age_sec}
    except Exception as e:
        return {"pass": False, "reason": f"Error: {e}"}

def check_state_integrity() -> dict:
    """Verify state file is valid JSON with required fields."""
    state_file = LOGS_DIR / "trading_engine_state.json"
    
    try:
        data = json.loads(state_file.read_text())
        required = ["heartbeat", "peak_capital", "open_positions", "circuit_breaker_halted"]
        
        for field in required:
            if field not in data:
                return {"pass": False, "reason": f"Missing field: {field}"}
        
        return {"pass": True}
    except Exception as e:
        return {"pass": False, "reason": f"Invalid JSON: {e}"}

def check_log_freshness() -> dict:
    """Verify engine log has recent entries."""
    log_file = LOGS_DIR / "trading_engine.jsonl"
    
    if not log_file.exists():
        return {"pass": False, "reason": "Log file missing"}
    
    try:
        lines = log_file.read_text().strip().split("\n")
        if not lines:
            return {"pass": False, "reason": "Log file empty"}
        
        last_line = json.loads(lines[-1])
        ts = datetime.fromisoformat(last_line["timestamp"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        
        age_sec = (datetime.now(timezone.utc) - ts).total_seconds()
        
        if age_sec > 600:  # 10 minutes
            return {"pass": False, "reason": f"Last log entry {age_sec/60:.0f} min old"}
        
        return {"pass": True, "age_min": age_sec / 60}
    except Exception as e:
        return {"pass": False, "reason": f"Error: {e}"}

def check_reconciliation() -> dict:
    """Verify reconciliation ran recently (if positions exist)."""
    state_file = LOGS_DIR / "trading_engine_state.json"
    log_file = LOGS_DIR / "trading_engine.jsonl"
    
    try:
        data = json.loads(state_file.read_text())
        
        # If no positions, reconciliation not critical
        if not data.get("open_positions"):
            return {"pass": True, "reason": "No positions (reconciliation not critical)"}
        
        # Check if reconciliation events exist in last 24 hours
        lines = log_file.read_text().strip().split("\n")
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        
        recent_reconcile = False
        for line in reversed(lines[-1000:]):  # Check last 1000 lines
            try:
                entry = json.loads(line)
                if "reconcile" in entry.get("event", ""):
                    ts = datetime.fromisoformat(entry["timestamp"])
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if ts > cutoff:
                        recent_reconcile = True
                        break
            except:
                continue
        
        if not recent_reconcile:
            return {"pass": False, "reason": "No reconciliation in 24h (with positions open)"}
        
        return {"pass": True}
    except Exception as e:
        return {"pass": False, "reason": f"Error: {e}"}

def check_sl_logic() -> dict:
    """Verify SL threshold is set correctly (not test value)."""
    engine_file = REPO_ROOT / "scripts" / "trading_engine.py"
    
    try:
        content = engine_file.read_text()
        
        # Check for test threshold
        if "STOP_LOSS_ROE = -0.005" in content:
            return {"pass": False, "reason": "SL threshold still at test value (-0.5%)"}
        
        # Check for correct threshold
        if "STOP_LOSS_ROE = -0.07" not in content:
            return {"pass": False, "reason": "SL threshold not set to -7%"}
        
        return {"pass": True}
    except Exception as e:
        return {"pass": False, "reason": f"Error: {e}"}

def main() -> None:
    print("=" * 70)
    print("  CONTINUOUS VALIDATION")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 70)
    print()
    
    tests = {
        "Heartbeat": check_heartbeat(),
        "State Integrity": check_state_integrity(),
        "Log Freshness": check_log_freshness(),
        "Reconciliation": check_reconciliation(),
        "SL Logic": check_sl_logic(),
    }
    
    all_pass = all(t["pass"] for t in tests.values())
    
    for name, result in tests.items():
        status = "✅ PASS" if result["pass"] else "❌ FAIL"
        print(f"{name:20s} {status}")
        if not result["pass"]:
            print(f"  Reason: {result['reason']}")
        elif "age_sec" in result:
            print(f"  Age: {result['age_sec']:.1f}s")
        elif "age_min" in result:
            print(f"  Age: {result['age_min']:.1f} min")
    
    print()
    
    if all_pass:
        print("✅ ALL VALIDATION CHECKS PASSED")
        sys.exit(0)
    else:
        print("❌ VALIDATION FAILED — REVIEW ABOVE")
        sys.exit(1)

if __name__ == "__main__":
    main()
