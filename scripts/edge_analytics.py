#!/usr/bin/env python3
"""
Edge Analytics Engine — Evidence-based strategy evaluation.

Reads from trade-ledger.jsonl and computes edge metrics.
Produces edge_report.json and prints summary.

Usage:
    python scripts/edge_analytics.py
"""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.runtime import WORKSPACE_ROOT as WORKSPACE, LOGS_DIR

# Import ledger
import importlib.util
_spec = importlib.util.spec_from_file_location("trade_ledger", REPO_ROOT / "scripts" / "trade_ledger.py")
_ledger = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ledger)

EDGE_REPORT = WORKSPACE / "edge_report.json"

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

MIN_TRADES_FOR_EVAL = 10        # Minimum trades before any statistical conclusion
MIN_TRADES_FOR_SCALING = 20     # Minimum before considering size increase
VIABLE_EDGE_EXPECTANCY = 0.005  # $0.005 per $1 risked (0.5%)
KILL_THRESHOLD_EXPECTANCY = -0.02  # -2% expectancy = strategy is dead
VIABLE_WIN_RATE = 0.45          # 45% win rate minimum (if reward:risk > 1.5)
VIABLE_PROFIT_FACTOR = 1.2     # Gross profit / gross loss > 1.2

SCORE_BUCKETS = [(0, 5), (5, 7), (7, 10), (10, 20), (20, 100)]


# ---------------------------------------------------------------------------
# Core Analytics
# ---------------------------------------------------------------------------

def compute_metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute edge metrics from closed trade records."""
    if not trades:
        return {"status": "NO_DATA", "trade_count": 0}

    n = len(trades)
    wins = [t for t in trades if t.get("pnl_usd", 0) > 0]
    losses = [t for t in trades if t.get("pnl_usd", 0) <= 0]

    total_pnl = sum(t.get("pnl_usd", 0) for t in trades)
    win_rate = len(wins) / n if n > 0 else 0

    avg_win = sum(t["pnl_usd"] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t["pnl_usd"] for t in losses) / len(losses) if losses else 0

    gross_profit = sum(t["pnl_usd"] for t in wins)
    gross_loss = abs(sum(t["pnl_usd"] for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf") if gross_profit > 0 else 0

    # Expectancy: avg pnl per dollar risked
    avg_size = sum(t.get("position_size_usd", 0) for t in trades) / n if n > 0 else 0
    expectancy = total_pnl / (avg_size * n) if avg_size * n > 0 else 0

    # Drawdown
    equity_curve = []
    running = 0
    peak = 0
    max_dd = 0
    for t in sorted(trades, key=lambda x: x.get("timestamp_close", "")):
        running += t.get("pnl_usd", 0)
        equity_curve.append(running)
        peak = max(peak, running)
        dd = peak - running
        max_dd = max(max_dd, dd)

    # Average hold time
    avg_hold_min = sum(t.get("time_held_minutes", 0) for t in trades) / n if n > 0 else 0

    # Reward:risk ratio
    reward_risk = abs(avg_win / avg_loss) if avg_loss != 0 else float("inf") if avg_win > 0 else 0

    return {
        "status": "EVALUATED" if n >= MIN_TRADES_FOR_EVAL else "INSUFFICIENT_DATA",
        "trade_count": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 4),
        "total_pnl_usd": round(total_pnl, 4),
        "avg_win_usd": round(avg_win, 4),
        "avg_loss_usd": round(avg_loss, 4),
        "reward_risk_ratio": round(reward_risk, 4),
        "profit_factor": round(profit_factor, 4),
        "expectancy_per_dollar": round(expectancy, 6),
        "max_drawdown_usd": round(max_dd, 4),
        "avg_hold_minutes": round(avg_hold_min, 1),
        "avg_position_size": round(avg_size, 2),
    }


def compute_by_strategy(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute metrics grouped by strategy_tag."""
    groups: dict[str, list] = defaultdict(list)
    for t in trades:
        tag = t.get("strategy_tag", "unknown")
        groups[tag].append(t)
    return {tag: compute_metrics(group) for tag, group in groups.items()}


def compute_by_score_bucket(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute metrics grouped by signal score buckets."""
    buckets: dict[str, list] = defaultdict(list)
    for t in trades:
        score = t.get("signal_score", 0)
        for lo, hi in SCORE_BUCKETS:
            if lo <= score < hi:
                buckets[f"{lo}-{hi}"] = buckets.get(f"{lo}-{hi}", [])
                buckets[f"{lo}-{hi}"].append(t)
                break
    return {bucket: compute_metrics(group) for bucket, group in buckets.items()}


def compute_by_exit_reason(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute metrics grouped by exit reason."""
    groups: dict[str, list] = defaultdict(list)
    for t in trades:
        reason = t.get("exit_reason", "unknown")
        groups[reason].append(t)
    return {reason: compute_metrics(group) for reason, group in groups.items()}


# ---------------------------------------------------------------------------
# Decision Engine
# ---------------------------------------------------------------------------

def evaluate_strategy(metrics: dict[str, Any]) -> dict[str, str]:
    """Produce a decision for a strategy based on its metrics."""
    n = metrics.get("trade_count", 0)

    if n < MIN_TRADES_FOR_EVAL:
        return {
            "verdict": "INSUFFICIENT_DATA",
            "action": "CONTINUE_TESTING",
            "reason": f"Only {n}/{MIN_TRADES_FOR_EVAL} trades. Need more data.",
        }

    exp = metrics.get("expectancy_per_dollar", 0)
    wr = metrics.get("win_rate", 0)
    pf = metrics.get("profit_factor", 0)

    if exp <= KILL_THRESHOLD_EXPECTANCY:
        return {
            "verdict": "NEGATIVE_EDGE",
            "action": "KILL_STRATEGY",
            "reason": f"Expectancy {exp:.4f} <= {KILL_THRESHOLD_EXPECTANCY}. Strategy is losing money.",
        }

    if exp >= VIABLE_EDGE_EXPECTANCY and pf >= VIABLE_PROFIT_FACTOR:
        if n >= MIN_TRADES_FOR_SCALING:
            return {
                "verdict": "VIABLE_EDGE",
                "action": "SCALE_UP",
                "reason": f"Expectancy {exp:.4f}, PF {pf:.2f}, {n} trades. Edge appears real.",
            }
        return {
            "verdict": "PROMISING",
            "action": "CONTINUE_TESTING",
            "reason": f"Expectancy {exp:.4f} positive but only {n}/{MIN_TRADES_FOR_SCALING} trades for scaling.",
        }

    return {
        "verdict": "INCONCLUSIVE",
        "action": "CONTINUE_TESTING",
        "reason": f"Expectancy {exp:.4f}, WR {wr:.1%}, PF {pf:.2f}. Not enough signal yet.",
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def generate_report() -> dict[str, Any]:
    """Generate the full edge analytics report."""
    trades = _ledger.load_closed_trades()

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overall": compute_metrics(trades),
        "by_strategy": compute_by_strategy(trades),
        "by_score_bucket": compute_by_score_bucket(trades),
        "by_exit_reason": compute_by_exit_reason(trades),
        "decisions": {},
        "thresholds": {
            "min_trades_eval": MIN_TRADES_FOR_EVAL,
            "min_trades_scaling": MIN_TRADES_FOR_SCALING,
            "viable_expectancy": VIABLE_EDGE_EXPECTANCY,
            "kill_expectancy": KILL_THRESHOLD_EXPECTANCY,
            "viable_win_rate": VIABLE_WIN_RATE,
            "viable_profit_factor": VIABLE_PROFIT_FACTOR,
        },
    }

    # Decisions per strategy
    for tag, metrics in report["by_strategy"].items():
        report["decisions"][tag] = evaluate_strategy(metrics)

    # Overall decision
    report["decisions"]["_overall"] = evaluate_strategy(report["overall"])

    # Write report
    EDGE_REPORT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    report = generate_report()
    overall = report["overall"]
    n = overall.get("trade_count", 0)

    print(f"\n{'='*60}")
    print(f"  EDGE ANALYTICS REPORT")
    print(f"  {report['generated_at']}")
    print(f"{'='*60}")

    if n == 0:
        print("\n  No closed trades in ledger. Run backfill first:")
        print("  python scripts/trade_ledger.py")
        return

    print(f"\n--- OVERALL ({n} trades) ---")
    print(f"  Win rate:     {overall['win_rate']:.1%} ({overall['wins']}W / {overall['losses']}L)")
    print(f"  Total PnL:    ${overall['total_pnl_usd']:+.4f}")
    print(f"  Avg win:      ${overall['avg_win_usd']:+.4f}")
    print(f"  Avg loss:     ${overall['avg_loss_usd']:+.4f}")
    print(f"  Reward:risk:  {overall['reward_risk_ratio']:.2f}")
    print(f"  Profit factor:{overall['profit_factor']:.2f}")
    print(f"  Expectancy:   {overall['expectancy_per_dollar']:+.6f} per $1")
    print(f"  Max drawdown: ${overall['max_drawdown_usd']:.4f}")
    print(f"  Avg hold:     {overall['avg_hold_minutes']:.0f} min")

    print(f"\n--- BY STRATEGY ---")
    for tag, metrics in report["by_strategy"].items():
        decision = report["decisions"].get(tag, {})
        print(f"  {tag}: {metrics['trade_count']} trades | PnL ${metrics['total_pnl_usd']:+.4f} | WR {metrics['win_rate']:.0%} | → {decision.get('action', '?')}")

    print(f"\n--- BY SCORE BUCKET ---")
    for bucket, metrics in report["by_score_bucket"].items():
        print(f"  Score {bucket}: {metrics['trade_count']} trades | PnL ${metrics['total_pnl_usd']:+.4f}")

    print(f"\n--- DECISIONS ---")
    for tag, decision in report["decisions"].items():
        print(f"  {tag}: {decision['verdict']} → {decision['action']}")
        print(f"    {decision['reason']}")

    # Edge readiness level
    if n < 5:
        level = 1
    elif n < MIN_TRADES_FOR_EVAL:
        level = 3
    elif n < MIN_TRADES_FOR_SCALING:
        overall_decision = report["decisions"].get("_overall", {})
        if overall_decision.get("verdict") == "NEGATIVE_EDGE":
            level = 2
        else:
            level = 5
    else:
        overall_decision = report["decisions"].get("_overall", {})
        if overall_decision.get("verdict") == "VIABLE_EDGE":
            level = 8
        elif overall_decision.get("verdict") == "NEGATIVE_EDGE":
            level = 2
        else:
            level = 6

    print(f"\n{'='*60}")
    print(f"  EDGE SYSTEM READINESS: {level}/10")
    print(f"{'='*60}")

    if level <= 3:
        print(f"  → Need {MIN_TRADES_FOR_EVAL - n} more trades before any evaluation")
    elif level <= 5:
        print(f"  → Need {MIN_TRADES_FOR_SCALING - n} more trades before scaling decision")
    elif level >= 8:
        print(f"  → Edge appears viable. Consider increasing position size.")


if __name__ == "__main__":
    main()
