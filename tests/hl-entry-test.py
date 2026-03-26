#!/usr/bin/env python3
"""Tests for hl_entry.py — offline, deterministic."""

import importlib.util
import json
import sys
import tempfile
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import Mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

spec = importlib.util.spec_from_file_location("hl_entry", REPO_ROOT / "scripts" / "hl_entry.py")
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)

PASS = 0
FAIL = 0

def check(name, condition):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}")

# --- Entry State ---
print("\n=== Entry State ===")
tmp = Path(tempfile.mkdtemp())
entry.ENTRY_STATE = tmp / "state.json"
entry.GUARDIAN_STATE_FILE = tmp / "guardian.json"

es = entry.EntryState()
ok, _ = es.can_enter()
check("Fresh state allows entry", ok)

es.record_entry()
ok, reason = es.can_enter()
check("Cooldown blocks after entry", not ok)
check("Reason mentions cooldown", "cooldown" in reason.lower() or "Cooldown" in reason)

# --- Safety Gates (mocked) ---
print("\n=== Safety Gates ===")

# Reset state
entry.ENTRY_STATE = tmp / "state2.json"
es2 = entry.EntryState()

signal_good = {
    "asset": "BTC", "direction": "long", "price": 100000.0,
    "funding_8h": -0.001, "annualized": -1.095, "volume_24h": 5000000,
    "score": 15.0, "scanned_at": datetime.now(timezone.utc).isoformat(),
}

signal_weak = {**signal_good, "score": 2.0}

# Mock client
mock_client = Mock()
mock_client.get_perp_state.return_value = {
    "account_value": 20.0, "total_notional": 0.0, "positions": []
}
mock_client.get_spot_usd.return_value = 80.0
mock_client.get_mid.return_value = 100000.0

passed, reason, ctx = entry.check_all_gates(signal_good, mock_client, es2)
check("Strong signal passes all gates", passed)
check("Reason is ALL GATES PASSED", reason == "ALL GATES PASSED")

passed, reason, _ = entry.check_all_gates(signal_weak, mock_client, es2)
check("Weak signal blocked", not passed)

# Duplicate position
mock_client.get_perp_state.return_value = {
    "account_value": 20.0, "total_notional": 10.0,
    "positions": [{"coin": "BTC", "size": 0.001, "direction": "long", "value": 10.0}]
}
passed, reason, _ = entry.check_all_gates(signal_good, mock_client, es2)
check("Duplicate asset blocked", not passed)
check("Reason mentions already have", "already" in reason.lower())

# Max concurrent
mock_client.get_perp_state.return_value = {
    "account_value": 20.0, "total_notional": 30.0,
    "positions": [
        {"coin": "ETH", "size": 0.01, "direction": "long", "value": 10.0},
        {"coin": "SOL", "size": 1.0, "direction": "short", "value": 10.0},
        {"coin": "DOGE", "size": 100, "direction": "long", "value": 10.0},
    ]
}
passed, reason, _ = entry.check_all_gates(signal_good, mock_client, es2)
check("Max concurrent blocked", not passed)

# Circuit breaker halted
(tmp / "guardian.json").write_text(json.dumps({"halted": True, "halt_reason": "test"}))
entry.GUARDIAN_STATE_FILE = tmp / "guardian.json"
mock_client.get_perp_state.return_value = {"account_value": 20.0, "total_notional": 0.0, "positions": []}
passed, reason, _ = entry.check_all_gates(signal_good, mock_client, es2)
check("Circuit breaker halts entry", not passed)

# Max exposure
(tmp / "guardian.json").write_text(json.dumps({"halted": False}))
mock_client.get_perp_state.return_value = {"account_value": 20.0, "total_notional": 45.0, "positions": []}
passed, reason, _ = entry.check_all_gates(signal_good, mock_client, es2)
check("Max exposure blocked", not passed)

# --- Constants ---
print("\n=== Entry Constants ===")
check("Max per trade $15", entry.MAX_POSITION_SIZE_USD == 15.0)
check("Max total $50", entry.MAX_TOTAL_EXPOSURE_USD == 50.0)
check("Max concurrent 3", entry.MAX_CONCURRENT == 3)
check("Min signal score 5", entry.MIN_SIGNAL_SCORE == 5.0)
check("Cooldown 30 min", entry.ENTRY_COOLDOWN_MIN == 30)
check("Default mode is paper", entry.ENTRY_MODE == "paper")
check("Slippage 3%", entry.MAX_SLIPPAGE == 0.03)

# Cleanup
shutil.rmtree(tmp, ignore_errors=True)

print(f"\n{'='*40}")
print(f"  Results: {PASS} passed, {FAIL} failed")
print(f"{'='*40}")
sys.exit(1 if FAIL else 0)
