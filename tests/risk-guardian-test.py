#!/usr/bin/env python3
"""Tests for risk-guardian.py — offline, deterministic."""

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

spec = importlib.util.spec_from_file_location("risk_guardian", REPO_ROOT / "scripts" / "risk-guardian.py")
rg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rg)

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

# --- Risk Evaluation ---
print("\n=== Position Evaluation ===")

# HOLD: healthy position
pos_hold = {
    "coin": "ETH", "direction": "long", "size": 0.01,
    "entry_price": 2000.0, "position_value": 15.0,
    "unrealized_pnl": 0.5, "roe": 0.05, "leverage": 10,
    "margin_used": 1.5, "cum_funding": 0.0,
}
r = rg.evaluate_position(pos_hold)
check("Healthy position → HOLD", r["action"] == "HOLD")
check("No triggers", len(r["triggers"]) == 0)

# CLOSE: stop-loss
pos_sl = {**pos_hold, "roe": -0.20, "unrealized_pnl": -3.0}
r = rg.evaluate_position(pos_sl)
check("Stop-loss -20% → CLOSE", r["action"] == "CLOSE")
check("Trigger mentions STOP_LOSS", any("STOP_LOSS" in t for t in r["triggers"]))

# CLOSE: exactly at threshold
pos_exact = {**pos_hold, "roe": -0.15}
r = rg.evaluate_position(pos_exact)
check("Exactly -15% → CLOSE", r["action"] == "CLOSE")

# HOLD: just above threshold
pos_above = {**pos_hold, "roe": -0.14}
r = rg.evaluate_position(pos_above)
check("-14% → HOLD", r["action"] == "HOLD")

# ALERT: over-exposure
pos_over = {**pos_hold, "position_value": 25.0}
r = rg.evaluate_position(pos_over)
check("Over $12 exposure → ALERT", r["action"] == "ALERT")
check("Trigger mentions OVER_EXPOSURE", any("OVER_EXPOSURE" in t for t in r["triggers"]))

# CLOSE takes priority over ALERT
pos_both = {**pos_hold, "roe": -0.20, "position_value": 25.0}
r = rg.evaluate_position(pos_both)
check("SL + over-exposure → CLOSE (SL priority)", r["action"] == "CLOSE")

# --- Guardian State ---
print("\n=== Guardian State ===")

# Clean state for testing
import tempfile
tmp = Path(tempfile.mkdtemp())
rg.GUARDIAN_STATE = tmp / "test-state.json"

state = rg.GuardianState()
check("Fresh state not halted", not state.data["halted"])
check("Fresh peak = 0", state.data["peak_account_value"] == 0.0)

state.update_peak(10.0)
check("Peak updated to 10", state.data["peak_account_value"] == 10.0)

# Circuit breaker: drawdown
safe, _ = state.check_circuit_breaker(8.5)
check("15% drawdown OK", safe)
safe, reason = state.check_circuit_breaker(7.5)
check("25% drawdown halts", not safe)
check("Reason has drawdown", "drawdown" in reason.lower() or "Drawdown" in reason)

state.reset_halt()

# Circuit breaker: consecutive losses
for i in range(5):
    state.record_close("ETH", -1.0)
safe, _ = state.check_circuit_breaker(10.0)
check("5 losses halts", not safe)

state.reset_halt()

# Cooldown
state.data["recent_executions"] = [{
    "coin": "ETH", "action": "close",
    "timestamp": rg.datetime.now(rg.timezone.utc).isoformat(),
}]
check("Recent coin in cooldown", state.is_in_cooldown("ETH"))
check("Different coin not in cooldown", not state.is_in_cooldown("BTC"))

# --- Constants ---
print("\n=== Risk Parameters ===")
check("Stop-loss -15%", rg.STOP_LOSS_ROE == -0.15)
check("Timeout 24h", rg.TIMEOUT_HOURS == 24)
check("Drawdown 15%", rg.DRAWDOWN_PCT == 0.15)
check("Max exposure $12", rg.MAX_EXPOSURE_PER_TRADE == 12.0)
check("Max slippage 3%", rg.MAX_SLIPPAGE == 0.03)
check("Circuit breaker 3 losses", rg.CIRCUIT_BREAKER_LOSSES == 3)
check("Cooldown 120s", rg.EXECUTION_COOLDOWN_SEC == 120)

# --- Simulated Stop-Loss Trigger ---
print("\n=== Simulated Stop-Loss Trigger ===")
# Simulate a position that hits stop-loss
sim_positions = [
    {"coin": "BTC", "direction": "long", "size": 0.001,
     "entry_price": 100000, "position_value": 12.0,
     "unrealized_pnl": -2.5, "roe": -0.20, "leverage": 10,
     "margin_used": 1.2, "cum_funding": 0.0},
    {"coin": "SOL", "direction": "short", "size": 0.5,
     "entry_price": 150.0, "position_value": 10.0,
     "unrealized_pnl": 0.3, "roe": 0.03, "leverage": 5,
     "margin_used": 2.0, "cum_funding": 0.0},
]

evaluated = [rg.evaluate_position(p) for p in sim_positions]
closes = [p for p in evaluated if p["action"] == "CLOSE"]
holds = [p for p in evaluated if p["action"] == "HOLD"]

check("BTC triggers CLOSE (SL)", len(closes) == 1 and closes[0]["coin"] == "BTC")
check("SOL remains HOLD", len(holds) == 1 and holds[0]["coin"] == "SOL")
print(f"  Decision: CLOSE BTC ({closes[0]['triggers'][0]}), HOLD SOL")

# Cleanup
import shutil
shutil.rmtree(tmp, ignore_errors=True)

print(f"\n{'='*40}")
print(f"  Results: {PASS} passed, {FAIL} failed")
print(f"{'='*40}")
sys.exit(1 if FAIL else 0)
