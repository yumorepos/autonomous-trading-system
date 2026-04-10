#!/usr/bin/env python3
"""
Diagnostic analysis of funding arb strategy + parameter experiments.

Outputs:
1. Detailed trade breakdown (exit reasons, fees vs funding, hold times, per-asset)
2. Parameter variation experiments
3. Comparison table & GO/NO-GO assessment
"""

from __future__ import annotations

import math
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.backtest.engine import (
    BacktestEngine, load_candles, load_funding, estimate_volumes,
)
from scripts.backtest.strategies.funding_arb import FundingArbStrategy
from scripts.backtest.strategies.mean_reversion import MeanReversionStrategy
from scripts.backtest.cost_model import CostModel
from config.risk_params import BACKTEST_INITIAL_CAPITAL


DAYS = 90
CAPITAL = 95.0  # Match validate_edge.py
DATA_DIR = REPO_ROOT / "data" / "historical"


def load_data():
    print("Loading data...")
    market_data, timestamps = load_candles(DATA_DIR, days=DAYS)
    funding_data = load_funding(DATA_DIR, days=DAYS)
    volume_data = estimate_volumes(market_data)
    print(f"  {len(market_data)} assets, {len(timestamps)} hourly bars")
    return market_data, timestamps, funding_data, volume_data


def run_funding_arb(market_data, timestamps, funding_data, volume_data,
                    stop_loss=-0.13, take_profit=0.13, timeout=8,
                    min_funding_apy=0.65, min_volume=500_000,
                    slippage=None, taker_fee=None, capital=CAPITAL):
    """Run funding arb with custom parameters. Returns BacktestResult."""
    strategy = FundingArbStrategy(
        min_funding_apy=min_funding_apy,
        min_volume=min_volume,
        capital=capital,
    )
    cost = CostModel()
    if slippage is not None:
        cost.SLIPPAGE = slippage
    if taker_fee is not None:
        cost.TAKER_FEE = taker_fee

    engine = BacktestEngine(
        strategy=strategy,
        initial_capital=capital,
        cost_model=cost,
        stop_loss_roe=stop_loss,
        take_profit_roe=take_profit,
        timeout_hours=timeout,
    )
    return engine.run(timestamps, market_data, funding_data, volume_data)


def run_mean_reversion(market_data, timestamps, funding_data, volume_data,
                       stop_loss=-0.13, take_profit=0.13, timeout=8,
                       z_threshold=2.0, lookback=24, min_volume=200_000,
                       slippage=None, capital=CAPITAL):
    """Run mean reversion with custom parameters."""
    strategy = MeanReversionStrategy(
        market_data=market_data,
        z_threshold=z_threshold,
        lookback=lookback,
        min_volume=min_volume,
        capital=capital,
    )
    cost = CostModel()
    if slippage is not None:
        cost.SLIPPAGE = slippage

    engine = BacktestEngine(
        strategy=strategy,
        initial_capital=capital,
        cost_model=cost,
        stop_loss_roe=stop_loss,
        take_profit_roe=take_profit,
        timeout_hours=timeout,
    )
    return engine.run(timestamps, market_data, funding_data, volume_data)


def diagnose(result, label=""):
    """Print detailed diagnostic breakdown of trades."""
    trades = result.closed_trades
    if not trades:
        print("  No trades to diagnose.")
        return

    if label:
        print(f"\n{'='*70}")
        print(f"DIAGNOSIS: {label}")
        print(f"{'='*70}")

    # --- Exit reason breakdown ---
    exit_counts = defaultdict(int)
    exit_pnl = defaultdict(float)
    exit_wins = defaultdict(int)
    exit_gross = defaultdict(float)
    exit_fees = defaultdict(float)
    exit_funding = defaultdict(float)
    for t in trades:
        exit_counts[t.exit_reason] += 1
        exit_pnl[t.exit_reason] += t.net_pnl
        exit_gross[t.exit_reason] += t.gross_pnl
        exit_fees[t.exit_reason] += t.fees
        exit_funding[t.exit_reason] += t.funding
        if t.net_pnl > 0:
            exit_wins[t.exit_reason] += 1

    print("\n--- Exit Reason Breakdown ---")
    print(f"{'Reason':<18} {'Count':>5} {'Win%':>7} {'AvgGross':>10} {'AvgFees':>9} {'AvgFund':>9} {'AvgNet':>10} {'TotalNet':>10}")
    print("-" * 90)
    for reason in sorted(exit_counts, key=lambda r: exit_counts[r], reverse=True):
        cnt = exit_counts[reason]
        avg_gross = exit_gross[reason] / cnt
        avg_fees = exit_fees[reason] / cnt
        avg_fund = exit_funding[reason] / cnt
        avg_pnl = exit_pnl[reason] / cnt
        win_pct = exit_wins.get(reason, 0) / cnt * 100
        print(f"{reason:<18} {cnt:>5} {win_pct:>6.1f}% ${avg_gross:>8.4f} ${avg_fees:>7.4f} ${avg_fund:>7.4f} ${avg_pnl:>8.4f} ${exit_pnl[reason]:>8.4f}")

    # --- Aggregate fees vs funding ---
    total_fees = sum(t.fees for t in trades)
    total_funding = sum(t.funding for t in trades)
    total_gross = sum(t.gross_pnl for t in trades)
    total_net = sum(t.net_pnl for t in trades)

    avg_size = sum(t.size_usd for t in trades) / len(trades)
    hold_hours = [(t.exit_time - t.entry_time) / 3600000 for t in trades]
    avg_hold = sum(hold_hours) / len(hold_hours)

    print("\n--- Fees vs Funding Summary ---")
    print(f"  Total gross PnL (price moves):     ${total_gross:>10.4f}")
    print(f"  Total fees paid:                    ${total_fees:>10.4f}")
    print(f"  Total last-hour funding recorded:   ${total_funding:>10.4f}")
    print(f"  Total net PnL:                      ${total_net:>10.4f}")
    print(f"  Avg position size:                  ${avg_size:.2f}")
    print(f"  Avg fee per trade:                  ${total_fees/len(trades):.4f}")
    print(f"  Avg hold time:                      {avg_hold:.1f}h")
    rt_cost_pct = (CostModel.TAKER_FEE + CostModel.SLIPPAGE) * 2 * 100
    print(f"  Round-trip cost:                    {rt_cost_pct:.3f}% of position")
    print(f"  Cost on avg trade (${avg_size:.2f}):        ${avg_size * (CostModel.TAKER_FEE + CostModel.SLIPPAGE) * 2:.4f}")

    # Estimate how much funding would need to be per 8h period to break even on costs
    rt_cost_abs = avg_size * (CostModel.TAKER_FEE + CostModel.SLIPPAGE) * 2
    if avg_hold > 0:
        funding_periods = avg_hold / 8.0
        breakeven_rate = rt_cost_abs / (avg_size * funding_periods) if funding_periods > 0 else 0
        print(f"  Funding periods per trade (avg):    {funding_periods:.2f}")
        print(f"  Breakeven funding rate per 8h:      {breakeven_rate:.6f} ({breakeven_rate * 3 * 365 * 100:.1f}% APY)")

    # --- Hold time analysis ---
    timeouts = [h for t, h in zip(trades, hold_hours) if t.exit_reason == "TIMEOUT"]
    non_timeouts = [h for t, h in zip(trades, hold_hours) if t.exit_reason != "TIMEOUT"]

    print("\n--- Hold Time Analysis ---")
    print(f"  Average hold time:    {avg_hold:.1f}h")
    print(f"  Median hold time:     {sorted(hold_hours)[len(hold_hours)//2]:.1f}h")
    if timeouts:
        print(f"  Avg timeout hold:     {sum(timeouts)/len(timeouts):.1f}h ({len(timeouts)} trades)")
    if non_timeouts:
        print(f"  Avg non-timeout hold: {sum(non_timeouts)/len(non_timeouts):.1f}h ({len(non_timeouts)} trades)")

    # --- Win rate by asset ---
    asset_stats = defaultdict(lambda: {"count": 0, "wins": 0, "pnl": 0.0, "gross": 0.0, "fees": 0.0})
    for t in trades:
        asset_stats[t.asset]["count"] += 1
        asset_stats[t.asset]["pnl"] += t.net_pnl
        asset_stats[t.asset]["gross"] += t.gross_pnl
        asset_stats[t.asset]["fees"] += t.fees
        if t.net_pnl > 0:
            asset_stats[t.asset]["wins"] += 1

    print("\n--- Win Rate by Asset ---")
    print(f"{'Asset':<12} {'Trades':>7} {'Win%':>8} {'GrossPnL':>10} {'Fees':>10} {'NetPnL':>10} {'AvgNet':>10}")
    print("-" * 70)
    for asset in sorted(asset_stats, key=lambda a: asset_stats[a]["count"], reverse=True):
        s = asset_stats[asset]
        wr = s["wins"] / s["count"] * 100
        avg = s["pnl"] / s["count"]
        print(f"{asset:<12} {s['count']:>7} {wr:>7.1f}% ${s['gross']:>8.4f} ${s['fees']:>8.4f} ${s['pnl']:>8.4f} ${avg:>8.4f}")

    # --- Direction breakdown ---
    long_trades = [t for t in trades if t.direction == "long"]
    short_trades = [t for t in trades if t.direction == "short"]
    print("\n--- Direction Breakdown ---")
    for lbl, subset in [("LONG", long_trades), ("SHORT", short_trades)]:
        if not subset:
            continue
        wins = sum(1 for t in subset if t.net_pnl > 0)
        pnl = sum(t.net_pnl for t in subset)
        print(f"  {lbl}: {len(subset)} trades, {wins}/{len(subset)} wins ({wins/len(subset)*100:.1f}%), net PnL ${pnl:.4f}")

    # --- Monthly window profitability ---
    if trades:
        first_entry = min(t.entry_time for t in trades)
        last_exit = max(t.exit_time for t in trades)
        span = last_exit - first_entry
        if span > 0:
            window_ms = span / 3
            windows_pnl = [0.0, 0.0, 0.0]
            windows_count = [0, 0, 0]
            for t in trades:
                w = min(2, int((t.entry_time - first_entry) / window_ms))
                windows_pnl[w] += t.net_pnl
                windows_count[w] += 1

            print("\n--- Monthly Window Profitability ---")
            positive_windows = 0
            for i in range(3):
                status = "POSITIVE" if windows_pnl[i] > 0 else "NEGATIVE"
                if windows_pnl[i] > 0:
                    positive_windows += 1
                print(f"  Window {i+1}: {windows_count[i]} trades, PnL ${windows_pnl[i]:.4f} ({status})")
            print(f"  Positive windows: {positive_windows}/3")


def print_comparison_table(experiments):
    """Print the comparison table."""
    print(f"\n{'='*110}")
    print("COMPARISON TABLE")
    print(f"{'='*110}")
    print(f"{'Experiment':<38} {'Trades':>6} {'WinRate':>7} "
          f"{'Net PnL':>9} {'Exp/Trade':>9} {'PF':>6} {'Sharpe':>7} {'MaxDD':>7} {'AvgHold':>8}")
    print("-" * 110)

    for label, result in experiments.items():
        pf = result.profit_factor
        pf_str = f"{pf:.2f}" if pf < 100 else "inf"
        avg_hold = getattr(result, 'avg_hold_hours', 0.0)
        if avg_hold == 0 and result.closed_trades:
            avg_hold = sum((t.exit_time - t.entry_time) / 3600000 for t in result.closed_trades) / len(result.closed_trades)
        print(f"{label:<38} {result.total_trades:>6} {result.win_rate:>7.1%} "
              f"${result.net_pnl:>8.2f} ${result.net_expectancy_per_trade:>7.4f} "
              f"{pf_str:>6} {result.sharpe_ratio:>7.2f} {result.max_drawdown_pct:>7.2%} {avg_hold:>7.1f}h")


def check_go_criteria(experiments):
    """Check GO criteria for all experiments."""
    print(f"\n{'='*70}")
    print("GO/NO-GO ASSESSMENT (PF > 1.2, positive in 2/3 windows)")
    print(f"{'='*70}")

    for label, result in experiments.items():
        pf = result.profit_factor
        trades = result.closed_trades
        if not trades or result.total_trades < 5:
            continue

        # Check monthly windows
        first_entry = min(t.entry_time for t in trades)
        last_exit = max(t.exit_time for t in trades)
        span = last_exit - first_entry
        if span == 0:
            continue
        window_ms = span / 3

        windows_pnl = [0.0, 0.0, 0.0]
        for t in trades:
            w = min(2, int((t.entry_time - first_entry) / window_ms))
            windows_pnl[w] += t.net_pnl

        pos_windows = sum(1 for p in windows_pnl if p > 0)
        go = "** GO **" if pf > 1.2 and pos_windows >= 2 else "NO-GO"
        marker = ">>>" if go == "** GO **" else "   "

        if pf > 1.0:  # Only show strategies that at least break even
            print(f"  {marker} {label:<35} PF={pf:.2f} Win={pos_windows}/3 -> {go}")


def main():
    market_data, timestamps, funding_data, volume_data = load_data()

    # =====================================================================
    # PART 1: DIAGNOSE baseline
    # =====================================================================
    print("\n" + "=" * 70)
    print("PART 1: DIAGNOSTIC ANALYSIS — BASELINE FUNDING ARB")
    print("=" * 70)
    print(f"Capital: ${CAPITAL}, Cost: {CostModel.TAKER_FEE*100:.3f}% taker + {CostModel.SLIPPAGE*100:.3f}% slippage")

    baseline = run_funding_arb(market_data, timestamps, funding_data, volume_data)
    diagnose(baseline, "Baseline (SL-13%, TP+13%, 8h timeout, 65% APY threshold)")

    # =====================================================================
    # PART 2: PARAMETER EXPERIMENTS
    # =====================================================================
    print("\n" + "=" * 70)
    print("PART 2: PARAMETER EXPERIMENTS")
    print("=" * 70)

    experiments = {}
    experiments["Baseline (current params)"] = baseline

    # --- Wider stop-loss experiments ---
    print("\n  Running stop-loss variations...")
    experiments["Wider SL (-15%)"] = run_funding_arb(
        market_data, timestamps, funding_data, volume_data, stop_loss=-0.15)
    experiments["Wider SL (-20%)"] = run_funding_arb(
        market_data, timestamps, funding_data, volume_data, stop_loss=-0.20)
    experiments["Wider SL (-25%)"] = run_funding_arb(
        market_data, timestamps, funding_data, volume_data, stop_loss=-0.25)

    # --- Longer timeout experiments ---
    print("  Running timeout variations...")
    experiments["Timeout 12h"] = run_funding_arb(
        market_data, timestamps, funding_data, volume_data, timeout=12)
    experiments["Timeout 24h"] = run_funding_arb(
        market_data, timestamps, funding_data, volume_data, timeout=24)
    experiments["Timeout 48h"] = run_funding_arb(
        market_data, timestamps, funding_data, volume_data, timeout=48)

    # --- Higher funding threshold ---
    print("  Running threshold variations...")
    experiments["Threshold 80% APY"] = run_funding_arb(
        market_data, timestamps, funding_data, volume_data, min_funding_apy=0.80)
    experiments["Threshold 100% APY"] = run_funding_arb(
        market_data, timestamps, funding_data, volume_data, min_funding_apy=1.00)
    experiments["Threshold 150% APY"] = run_funding_arb(
        market_data, timestamps, funding_data, volume_data, min_funding_apy=1.50)

    # --- Slippage/fee experiments ---
    print("  Running cost model variations...")
    experiments["No slippage (limit orders)"] = run_funding_arb(
        market_data, timestamps, funding_data, volume_data, slippage=0.0)
    experiments["Maker rebate (-0.002%)"] = run_funding_arb(
        market_data, timestamps, funding_data, volume_data, slippage=0.0, taker_fee=-0.00002)
    experiments["Half slippage (0.025%)"] = run_funding_arb(
        market_data, timestamps, funding_data, volume_data, slippage=0.00025)

    # --- Combinations ---
    print("  Running combination experiments...")
    experiments["SL-15% + Timeout 24h"] = run_funding_arb(
        market_data, timestamps, funding_data, volume_data, stop_loss=-0.15, timeout=24)
    experiments["SL-20% + Timeout 24h"] = run_funding_arb(
        market_data, timestamps, funding_data, volume_data, stop_loss=-0.20, timeout=24)
    experiments["SL-15% + 24h + 100%APY"] = run_funding_arb(
        market_data, timestamps, funding_data, volume_data, stop_loss=-0.15, timeout=24, min_funding_apy=1.00)
    experiments["SL-20% + 24h + 100%APY"] = run_funding_arb(
        market_data, timestamps, funding_data, volume_data, stop_loss=-0.20, timeout=24, min_funding_apy=1.00)
    experiments["SL-20%+48h+100%APY"] = run_funding_arb(
        market_data, timestamps, funding_data, volume_data, stop_loss=-0.20, timeout=48, min_funding_apy=1.00)

    # --- Kitchen sink: best combo + limit orders ---
    experiments["SL-15%+24h+no slip"] = run_funding_arb(
        market_data, timestamps, funding_data, volume_data, stop_loss=-0.15, timeout=24, slippage=0.0)
    experiments["SL-20%+24h+100%APY+no slip"] = run_funding_arb(
        market_data, timestamps, funding_data, volume_data, stop_loss=-0.20, timeout=24, min_funding_apy=1.00, slippage=0.0)
    experiments["SL-20%+48h+100%APY+no slip"] = run_funding_arb(
        market_data, timestamps, funding_data, volume_data, stop_loss=-0.20, timeout=48, min_funding_apy=1.00, slippage=0.0)

    # =====================================================================
    # ALTERNATIVE STRATEGY: Mean Reversion
    # =====================================================================
    print("  Running mean reversion variations...")
    experiments["MeanRev z=2.0 (default exits)"] = run_mean_reversion(
        market_data, timestamps, funding_data, volume_data, z_threshold=2.0)
    experiments["MeanRev z=2.5 (default exits)"] = run_mean_reversion(
        market_data, timestamps, funding_data, volume_data, z_threshold=2.5)
    experiments["MeanRev z=2.0 SL-8% TP+8% 12h"] = run_mean_reversion(
        market_data, timestamps, funding_data, volume_data,
        z_threshold=2.0, stop_loss=-0.08, take_profit=0.08, timeout=12)
    experiments["MeanRev z=1.5 SL-5% TP+5% 6h"] = run_mean_reversion(
        market_data, timestamps, funding_data, volume_data,
        z_threshold=1.5, stop_loss=-0.05, take_profit=0.05, timeout=6)
    experiments["MeanRev z=2.0 SL-5% TP+5% 8h"] = run_mean_reversion(
        market_data, timestamps, funding_data, volume_data,
        z_threshold=2.0, stop_loss=-0.05, take_profit=0.05, timeout=8)
    experiments["MeanRev z=3.0 SL-10% TP+10% 12h"] = run_mean_reversion(
        market_data, timestamps, funding_data, volume_data,
        z_threshold=3.0, stop_loss=-0.10, take_profit=0.10, timeout=12)

    # =====================================================================
    # OUTPUT
    # =====================================================================
    print_comparison_table(experiments)
    check_go_criteria(experiments)

    # Diagnose best-performing
    best_label = max(
        (k for k, v in experiments.items() if v.total_trades >= 10),
        key=lambda k: experiments[k].profit_factor,
        default=None,
    )
    if best_label and best_label != "Baseline (current params)":
        diagnose(experiments[best_label], f"Best: {best_label}")


if __name__ == "__main__":
    main()
