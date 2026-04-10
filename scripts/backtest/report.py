#!/usr/bin/env python3
"""
Generate backtest report with GO/NO-GO decision.

Runs the backtest with current risk_params.py settings, loads sweep results
if available, and writes artifacts/BACKTEST_REPORT.md.

Usage:
    python scripts/backtest/report.py --days 90
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.risk_params import (
    STOP_LOSS_ROE,
    TAKE_PROFIT_ROE,
    TIMEOUT_HOURS,
    TRAILING_STOP_ACTIVATE,
    TRAILING_STOP_DISTANCE,
    BACKTEST_INITIAL_CAPITAL,
)
from scripts.backtest.engine import (
    BacktestEngine,
    BacktestResult,
    load_candles,
    load_funding,
    estimate_volumes,
)
from scripts.backtest.strategies.funding_arb import FundingArbStrategy


def load_sweep_top5(sweep_path: Path) -> list[dict]:
    """Load top 5 from sweep_results.csv if it exists."""
    if not sweep_path.exists():
        return []

    rows = []
    with open(sweep_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({k: float(v) if k != "total_trades" else int(float(v))
                         for k, v in row.items()})

    rows.sort(key=lambda r: r.get("net_expectancy", 0), reverse=True)
    return rows[:5]


def build_equity_ascii(result: BacktestResult, width: int = 60, height: int = 15) -> str:
    """Build ASCII equity curve."""
    if not result.closed_trades:
        return "No trades — no equity curve."

    # Build cumulative equity points
    points = [BACKTEST_INITIAL_CAPITAL]
    running = BACKTEST_INITIAL_CAPITAL
    for t in result.closed_trades:
        running += t.net_pnl
        points.append(running)

    if len(points) < 2:
        return f"Single point: ${points[0]:.2f}"

    min_val = min(points)
    max_val = max(points)
    val_range = max_val - min_val if max_val != min_val else 1.0

    # Sample points to fit width
    step = max(1, len(points) // width)
    sampled = [points[i] for i in range(0, len(points), step)]
    if sampled[-1] != points[-1]:
        sampled.append(points[-1])

    lines = []

    # Y-axis labels
    for row in range(height, -1, -1):
        y_val = min_val + (row / height) * val_range
        if row == height or row == height // 2 or row == 0:
            label = f"${y_val:>8.2f} |"
        else:
            label = "           |"

        chars = []
        for val in sampled:
            normalized = (val - min_val) / val_range
            bar_row = int(normalized * height)
            if bar_row == row:
                chars.append("*")
            elif bar_row > row:
                chars.append(" ")
            else:
                chars.append(" ")
        lines.append(label + "".join(chars))

    # X-axis
    lines.append("           +" + "-" * len(sampled))
    lines.append(f"            Trade 1{' ' * max(0, len(sampled) - 15)}Trade {len(points)-1}")

    return "\n".join(lines)


def generate_report(result: BacktestResult, days: int, sweep_top5: list[dict]) -> str:
    """Generate markdown report."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # GO/NO-GO decision
    exp = result.net_expectancy_per_trade
    if exp > 0.30:
        decision = "GO"
        decision_emoji = "GREEN"
        decision_detail = f"Net expectancy ${exp:.4f}/trade > $0.30 threshold"
    elif exp >= 0:
        decision = "CAUTIOUS"
        decision_emoji = "YELLOW"
        decision_detail = f"Net expectancy ${exp:.4f}/trade — positive but below $0.30 confidence threshold"
    else:
        decision = "HALT"
        decision_emoji = "RED"
        decision_detail = f"Net expectancy ${exp:.4f}/trade — strategy loses money after costs"

    report = f"""# Backtest Report

Generated: {now}
Period: {days} days | Initial capital: ${BACKTEST_INITIAL_CAPITAL:.0f}

## Current Parameters

| Parameter | Value |
|-----------|-------|
| Stop Loss | {STOP_LOSS_ROE:.0%} ROE |
| Take Profit | {TAKE_PROFIT_ROE:.0%} ROE |
| Timeout | {TIMEOUT_HOURS}h |
| Trailing Activate | {TRAILING_STOP_ACTIVATE:.0%} ROE |
| Trailing Distance | {TRAILING_STOP_DISTANCE:.0%} |

## Results

| Metric | Value |
|--------|-------|
| Total Trades | {result.total_trades} |
| Wins / Losses | {result.wins} / {result.losses} |
| Win Rate | {result.win_rate:.1%} |
| Gross PnL | ${result.gross_pnl:.2f} |
| Net PnL | ${result.net_pnl:.2f} |
| Net Expectancy | ${result.net_expectancy_per_trade:.4f} / trade |
| Profit Factor | {result.profit_factor:.2f} |
| Sharpe Ratio | {result.sharpe_ratio:.2f} |
| Max Drawdown | {result.max_drawdown_pct:.2%} |
| Final Capital | ${result.final_capital:.2f} |

## Decision: {decision} ({decision_emoji})

{decision_detail}

## Equity Curve

```
{build_equity_ascii(result)}
```

## Equity Data Points

| Trade # | Capital |
|---------|---------|
"""

    running = BACKTEST_INITIAL_CAPITAL
    for i, t in enumerate(result.closed_trades, 1):
        running += t.net_pnl
        if i <= 20 or i == len(result.closed_trades) or i % max(1, len(result.closed_trades) // 20) == 0:
            report += f"| {i} | ${running:.2f} |\n"

    # Top 5 from sweep
    if sweep_top5:
        report += "\n## Top 5 Parameter Combinations (from sweep)\n\n"
        report += "| Rank | Stop Loss | Take Profit | Net Exp/Trade | Win Rate | Sharpe | Trades | Max DD |\n"
        report += "|------|-----------|-------------|---------------|----------|--------|--------|--------|\n"
        for i, r in enumerate(sweep_top5, 1):
            report += (
                f"| {i} | {r.get('stop_loss_pct', 0):+.0f}% | {r.get('take_profit_pct', 0):+.0f}% "
                f"| ${r.get('net_expectancy', 0):.4f} | {r.get('win_rate', 0):.0%} "
                f"| {r.get('sharpe_ratio', 0):.2f} | {int(r.get('total_trades', 0))} "
                f"| {r.get('max_drawdown_pct', 0):.2%} |\n"
            )
    else:
        report += "\n## Parameter Sweep\n\nNo sweep results found. Run `python scripts/backtest/sweep.py` first.\n"

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate backtest report")
    parser.add_argument("--days", type=int, default=90)
    args = parser.parse_args()

    data_dir = REPO_ROOT / "data" / "historical"

    print("Loading data...")
    market_data, timestamps = load_candles(data_dir, args.days)
    funding_data = load_funding(data_dir, args.days)
    volume_data = estimate_volumes(market_data)

    if not timestamps:
        print("No data found. Run scripts/data/download_hl_history.py first.")
        sys.exit(1)

    print(f"Loaded {len(market_data)} assets, {len(timestamps)} bars")

    strategy = FundingArbStrategy()
    engine = BacktestEngine(strategy=strategy)

    print("Running backtest with current parameters...")
    result = engine.run(timestamps, market_data, funding_data, volume_data)

    # Load sweep if available
    sweep_path = REPO_ROOT / "artifacts" / "sweep_results.csv"
    sweep_top5 = load_sweep_top5(sweep_path)

    # Generate report
    report = generate_report(result, args.days, sweep_top5)

    out_path = REPO_ROOT / "artifacts" / "BACKTEST_REPORT.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report)

    print(f"\nReport written to {out_path}")
    print(f"\nDecision: {'GO' if result.net_expectancy_per_trade > 0.30 else 'CAUTIOUS' if result.net_expectancy_per_trade >= 0 else 'HALT'}")


if __name__ == "__main__":
    main()
