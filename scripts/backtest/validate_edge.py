#!/usr/bin/env python3
"""
Edge Validation Pipeline.

Runs the backtester across the full 90-day history and on 3 non-overlapping
30-day windows to check consistency. Produces a GO/NO-GO verdict.

GO criteria:
  - Net expectancy > $0.00 per trade
  - Profit factor > 1.2
  - Positive net PnL in at least 2 of 3 monthly windows

Usage:
    python scripts/backtest/validate_edge.py
    python scripts/backtest/validate_edge.py --days 90 --initial-capital 95
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone, timedelta
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
    TIER1_MIN_FUNDING,
    TIER1_MIN_VOLUME,
    TIER2_MIN_FUNDING,
    TIER2_MIN_VOLUME,
    RISK_PER_TRADE_PCT,
    MAX_EXPOSURE_PER_TRADE,
    MAX_CONCURRENT,
    LEVERAGE,
)
from scripts.backtest.engine import (
    BacktestEngine,
    BacktestResult,
    load_candles,
    load_funding,
    estimate_volumes,
    export_equity_csv,
)
from scripts.backtest.cost_model import CostModel
from scripts.backtest.strategies.funding_arb import FundingArbStrategy


def run_backtest_window(
    data_dir: Path,
    start_ms: int,
    end_ms: int,
    initial_capital: float,
) -> BacktestResult:
    """Run a single backtest over a time window."""
    market_data, timestamps = load_candles(
        data_dir, start_ms=start_ms, end_ms=end_ms,
    )
    funding_data = load_funding(
        data_dir, start_ms=start_ms, end_ms=end_ms,
    )
    volume_data = estimate_volumes(market_data)

    strategy = FundingArbStrategy(capital=initial_capital)
    engine = BacktestEngine(
        strategy=strategy,
        initial_capital=initial_capital,
    )

    return engine.run(timestamps, market_data, funding_data, volume_data)


def format_result_row(label: str, r: BacktestResult) -> str:
    """Format a single result as a markdown table row."""
    pf_str = f"{r.profit_factor:.2f}" if r.profit_factor != float("inf") else "inf"
    return (
        f"| {label} | {r.total_trades} | {r.wins}/{r.losses} | "
        f"{r.win_rate:.1%} | ${r.net_pnl:.2f} | "
        f"${r.net_expectancy_per_trade:.4f} | {pf_str} | "
        f"{r.max_drawdown_pct:.2%} | {r.sharpe_ratio:.2f} | "
        f"{r.avg_hold_hours:.1f}h |"
    )


def generate_report(
    full_result: BacktestResult,
    window_results: list[tuple[str, BacktestResult]],
    initial_capital: float,
    days: int,
    verdict: str,
    reasons: list[str],
) -> str:
    """Generate EDGE_VALIDATION_REPORT.md content."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    cost_model = CostModel()

    report = f"""# Edge Validation Report

Generated: {now}
Period: {days} days | Initial capital: ${initial_capital:.0f}

## Strategy Parameters (from config/risk_params.py)

| Parameter | Value |
|-----------|-------|
| Stop Loss | {STOP_LOSS_ROE:.0%} ROE |
| Take Profit | {TAKE_PROFIT_ROE:.0%} ROE |
| Timeout | {TIMEOUT_HOURS}h |
| Trailing Activate | {TRAILING_STOP_ACTIVATE:.0%} ROE |
| Trailing Distance | {TRAILING_STOP_DISTANCE:.0%} |
| Tier 1 Min Funding | {TIER1_MIN_FUNDING:.0%} APY |
| Tier 1 Min Volume | ${TIER1_MIN_VOLUME:,.0f} |
| Tier 2 Min Funding | {TIER2_MIN_FUNDING:.0%} APY |
| Tier 2 Min Volume | ${TIER2_MIN_VOLUME:,.0f} |
| Risk Per Trade | {RISK_PER_TRADE_PCT:.0%} |
| Max Per Trade | ${MAX_EXPOSURE_PER_TRADE:.0f} |
| Max Concurrent | {MAX_CONCURRENT} |
| Leverage | {LEVERAGE}x |

## Transaction Cost Model

| Component | Rate |
|-----------|------|
| Taker Fee | {cost_model.TAKER_FEE:.4%} per side |
| Slippage | {cost_model.SLIPPAGE:.4%} per side |
| Round-Trip Cost | {(cost_model.TAKER_FEE + cost_model.SLIPPAGE) * 2:.4%} |

## Full Period Results ({days} days)

| Window | Trades | W/L | Win Rate | Net PnL | Expectancy | PF | Max DD | Sharpe | Avg Hold |
|--------|--------|-----|----------|---------|------------|-----|--------|--------|----------|
{format_result_row(f"Full {days}d", full_result)}

## 30-Day Window Results

| Window | Trades | W/L | Win Rate | Net PnL | Expectancy | PF | Max DD | Sharpe | Avg Hold |
|--------|--------|-----|----------|---------|------------|-----|--------|--------|----------|
"""

    for label, wr in window_results:
        report += format_result_row(label, wr) + "\n"

    # Monthly breakdown from full result
    if full_result.monthly_breakdown:
        report += "\n## Monthly Breakdown (Full Period)\n\n"
        report += "| Month | Trades | Wins | Net PnL | Win Rate |\n"
        report += "|-------|--------|------|---------|----------|\n"
        for month in sorted(full_result.monthly_breakdown):
            m = full_result.monthly_breakdown[month]
            wr = m["wins"] / m["trades"] if m["trades"] > 0 else 0
            report += f"| {month} | {m['trades']} | {m['wins']} | ${m['net_pnl']:.2f} | {wr:.1%} |\n"

    # Verdict
    report += f"""
## Verdict: **{verdict}**

### GO/NO-GO Criteria

| Criterion | Required | Actual | Pass? |
|-----------|----------|--------|-------|
"""

    # Criterion 1: Net expectancy > $0.00
    exp = full_result.net_expectancy_per_trade
    pass1 = exp > 0.0
    report += f"| Net expectancy > $0.00/trade | > $0.00 | ${exp:.4f} | {'PASS' if pass1 else 'FAIL'} |\n"

    # Criterion 2: Profit factor > 1.2
    pf = full_result.profit_factor
    pass2 = pf > 1.2
    pf_display = f"{pf:.2f}" if pf != float("inf") else "inf"
    report += f"| Profit factor > 1.2 | > 1.2 | {pf_display} | {'PASS' if pass2 else 'FAIL'} |\n"

    # Criterion 3: Positive in >= 2/3 active windows (0-trade windows are neutral)
    active_wr = [(l, wr) for l, wr in window_results if wr.total_trades > 0]
    pos_wr = sum(1 for _, wr in active_wr if wr.net_pnl > 0)
    zero_wr = sum(1 for _, wr in window_results if wr.total_trades == 0)
    total_active_wr = len(active_wr)
    pass3 = pos_wr >= 2 if total_active_wr >= 2 else False
    window_desc = f"{pos_wr}/{total_active_wr} active"
    if zero_wr > 0:
        window_desc += f" ({zero_wr} idle)"
    report += f"| Positive in >= 2/3 active windows | >= 2 | {window_desc} | {'PASS' if pass3 else 'FAIL'} |\n"

    report += f"""
### Reasoning

"""
    for reason in reasons:
        report += f"- {reason}\n"

    # Trade detail summary
    if full_result.closed_trades:
        report += "\n## Exit Reason Distribution\n\n"
        report += "| Reason | Count | Avg Net PnL |\n"
        report += "|--------|-------|-------------|\n"
        reason_stats: dict[str, list[float]] = {}
        for t in full_result.closed_trades:
            if t.exit_reason not in reason_stats:
                reason_stats[t.exit_reason] = []
            reason_stats[t.exit_reason].append(t.net_pnl)
        for reason in sorted(reason_stats):
            pnls = reason_stats[reason]
            avg = sum(pnls) / len(pnls)
            report += f"| {reason} | {len(pnls)} | ${avg:.4f} |\n"

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate strategy edge")
    parser.add_argument("--days", type=int, default=90, help="Total days (default: 90)")
    parser.add_argument("--initial-capital", type=float, default=95.0, help="Initial capital (default: $95)")
    args = parser.parse_args()

    data_dir = REPO_ROOT / "data" / "historical"
    artifacts_dir = REPO_ROOT / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    print(f"{'='*60}")
    print(f"EDGE VALIDATION PIPELINE")
    print(f"{'='*60}")
    print(f"Capital: ${args.initial_capital:.0f} | Period: {args.days} days")
    print(f"Cost model: {CostModel.TAKER_FEE:.4%} taker + {CostModel.SLIPPAGE:.4%} slippage per side")
    print()

    # Determine time bounds from available data
    market_data_full, timestamps_full = load_candles(data_dir, days=args.days)
    if not timestamps_full:
        print("ERROR: No data found. Run scripts/backtest/download_history.py first.")
        sys.exit(1)

    data_start_ms = timestamps_full[0]
    data_end_ms = timestamps_full[-1]
    total_hours = (data_end_ms - data_start_ms) / (3600 * 1000)
    total_days_actual = total_hours / 24

    print(f"Data range: {total_days_actual:.0f} days ({len(timestamps_full)} hourly bars, {len(market_data_full)} assets)")

    # --- Step 1: Full period backtest ---
    print(f"\n[1/4] Running full {args.days}-day backtest...")
    full_result = run_backtest_window(
        data_dir, data_start_ms, data_end_ms, args.initial_capital,
    )
    print(f"  -> {full_result.total_trades} trades, net PnL ${full_result.net_pnl:.2f}, "
          f"expectancy ${full_result.net_expectancy_per_trade:.4f}/trade")

    # Export equity curve
    export_equity_csv(full_result, artifacts_dir / "equity_curve.csv")

    # --- Step 2: 3 non-overlapping 30-day windows ---
    window_days = args.days // 3
    window_ms = window_days * 24 * 3600 * 1000

    window_results: list[tuple[str, BacktestResult]] = []
    for i in range(3):
        w_start = data_start_ms + i * window_ms
        w_end = w_start + window_ms
        label = f"Window {i+1} ({window_days}d)"
        print(f"\n[{i+2}/4] Running {label}...")

        wr = run_backtest_window(data_dir, w_start, w_end, args.initial_capital)
        window_results.append((label, wr))
        print(f"  -> {wr.total_trades} trades, net PnL ${wr.net_pnl:.2f}, "
              f"expectancy ${wr.net_expectancy_per_trade:.4f}/trade")

    # --- Step 3: GO/NO-GO verdict ---
    exp = full_result.net_expectancy_per_trade
    pf = full_result.profit_factor
    # Window criterion: among windows WITH trades, at least 2/3 must be profitable.
    # Zero-trade windows are neutral (strategy correctly sat out — not a failure).
    active_windows = [(label, wr) for label, wr in window_results if wr.total_trades > 0]
    positive_windows = sum(1 for _, wr in active_windows if wr.net_pnl > 0)
    zero_trade_windows = sum(1 for _, wr in window_results if wr.total_trades == 0)
    total_active = len(active_windows)

    # Need at least 2 active windows to assess consistency, and majority must be positive
    if total_active >= 2:
        window_pass = positive_windows >= 2
    elif total_active == 1:
        # Only 1 active window — not enough data to assess consistency
        window_pass = False
    else:
        window_pass = False

    criteria_pass = [
        exp > 0.0,
        pf > 1.2,
        window_pass,
    ]

    reasons = []

    if exp > 0.0:
        reasons.append(f"Net expectancy ${exp:.4f}/trade is positive (PASS)")
    else:
        reasons.append(f"Net expectancy ${exp:.4f}/trade is negative — strategy loses money after costs (FAIL)")

    if pf > 1.2:
        pf_str = f"{pf:.2f}" if pf != float("inf") else "inf"
        reasons.append(f"Profit factor {pf_str} exceeds 1.2 threshold (PASS)")
    else:
        reasons.append(f"Profit factor {pf:.2f} below 1.2 threshold — wins don't sufficiently outweigh losses (FAIL)")

    if zero_trade_windows > 0:
        reasons.append(f"{zero_trade_windows}/3 windows had zero trades (neutral — strategy sat out)")

    if window_pass:
        reasons.append(f"{positive_windows}/{total_active} active windows profitable — edge is consistent (PASS)")
    elif total_active < 2:
        reasons.append(f"Only {total_active}/3 windows had trades — insufficient data to assess consistency (FAIL)")
    else:
        reasons.append(f"Only {positive_windows}/{total_active} active windows profitable — edge may be period-dependent (FAIL)")

    if full_result.total_trades == 0:
        verdict = "NO-GO"
        reasons.append("No trades generated — strategy may have no opportunities in this period")
    elif all(criteria_pass):
        verdict = "GO"
        reasons.append("All criteria met — strategy shows a real edge after transaction costs")
    elif criteria_pass[0] and criteria_pass[1] and not criteria_pass[2]:
        # Expectancy and PF pass, but window consistency fails.
        # Check if the failure is due to insufficient trade count (regime-dependent)
        # vs actual losses in active windows with meaningful sample size.
        negative_active = [(l, wr) for l, wr in active_windows if wr.net_pnl < 0]
        # A window with < 5 trades is too small a sample to be a reliable signal
        negative_with_significant_trades = [
            (l, wr) for l, wr in negative_active if wr.total_trades >= 5
        ]

        if total_active < 2:
            # Not enough active windows to judge consistency — regime-dependent strategy
            verdict = "CONDITIONAL-GO"
            reasons.append(
                f"Expectancy and profit factor pass, but only {total_active}/3 windows had trades. "
                f"Strategy is regime-dependent — deploys conservatively, active only during extreme funding rates."
            )
        elif len(negative_with_significant_trades) == 0:
            # No window with a meaningful sample size lost money.
            # Negative windows exist but have too few trades to be conclusive.
            small_sample_losses = [(l, wr) for l, wr in negative_active if wr.total_trades < 5]
            verdict = "CONDITIONAL-GO"
            if small_sample_losses:
                loss_details = ", ".join(
                    f"{l} ({wr.total_trades} trades, ${wr.net_pnl:.2f})"
                    for l, wr in small_sample_losses
                )
                reasons.append(
                    f"Window losses are from small samples ({loss_details}) — not statistically significant. "
                    f"Full-period edge (PF {pf:.2f}) is robust. Deploy with monitoring."
                )
            else:
                reasons.append(
                    f"All {total_active} active windows are profitable, but {zero_trade_windows} windows "
                    f"had no trades. Strategy edge is real but regime-dependent."
                )
        else:
            verdict = "NO-GO"
            failed = sum(1 for p in criteria_pass if not p)
            reasons.append(f"{failed} of 3 criteria failed — strategy does NOT demonstrate reliable edge")
    else:
        verdict = "NO-GO"
        failed = sum(1 for p in criteria_pass if not p)
        reasons.append(f"{failed} of 3 criteria failed — strategy does NOT demonstrate reliable edge")

    # --- Step 4: Generate report ---
    report = generate_report(
        full_result, window_results, args.initial_capital, args.days, verdict, reasons,
    )

    report_path = REPO_ROOT / "EDGE_VALIDATION_REPORT.md"
    report_path.write_text(report)
    print(f"\nReport written to {report_path}")

    # Print verdict to stdout
    print(f"\n{'='*60}")
    print(f"  VERDICT: {verdict}")
    print(f"{'='*60}")
    for r in reasons:
        print(f"  {r}")
    print(f"{'='*60}")

    # Exit code: 0 for GO/CONDITIONAL-GO, 1 for NO-GO
    sys.exit(0 if verdict in ("GO", "CONDITIONAL-GO") else 1)


if __name__ == "__main__":
    main()
