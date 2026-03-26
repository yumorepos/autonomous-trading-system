#!/usr/bin/env python3
"""Tests for hl_executor.py — offline, no exchange calls."""

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

spec = importlib.util.spec_from_file_location("hl_executor", REPO_ROOT / "scripts" / "hl_executor.py")
ex = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ex)

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

# --- Circuit Breaker ---
print("\n=== Circuit Breaker ===")
cb = ex.CircuitBreaker()
cb.reset()

check("Initially allowed", cb.check(1.0)[0])
cb.update_peak(2.0)
check("Peak updated", cb.state["peak_value"] == 2.0)

# Drawdown: 10% should be OK, 25% should be blocked
allowed, _ = cb.check(1.85)  # 7.5% drawdown — OK
check("7.5% drawdown allowed", allowed)
allowed, reason = cb.check(1.5)  # 25% drawdown — blocked
check("25% drawdown blocked", not allowed)
check("Reason mentions drawdown", "drawdown" in reason.lower())

cb.reset()
check("Reset clears halt", not cb.state["halted"])

# Consecutive losses
for i in range(5):
    cb.record_loss(1.0)
allowed, reason = cb.check(10.0)
check("5 losses halts", not allowed)

cb.reset()

# Daily loss
for i in range(11):
    cb.record_loss(1.0)
allowed, reason = cb.check(100.0)
check("$11 daily loss halts", not allowed)

cb.reset()

# Win resets consecutive
cb.record_loss(1.0)
cb.record_loss(1.0)
check("2 losses tracked", cb.state["consecutive_losses"] == 2)
cb.record_win()
check("Win resets consecutive", cb.state["consecutive_losses"] == 0)

# --- Constants ---
print("\n=== Safety Constants ===")
check("Max slippage 5%", ex.MAX_SLIPPAGE == 0.05)
check("Max losses 5", ex.MAX_LOSSES_BEFORE_HALT == 5)
check("Max daily loss $10", ex.MAX_DAILY_LOSS_USD == 10.0)
check("Max drawdown 20%", ex.MAX_DRAWDOWN_PCT == 0.20)
check("Banner mentions close only", "CLOSE" in ex.BANNER)

print(f"\n{'='*40}")
print(f"  Results: {PASS} passed, {FAIL} failed")
print(f"{'='*40}")
sys.exit(1 if FAIL else 0)
