#!/usr/bin/env python3
"""Tests for daily-review.py — run directly: python tests/daily-review-test.py"""

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import Mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# Import via importlib because filename has hyphen
import importlib.util
_spec = importlib.util.spec_from_file_location("daily_review", REPO_ROOT / "scripts" / "daily-review.py")
dr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dr)

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

# --- Age Hours ---
print("\n=== Age Hours ===")
check("None returns 0", dr.age_hours(None) == 0.0)
check("Invalid string returns 0", dr.age_hours("not-a-date") == 0.0)
recent = (dr.utcnow() - timedelta(hours=2)).isoformat()
check("Recent position ~2h", 1.9 < dr.age_hours(recent) < 2.2)

# --- Evaluate Position ---
print("\n=== Position Evaluation ===")
def make_pos(**kw):
    base = {"exchange": "Hyperliquid", "asset": "BTC", "direction": "long",
            "entry_price": 100000.0, "opened_at": (dr.utcnow() - timedelta(hours=10)).isoformat(),
            "timeout_hours": 72, "stop_loss_pct": 0.15, "take_profit_pct": 0.25}
    base.update(kw)
    return base

r = dr.evaluate_position(make_pos(), {"BTC": 105000.0})
check("HOLD within thresholds", r["decision"] == "HOLD")

r = dr.evaluate_position(make_pos(opened_at=(dr.utcnow() - timedelta(hours=100)).isoformat()), {"BTC": 105000.0})
check("EXIT_TIMEOUT after 100h", r["decision"] == "EXIT_TIMEOUT")

r = dr.evaluate_position(make_pos(), {"BTC": 80000.0})
check("EXIT_STOPLOSS at -20%", r["decision"] == "EXIT_STOPLOSS")

r = dr.evaluate_position(make_pos(), {"BTC": 130000.0})
check("EXIT_TAKEPROFIT at +30%", r["decision"] == "EXIT_TAKEPROFIT")

r = dr.evaluate_position(make_pos(asset="UNKNOWN", opened_at=(dr.utcnow() - timedelta(hours=30)).isoformat()), {})
check("STALE with no price", r["decision"] == "STALE")

r = dr.evaluate_position(make_pos(direction="short"), {"BTC": 95000.0})
check("Short P&L positive on drop", r["pnl_pct"] > 0)

# --- Paper Trades ---
print("\n=== Paper Trades ===")
sig = {"exchange": "Hyperliquid", "asset": "ETH", "direction": "long", "entry_price": 3000.0, "score": 5.0}
check("Open within limits", dr.paper_open_position(sig, 2) is not None)
check("Blocked at max positions", dr.paper_open_position(sig, 5) is None)

pos = {"trade_id": "t1", "exchange": "HL", "asset": "BTC", "entry_price": 100000, "current_price": 90000, "pnl_pct": -0.1}
close = dr.paper_close_position(pos, "stop-loss")
check("Close record event", close["event"] == "paper_close")

# --- Signal Scanning ---
print("\n=== Signal Scanning ===")
universe = [{"name": "TEST"}]
contexts = [{"funding": "0.001", "midPx": "10.0", "dayNtlVlm": "500000"}]
sigs = dr.scan_hyperliquid_signals(universe, contexts, set())
check("HL funding anomaly detected", len(sigs) == 1 and sigs[0]["asset"] == "TEST")
check("HL skip existing asset", len(dr.scan_hyperliquid_signals(universe, contexts, {"TEST"})) == 0)

pm = [{"conditionId": "0x1", "question": "Test?", "volumeNum": 100000, "volume24hr": 50000, "outcomePrices": '["0.35","0.65"]', "active": True}]
sigs = dr.scan_polymarket_signals(pm, set())
check("PM volume mover detected", len(sigs) == 1)

# --- Report ---
print("\n=== Report Generation ===")
report = dr.generate_report([], [], [], [], [], True, True, 229, 50)
check("Report has paper banner", "PAPER TRADING ONLY" in report)
check("Report has no positions msg", "No open positions" in report)

# --- Summary ---
print(f"\n{'='*40}")
print(f"  Results: {PASS} passed, {FAIL} failed")
print(f"{'='*40}")
sys.exit(1 if FAIL else 0)
