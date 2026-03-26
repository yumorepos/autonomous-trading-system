#!/usr/bin/env python3
"""Tests for edge analytics engine."""

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

spec = importlib.util.spec_from_file_location("edge_analytics", REPO_ROOT / "scripts" / "edge_analytics.py")
ea = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ea)

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

# --- Metrics Computation ---
print("\n=== Metrics ===")

# Empty
m = ea.compute_metrics([])
check("Empty returns NO_DATA", m["status"] == "NO_DATA")

# One loser
trades_1l = [{"pnl_usd": -0.50, "position_size_usd": 15.0, "time_held_minutes": 90, "signal_score": 5.5, "timestamp_close": "2026-03-26T02:00:00Z"}]
m = ea.compute_metrics(trades_1l)
check("1 trade: INSUFFICIENT_DATA", m["status"] == "INSUFFICIENT_DATA")
check("1 loss: win_rate 0", m["win_rate"] == 0)
check("1 loss: total_pnl negative", m["total_pnl_usd"] < 0)

# Mixed: 3 wins, 2 losses
trades_mixed = [
    {"pnl_usd": 1.0, "position_size_usd": 12, "time_held_minutes": 60, "signal_score": 6, "timestamp_close": "2026-03-26T01:00:00Z", "strategy_tag": "funding_arb", "exit_reason": "tp"},
    {"pnl_usd": 0.5, "position_size_usd": 12, "time_held_minutes": 45, "signal_score": 8, "timestamp_close": "2026-03-26T02:00:00Z", "strategy_tag": "funding_arb", "exit_reason": "tp"},
    {"pnl_usd": -0.8, "position_size_usd": 12, "time_held_minutes": 120, "signal_score": 5, "timestamp_close": "2026-03-26T03:00:00Z", "strategy_tag": "funding_arb", "exit_reason": "sl"},
    {"pnl_usd": 0.3, "position_size_usd": 12, "time_held_minutes": 30, "signal_score": 7, "timestamp_close": "2026-03-26T04:00:00Z", "strategy_tag": "momentum", "exit_reason": "tp"},
    {"pnl_usd": -0.4, "position_size_usd": 12, "time_held_minutes": 90, "signal_score": 5, "timestamp_close": "2026-03-26T05:00:00Z", "strategy_tag": "momentum", "exit_reason": "timeout"},
]
m = ea.compute_metrics(trades_mixed)
check("5 trades: INSUFFICIENT_DATA (need 10)", m["status"] == "INSUFFICIENT_DATA")
check("Win rate 60%", m["win_rate"] == 0.6)
check("Total PnL +$0.60", abs(m["total_pnl_usd"] - 0.6) < 0.01)
check("Profit factor > 1", m["profit_factor"] > 1)
check("Expectancy positive", m["expectancy_per_dollar"] > 0)
check("Avg win > 0", m["avg_win_usd"] > 0)
check("Avg loss < 0", m["avg_loss_usd"] < 0)

# --- Strategy Grouping ---
print("\n=== By Strategy ===")
by_strat = ea.compute_by_strategy(trades_mixed)
check("funding_arb group exists", "funding_arb" in by_strat)
check("momentum group exists", "momentum" in by_strat)
check("funding_arb has 3 trades", by_strat["funding_arb"]["trade_count"] == 3)
check("momentum has 2 trades", by_strat["momentum"]["trade_count"] == 2)

# --- Score Buckets ---
print("\n=== By Score Bucket ===")
by_score = ea.compute_by_score_bucket(trades_mixed)
check("5-7 bucket exists", "5-7" in by_score)
check("7-10 bucket exists", "7-10" in by_score)

# --- Decisions ---
print("\n=== Decision Engine ===")

# Insufficient data
d = ea.evaluate_strategy({"trade_count": 5, "expectancy_per_dollar": 0.01, "win_rate": 0.6, "profit_factor": 1.5})
check("5 trades → INSUFFICIENT_DATA", d["verdict"] == "INSUFFICIENT_DATA")

# Negative edge
d = ea.evaluate_strategy({"trade_count": 15, "expectancy_per_dollar": -0.03, "win_rate": 0.3, "profit_factor": 0.5})
check("Negative exp → KILL", d["verdict"] == "NEGATIVE_EDGE")
check("Kill action", d["action"] == "KILL_STRATEGY")

# Viable edge but needs more trades
d = ea.evaluate_strategy({"trade_count": 12, "expectancy_per_dollar": 0.01, "win_rate": 0.55, "profit_factor": 1.5})
check("Positive exp, <20 trades → PROMISING", d["verdict"] == "PROMISING")

# Viable edge with enough trades
d = ea.evaluate_strategy({"trade_count": 25, "expectancy_per_dollar": 0.01, "win_rate": 0.55, "profit_factor": 1.5})
check("Positive exp, 25 trades → VIABLE_EDGE", d["verdict"] == "VIABLE_EDGE")
check("Scale action", d["action"] == "SCALE_UP")

# Inconclusive
d = ea.evaluate_strategy({"trade_count": 15, "expectancy_per_dollar": 0.002, "win_rate": 0.5, "profit_factor": 1.05})
check("Weak edge → INCONCLUSIVE", d["verdict"] == "INCONCLUSIVE")

# --- Thresholds ---
print("\n=== Thresholds ===")
check("Min eval = 10", ea.MIN_TRADES_FOR_EVAL == 10)
check("Min scaling = 20", ea.MIN_TRADES_FOR_SCALING == 20)
check("Kill at -2%", ea.KILL_THRESHOLD_EXPECTANCY == -0.02)
check("Viable at 0.5%", ea.VIABLE_EDGE_EXPECTANCY == 0.005)

print(f"\n{'='*40}")
print(f"  Results: {PASS} passed, {FAIL} failed")
print(f"{'='*40}")
sys.exit(1 if FAIL else 0)
