#!/usr/bin/env python3
"""
Parameter sweep over stop-loss and take-profit thresholds.

Grid search:
- Stop-loss: -3% to -15% (step 2%)
- Take-profit: +3% to +20% (step 2%)

Output: artifacts/sweep_results.csv

Usage:
    python scripts/backtest/sweep.py --days 90
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.risk_params import BACKTEST_INITIAL_CAPITAL
from scripts.backtest.engine import (
    BacktestEngine,
    load_candles,
    load_funding,
    estimate_volumes,
)
from scripts.backtest.strategies.funding_arb import FundingArbStrategy


def run_sweep(days: int = 90) -> list[dict]:
    """Run parameter sweep and return results."""
    data_dir = REPO_ROOT / "data" / "historical"

    print("Loading data...")
    market_data, timestamps = load_candles(data_dir, days)
    funding_data = load_funding(data_dir, days)
    volume_data = estimate_volumes(market_data)

    if not timestamps:
        print("No data found. Run scripts/data/download_hl_history.py first.")
        sys.exit(1)

    print(f"Loaded {len(market_data)} assets, {len(timestamps)} bars")

    # Grid
    sl_values = [round(-x / 100, 2) for x in range(3, 16, 2)]  # -0.03 to -0.15
    tp_values = [round(x / 100, 2) for x in range(3, 21, 2)]   # 0.03 to 0.20

    total_combos = len(sl_values) * len(tp_values)
    results = []
    count = 0

    print(f"Running {total_combos} parameter combinations...\n")

    for sl in sl_values:
        for tp in tp_values:
            count += 1
            strategy = FundingArbStrategy()
            engine = BacktestEngine(
                strategy=strategy,
                initial_capital=BACKTEST_INITIAL_CAPITAL,
                stop_loss_roe=sl,
                take_profit_roe=tp,
            )

            result = engine.run(timestamps, market_data, funding_data, volume_data)

            row = {
                "stop_loss_pct": sl * 100,
                "take_profit_pct": tp * 100,
                "total_trades": result.total_trades,
                "wins": result.wins,
                "losses": result.losses,
                "win_rate": round(result.win_rate, 4),
                "gross_pnl": round(result.gross_pnl, 4),
                "net_pnl": round(result.net_pnl, 4),
                "net_expectancy": round(result.net_expectancy_per_trade, 4),
                "max_drawdown_pct": round(result.max_drawdown_pct, 4),
                "sharpe_ratio": round(result.sharpe_ratio, 4),
                "profit_factor": round(result.profit_factor, 4),
                "final_capital": round(result.final_capital, 2),
            }
            results.append(row)

            indicator = "+" if result.net_pnl > 0 else "-"
            print(
                f"  [{count}/{total_combos}] SL={sl*100:+.0f}% TP={tp*100:+.0f}% "
                f"| trades={result.total_trades} win={result.win_rate:.0%} "
                f"net=${result.net_pnl:.2f} exp=${result.net_expectancy_per_trade:.4f} "
                f"sharpe={result.sharpe_ratio:.2f} {indicator}"
            )

    return results


def save_results(results: list[dict], out_path: Path) -> None:
    """Save sweep results to CSV."""
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not results:
        print("No results to save.")
        return

    fieldnames = list(results[0].keys())
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    print(f"\nSaved {len(results)} results to {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Parameter sweep")
    parser.add_argument("--days", type=int, default=90)
    args = parser.parse_args()

    results = run_sweep(args.days)

    out_path = REPO_ROOT / "artifacts" / "sweep_results.csv"
    save_results(results, out_path)

    # Print top 5 by net expectancy
    if results:
        top5 = sorted(results, key=lambda r: r["net_expectancy"], reverse=True)[:5]
        print(f"\nTop 5 by net expectancy:")
        for i, r in enumerate(top5, 1):
            print(
                f"  {i}. SL={r['stop_loss_pct']:+.0f}% TP={r['take_profit_pct']:+.0f}% "
                f"| exp=${r['net_expectancy']:.4f} win={r['win_rate']:.0%} "
                f"sharpe={r['sharpe_ratio']:.2f} trades={r['total_trades']}"
            )


if __name__ == "__main__":
    main()
