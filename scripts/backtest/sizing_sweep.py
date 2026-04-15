#!/usr/bin/env python3
"""
Position sizing & leverage sweep for funding_arb strategy.

For each position size (fixed $ per trade), runs the 180-day backtest with
optimized risk params (SL -15%, timeout 24h, 100% APY threshold) starting
from $95 capital. Sizes >$95 simulate leverage against the same collateral.

Computes per-size: net P&L, max drawdown, largest loss, risk of ruin
(equity touching $20 MIN_BALANCE), monthly return, months-to-double.
Also derives the Kelly-optimal fraction and prints a comparison table
sorted by months-to-double.

Usage:
    python scripts/backtest/sizing_sweep.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.backtest.engine import (
    BacktestEngine,
    BacktestResult,
    load_candles,
    load_funding,
    estimate_volumes,
)
from scripts.backtest.strategies.funding_arb import FundingArbStrategy


STARTING_CAPITAL = 95.0
TARGET_CAPITAL = 194.0   # "double to $194" goal
MIN_BALANCE = 20.0       # live engine halts trading below this
CATASTROPHIC_LOSS_PCT = 0.50   # single-trade loss >50% of starting capital
DAYS = 180

# (label, notional $, leverage note)
SIZE_GRID = [
    ("$10",   10.0, "no leverage"),
    ("$20",   20.0, "no leverage"),
    ("$35",   35.0, "no leverage"),
    ("$50",   50.0, "no leverage"),
    ("$75",   75.0, "no leverage"),
    ("$95",   95.0, "no leverage"),
    ("$142",  142.0, "1.5x"),
    ("$190",  190.0, "2x"),
    ("$285",  285.0, "3x"),
]


class FixedSizeStrategy:
    """Wrap FundingArbStrategy to force a fixed notional per signal."""

    def __init__(self, fixed_size_usd: float):
        # Underlying strategy handles signal selection; we only override sizing.
        self._inner = FundingArbStrategy()
        self.fixed_size_usd = fixed_size_usd

    def __call__(self, state):
        sig = self._inner(state)
        if sig is None:
            return None
        sig["position_size_usd"] = self.fixed_size_usd
        return sig


def _min_equity(result: BacktestResult, starting_capital: float) -> float:
    """Lowest capital value ever touched (starting or any post-trade point)."""
    low = starting_capital
    for _, cap in result.equity_curve:
        if cap < low:
            low = cap
    return low


def _largest_loss(result: BacktestResult) -> float:
    """Most negative single-trade net PnL (0 if none)."""
    losses = [t.net_pnl for t in result.closed_trades if t.net_pnl < 0]
    return min(losses) if losses else 0.0


def _ever_ruined(result: BacktestResult, floor: float) -> bool:
    """True if account balance ever touched the MIN_BALANCE floor."""
    return any(cap <= floor for _, cap in result.equity_curve)


def _catastrophic_loss_count(result: BacktestResult, starting_capital: float,
                             pct: float) -> int:
    """Trades whose single-trade loss exceeded `pct` of starting capital."""
    threshold = -pct * starting_capital
    return sum(1 for t in result.closed_trades if t.net_pnl <= threshold)


def _months_to_target(monthly_pnl: float, starting_capital: float,
                      target: float) -> float:
    """Months of constant monthly $ P&L needed to reach target capital."""
    need = target - starting_capital
    if monthly_pnl <= 0 or need <= 0:
        return float("inf")
    return need / monthly_pnl


def _run_one(size_usd: float, timestamps, market_data, funding_data,
             volume_data) -> BacktestResult:
    strategy = FixedSizeStrategy(fixed_size_usd=size_usd)
    engine = BacktestEngine(
        strategy=strategy,
        initial_capital=STARTING_CAPITAL,
        stop_loss_roe=-0.15,
        take_profit_roe=0.13,
        timeout_hours=24,
    )
    return engine.run(timestamps, market_data, funding_data, volume_data)


def _kelly_fraction(result: BacktestResult) -> tuple[float, float, float, float]:
    """
    Kelly fraction from per-trade ROE distribution.

    Returns (win_rate, avg_win_roe, avg_loss_roe, kelly_fraction_of_position).

    Kelly f* = (p*b - q) / b, where:
        p = win rate, q = 1-p
        b = avg_win / |avg_loss| (payoff ratio)

    f* is the fraction of bankroll to risk per bet. We return it as the
    fraction of position notional (position_size / capital).
    """
    trades = result.closed_trades
    if not trades:
        return (0.0, 0.0, 0.0, 0.0)

    # Normalize each trade's net_pnl by its notional to get ROE
    roes = [t.net_pnl / t.size_usd for t in trades if t.size_usd > 0]
    if not roes:
        return (0.0, 0.0, 0.0, 0.0)

    wins = [r for r in roes if r > 0]
    losses = [r for r in roes if r <= 0]
    p = len(wins) / len(roes)
    q = 1 - p
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    if avg_loss == 0 or avg_win == 0:
        return (p, avg_win, avg_loss, 0.0)
    b = avg_win / abs(avg_loss)
    f = (p * b - q) / b
    return (p, avg_win, avg_loss, f)


def main() -> None:
    data_dir = REPO_ROOT / "data" / "historical"
    print(f"Loading {DAYS}d historical data from {data_dir}...")
    market_data, timestamps = load_candles(data_dir, days=DAYS)
    funding_data = load_funding(data_dir, days=DAYS)
    volume_data = estimate_volumes(market_data)

    if not timestamps:
        print("No historical data found.")
        sys.exit(1)

    print(f"Loaded {len(market_data)} assets, {len(timestamps)} hourly bars\n")
    print(f"Sweeping {len(SIZE_GRID)} position sizes "
          f"(starting capital ${STARTING_CAPITAL:.0f}, SL -15%, TO 24h, 100% APY)...\n")

    months = DAYS / 30.0
    rows: list[dict] = []

    for label, size_usd, lev_note in SIZE_GRID:
        result = _run_one(size_usd, timestamps, market_data, funding_data, volume_data)

        min_eq = _min_equity(result, STARTING_CAPITAL)
        max_dd_pct = result.max_drawdown_pct * 100
        largest_loss = _largest_loss(result)
        ruin = _ever_ruined(result, MIN_BALANCE)
        catastrophic = _catastrophic_loss_count(
            result, STARTING_CAPITAL, CATASTROPHIC_LOSS_PCT
        )
        monthly_pnl = result.net_pnl / months if months > 0 else 0.0
        m2target = _months_to_target(monthly_pnl, STARTING_CAPITAL, TARGET_CAPITAL)

        rows.append({
            "label": label,
            "size_usd": size_usd,
            "lev": lev_note,
            "trades": result.total_trades,
            "win_rate": result.win_rate,
            "net_pnl": result.net_pnl,
            "final_cap": result.final_capital,
            "max_dd_pct": max_dd_pct,
            "largest_loss": largest_loss,
            "catastrophic_losses": catastrophic,
            "min_equity": min_eq,
            "ruin": ruin,
            "monthly_pnl": monthly_pnl,
            "months_to_target": m2target,
            "result": result,
        })

    # Sort by months-to-target ascending (fastest growth first)
    rows_sorted = sorted(rows, key=lambda r: r["months_to_target"])

    # --- Table ---
    print("=" * 124)
    print(f"{'Size':>6}  {'Lev':>11}  {'Trades':>6}  {'WinR':>6}  "
          f"{'Net P&L':>10}  {'FinalCap':>9}  {'MaxDD%':>7}  "
          f"{'MaxLoss$':>9}  {'>50%':>4}  {'MinEq$':>7}  {'Ruin?':>5}  "
          f"{'Mo.P&L':>8}  {f'Mo→${int(TARGET_CAPITAL)}':>10}")
    print("-" * 124)
    for r in rows_sorted:
        m2t_str = "inf" if r["months_to_target"] == float("inf") else f"{r['months_to_target']:.1f}"
        ruin_str = "YES" if r["ruin"] else "no"
        print(
            f"{r['label']:>6}  {r['lev']:>11}  {r['trades']:>6}  "
            f"{r['win_rate']*100:>5.1f}%  "
            f"${r['net_pnl']:>9.2f}  ${r['final_cap']:>8.2f}  "
            f"{r['max_dd_pct']:>6.2f}%  "
            f"${r['largest_loss']:>8.2f}  "
            f"{r['catastrophic_losses']:>4}  "
            f"${r['min_equity']:>6.2f}  "
            f"{ruin_str:>5}  "
            f"${r['monthly_pnl']:>7.2f}  {m2t_str:>10}"
        )
    print("=" * 124)
    print(f"  '>50%' column = trades with single-trade loss > "
          f"{int(CATASTROPHIC_LOSS_PCT*100)}% of starting ${int(STARTING_CAPITAL)}")
    print(f"  'Ruin?' column = did equity ever touch MIN_BALANCE "
          f"(${int(MIN_BALANCE)})?")

    # --- Kelly analysis using the $95 baseline (full capital, no leverage) ---
    baseline = next((r for r in rows if r["label"] == "$95"), rows[0])
    p, avg_win, avg_loss, kelly_f = _kelly_fraction(baseline["result"])
    print("\nKELLY ANALYSIS (derived from $95 baseline trade distribution)")
    print("-" * 60)
    print(f"Win rate (p):          {p*100:.1f}%")
    print(f"Avg win ROE:           {avg_win*100:+.2f}%")
    print(f"Avg loss ROE:          {avg_loss*100:+.2f}%")
    payoff = (avg_win / abs(avg_loss)) if avg_loss else 0.0
    print(f"Payoff ratio (b):      {payoff:.3f}")
    print(f"Kelly fraction (f*):   {kelly_f:.4f}  "
          f"({kelly_f*100:.2f}% of capital per trade)")
    if kelly_f > 0:
        kelly_size = kelly_f * STARTING_CAPITAL
        half_kelly = 0.5 * kelly_size
        print(f"Full-Kelly notional:   ${kelly_size:.2f}  (on ${STARTING_CAPITAL:.0f})")
        print(f"Half-Kelly (safer):    ${half_kelly:.2f}")
    else:
        print("Kelly fraction is non-positive — strategy has negative edge "
              "at this capital; do not size up.")

    # --- Recommendation: balance growth speed vs survival ---
    print("\n" + "=" * 72)
    print(f"RECOMMENDATION — balancing growth vs survival for $95 → ${int(TARGET_CAPITAL)}")
    print("=" * 72)

    fastest = rows_sorted[0]
    # Survivor set: no ruin, no >50% catastrophic losses, max DD < 25%
    survivors = [
        r for r in rows
        if not r["ruin"]
        and r["catastrophic_losses"] == 0
        and r["max_dd_pct"] < 25.0
        and r["monthly_pnl"] > 0
    ]
    survivors_sorted = sorted(survivors, key=lambda r: r["months_to_target"])

    print(f"Fastest (raw):         {fastest['label']:>5} "
          f"({fastest['lev']:>11}) — {fastest['months_to_target']:.1f} mo, "
          f"DD {fastest['max_dd_pct']:.1f}%, "
          f"max single loss ${fastest['largest_loss']:.2f}")

    if survivors_sorted:
        safe = survivors_sorted[0]
        print(f"Fastest that survives: {safe['label']:>5} "
              f"({safe['lev']:>11}) — {safe['months_to_target']:.1f} mo, "
              f"DD {safe['max_dd_pct']:.1f}%, "
              f"max single loss ${safe['largest_loss']:.2f}")
    else:
        safe = fastest

    # Kelly-aligned pick: largest tested size whose notional <= full-Kelly $
    kelly_dollar = kelly_f * STARTING_CAPITAL if kelly_f > 0 else 0.0
    half_k_dollar = 0.5 * kelly_dollar
    kelly_picks = [r for r in rows if r["size_usd"] <= kelly_dollar]
    half_kelly_picks = [r for r in rows if r["size_usd"] <= half_k_dollar]
    if kelly_picks:
        kelly_pick = max(kelly_picks, key=lambda r: r["size_usd"])
        print(f"Closest to full-Kelly:   {kelly_pick['label']:>5} "
              f"(Kelly ${kelly_dollar:.2f})")
    if half_kelly_picks:
        hk_pick = max(half_kelly_picks, key=lambda r: r["size_usd"])
        print(f"Closest to half-Kelly:   {hk_pick['label']:>5} "
              f"(½-Kelly ${half_k_dollar:.2f})")

    print()
    # Qualitative recommendation
    print("VERDICT:")
    if kelly_f <= 0:
        print("  Kelly is non-positive — strategy lacks edge; do not size up.")
    else:
        # Larger than full-Kelly is theoretically suboptimal (higher variance
        # with lower geometric growth). Leveraged sizes above Kelly are
        # 'gambler's ruin' territory even if 180d backtest shows no ruin.
        over_kelly = [r for r in rows if r["size_usd"] > kelly_dollar]
        print(f"  Full-Kelly notional = ${kelly_dollar:.2f}  "
              f"(½-Kelly = ${half_k_dollar:.2f}).")
        print(f"  Sizes above full-Kelly ({', '.join(r['label'] for r in over_kelly) or 'none'}) "
              "over-bet the edge:")
        print(f"    even though backtest ruin=0, variance dominates and")
        print(f"    geometric growth DECREASES vs Kelly over the long run.")
        print(f"  Sizes at/under ½-Kelly sacrifice growth for margin of safety.")
        print()
        print(f"  For $95 → ${int(TARGET_CAPITAL)} with survival as a hard constraint:")
        rec = safe
        print(f"    -> USE {rec['label']} ({rec['lev']})")
        print(f"       reaches target in ~{rec['months_to_target']:.1f} months,")
        print(f"       max DD {rec['max_dd_pct']:.1f}%, "
              f"worst single loss ${rec['largest_loss']:.2f} "
              f"({abs(rec['largest_loss'])/STARTING_CAPITAL*100:.1f}% of start cap),")
        print(f"       no catastrophic (>50%) losses, no ruin event in 180d.")
        if rec["size_usd"] > kelly_dollar:
            print(f"       NOTE: this is above full-Kelly (${kelly_dollar:.2f}); "
                  "growth-maximizing but variance-heavy.")
        elif rec["size_usd"] > half_k_dollar:
            print(f"       (between ½-Kelly and full-Kelly — standard aggressive range)")
        else:
            print(f"       (at or below ½-Kelly — conservative)")


if __name__ == "__main__":
    main()
