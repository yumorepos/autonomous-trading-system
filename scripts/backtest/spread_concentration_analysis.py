"""
Analyze WHY XPL dominates cross-exchange funding-spread returns, and
whether the pattern is repeatable.

Pure analysis — reads, never writes (except the printed report).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

TRADES_CSV = Path("data/spreads/historical_spread_analysis.csv")
HL_CSV = Path("data/historical/funding_rates.csv")
KR_CSV = Path("data/historical/kraken_funding_rates.csv")

HL_RT_FEE = 0.0001 + 0.00035
KR_RT_FEE = 0.0002 + 0.0005
ROUND_TRIP_FEE = HL_RT_FEE + KR_RT_FEE   # 0.00115
EXIT_MIN = 0.0002
CAPITAL_PER_LEG = 47.50
FEE_DOLLARS = ROUND_TRIP_FEE * CAPITAL_PER_LEG


def to_dt(ts_ms):
    return pd.to_datetime(ts_ms, unit="ms", utc=True)


def fmt_ts(ts_ms):
    return to_dt(ts_ms).strftime("%Y-%m-%d %H:%M")


def load():
    trades = pd.read_csv(TRADES_CSV)
    trades["entry_dt"] = to_dt(trades["entry_time"])
    trades["exit_dt"] = to_dt(trades["exit_time"])
    trades["month"] = trades["entry_dt"].dt.strftime("%Y-%m")
    trades["entry_hour_utc"] = trades["entry_dt"].dt.hour
    hl = pd.read_csv(HL_CSV).rename(columns={"funding_rate_8h": "hl_rate_8h"})
    kr = pd.read_csv(KR_CSV).rename(columns={"funding_rate_8h": "kr_rate_8h"})
    return trades, hl, kr


# ------------------------ Re-simulation helper -----------------------------
# So we can evaluate strategy variants quickly, replay the backtest with
# configurable entry / exit / hold filters.
HL_SNAP_TOL_MS = 2 * 3600 * 1000


def aligned_data(hl: pd.DataFrame, kr: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for asset in sorted(set(kr["asset"]).intersection(hl["asset"])):
        hl_a = hl[hl["asset"] == asset].sort_values("timestamp")
        kr_a = kr[kr["asset"] == asset].sort_values("timestamp")
        if hl_a.empty or kr_a.empty:
            continue
        m = pd.merge_asof(
            kr_a[["timestamp", "asset", "kr_rate_8h"]],
            hl_a[["timestamp", "hl_rate_8h"]],
            on="timestamp", direction="nearest", tolerance=HL_SNAP_TOL_MS,
        ).dropna(subset=["hl_rate_8h"])
        parts.append(m)
    merged = pd.concat(parts, ignore_index=True)
    merged["spread"] = merged["hl_rate_8h"] - merged["kr_rate_8h"]
    return merged


def simulate(merged: pd.DataFrame,
             entry_threshold: float = ROUND_TRIP_FEE,
             exit_min: float = EXIT_MIN,
             min_hold_periods: int = 1,
             asset_filter=None) -> pd.DataFrame:
    trades = []
    assets = sorted(merged["asset"].unique())
    if asset_filter is not None:
        assets = [a for a in assets if a in asset_filter]
    for asset in assets:
        df = merged[merged["asset"] == asset].sort_values("timestamp").reset_index(drop=True)
        in_trade = False
        direction = 0
        entry_ts = None
        cum_pct = 0.0
        samples = []
        hold = 0
        for _, row in df.iterrows():
            spread = row["spread"]
            ts = int(row["timestamp"])
            if not in_trade:
                if abs(spread) > entry_threshold:
                    in_trade = True
                    direction = 1 if spread > 0 else -1
                    entry_ts = ts
                    cum_pct = 0.0
                    samples = []
                    hold = 0
                continue
            same_sign = (spread > 0) == (direction > 0)
            below_min = abs(spread) < exit_min
            can_exit = hold >= min_hold_periods
            if ((not same_sign) or below_min) and can_exit:
                gross = cum_pct * CAPITAL_PER_LEG
                trades.append({
                    "asset": asset,
                    "entry_time": entry_ts, "exit_time": ts,
                    "direction": "short_HL_long_KR" if direction > 0 else "long_HL_short_KR",
                    "avg_spread": float(np.mean(samples)) if samples else 0.0,
                    "hold_periods": hold,
                    "gross_pnl": gross,
                    "fees": FEE_DOLLARS,
                    "total_pnl": gross - FEE_DOLLARS,
                })
                in_trade = False
                continue
            cum_pct += spread * direction * 0.5
            samples.append(abs(spread))
            hold += 1
        if in_trade and hold > 0:
            gross = cum_pct * CAPITAL_PER_LEG
            trades.append({
                "asset": asset,
                "entry_time": entry_ts, "exit_time": int(df.iloc[-1]["timestamp"]),
                "direction": "short_HL_long_KR" if direction > 0 else "long_HL_short_KR",
                "avg_spread": float(np.mean(samples)) if samples else 0.0,
                "hold_periods": hold,
                "gross_pnl": gross,
                "fees": FEE_DOLLARS,
                "total_pnl": gross - FEE_DOLLARS,
            })
    return pd.DataFrame(trades)


# ------------------------ Sections -----------------------------------------

def section_header(title):
    print()
    print("=" * 74)
    print(title)
    print("=" * 74)


def xpl_deep_dive(trades: pd.DataFrame, hl: pd.DataFrame, kr: pd.DataFrame):
    section_header("1. XPL DEEP DIVE")
    xpl = trades[trades["asset"] == "XPL"].sort_values("entry_time").reset_index(drop=True)
    others = trades[trades["asset"] != "XPL"]

    print(f"XPL trades:           {len(xpl)}")
    print(f"XPL total P&L:        ${xpl['total_pnl'].sum():.4f}")
    print(f"XPL % of all P&L:     {100 * xpl['total_pnl'].sum() / trades['total_pnl'].sum():.1f}%")
    print(f"XPL avg spread size:  {xpl['avg_spread'].mean()*100:.4f}%")
    print(f"Other assets avg:     {others['avg_spread'].mean()*100:.4f}%")
    print(f"XPL avg hold:         {xpl['hold_periods'].mean():.2f} periods")
    print(f"Others avg hold:      {others['hold_periods'].mean():.2f} periods")

    # Directional bias
    dirs = xpl["direction"].value_counts()
    print(f"\nXPL direction breakdown:")
    for d, n in dirs.items():
        pnl = xpl[xpl["direction"] == d]["total_pnl"].sum()
        print(f"  {d}: {n} trades, ${pnl:.4f}")

    # Temporal clustering — monthly
    xpl_monthly = xpl.groupby(xpl["entry_dt"].dt.strftime("%Y-%m"))["total_pnl"].agg(["count", "sum"])
    print(f"\nXPL monthly distribution:")
    for month, row in xpl_monthly.iterrows():
        bar = "█" * min(40, int(row["count"]))
        print(f"  {month}: {int(row['count']):3d} trades  ${row['sum']:8.3f}  {bar}")

    first = xpl["entry_dt"].min()
    last = xpl["entry_dt"].max()
    span = (last - first).total_seconds() / 86400
    print(f"\nXPL trade span: {first.strftime('%Y-%m-%d')} → {last.strftime('%Y-%m-%d')}  ({span:.1f} days)")
    print(f"(Full dataset spans ~180 days, so XPL was active on {span/180*100:.0f}% of the window)")

    # Sample rates during profitable vs losing XPL periods
    xpl_hl = hl[hl["asset"] == "XPL"]
    xpl_kr = kr[kr["asset"] == "XPL"]
    print(f"\nXPL funding-rate stats (8h-normalized):")
    print(f"  HL     mean={xpl_hl['hl_rate_8h'].mean()*100:.4f}%  "
          f"std={xpl_hl['hl_rate_8h'].std()*100:.4f}%  "
          f"min={xpl_hl['hl_rate_8h'].min()*100:.4f}%  "
          f"max={xpl_hl['hl_rate_8h'].max()*100:.4f}%")
    print(f"  Kraken mean={xpl_kr['kr_rate_8h'].mean()*100:.4f}%  "
          f"std={xpl_kr['kr_rate_8h'].std()*100:.4f}%  "
          f"min={xpl_kr['kr_rate_8h'].min()*100:.4f}%  "
          f"max={xpl_kr['kr_rate_8h'].max()*100:.4f}%")

    # Show top 5 XPL trades by P&L
    print(f"\nTop 5 XPL trades by P&L:")
    top = xpl.nlargest(5, "total_pnl")[["entry_dt", "exit_dt", "direction", "avg_spread", "hold_periods", "total_pnl"]]
    for _, r in top.iterrows():
        print(f"  {r['entry_dt'].strftime('%Y-%m-%d %H:%M')} → {r['exit_dt'].strftime('%m-%d %H:%M')}  "
              f"{r['direction']:<18} spread={r['avg_spread']*100:.3f}%  hold={int(r['hold_periods']):2d}  "
              f"P&L=${r['total_pnl']:.4f}")


def asset_characteristics(trades: pd.DataFrame, hl: pd.DataFrame, kr: pd.DataFrame):
    section_header("2. ASSET CHARACTERISTICS")
    agg = trades.groupby("asset").agg(
        n_trades=("total_pnl", "count"),
        total_pnl=("total_pnl", "sum"),
        avg_pnl=("total_pnl", "mean"),
        avg_spread=("avg_spread", "mean"),
        avg_hold=("hold_periods", "mean"),
        win_rate=("total_pnl", lambda s: 100.0 * (s > 0).sum() / len(s)),
    ).sort_values("total_pnl", ascending=False)

    # Direction concentration per asset
    dir_counts = trades.groupby(["asset", "direction"]).size().unstack(fill_value=0)
    for d in ("short_HL_long_KR", "long_HL_short_KR"):
        if d not in dir_counts.columns:
            dir_counts[d] = 0
    dir_counts["dir_bias_pct"] = 100 * dir_counts.max(axis=1) / dir_counts.sum(axis=1)
    agg = agg.join(dir_counts[["dir_bias_pct"]])

    print("Per-asset stats (29 assets):")
    print(agg.to_string(float_format=lambda x: f"{x:.4f}"))

    winners = agg[agg["total_pnl"] > 0.50]
    neutral = agg[(agg["total_pnl"] >= -0.50) & (agg["total_pnl"] <= 0.50)]
    losers = agg[agg["total_pnl"] < -0.50]

    def bucket_stats(name, df):
        if df.empty:
            print(f"  {name}: 0 assets")
            return
        print(f"  {name} ({len(df)} assets): "
              f"avg_spread={df['avg_spread'].mean()*100:.4f}%  "
              f"avg_hold={df['avg_hold'].mean():.2f}  "
              f"avg_win_rate={df['win_rate'].mean():.1f}%  "
              f"avg_dir_bias={df['dir_bias_pct'].mean():.1f}%  "
              f"total_pnl=${df['total_pnl'].sum():.4f}")

    print("\nBucketed:")
    bucket_stats("WINNERS (>+$0.50)", winners)
    bucket_stats("NEUTRAL (-$0.50..+$0.50)", neutral)
    bucket_stats("LOSERS (<-$0.50)", losers)

    print("\nInterpretation:")
    if not winners.empty and not losers.empty:
        w_spread = winners["avg_spread"].mean()
        l_spread = losers["avg_spread"].mean()
        w_hold = winners["avg_hold"].mean()
        l_hold = losers["avg_hold"].mean()
        w_bias = winners["dir_bias_pct"].mean()
        l_bias = losers["dir_bias_pct"].mean()
        print(f"  Winners' avg spread is {w_spread/l_spread:.2f}x losers' ({w_spread*100:.3f}% vs {l_spread*100:.3f}%)")
        print(f"  Winners' avg hold  is {w_hold/l_hold:.2f}x losers' ({w_hold:.2f} vs {l_hold:.2f})")
        print(f"  Winners' direction bias {w_bias:.1f}% vs losers' {l_bias:.1f}% (100% = fully one-sided)")


def temporal_analysis(trades: pd.DataFrame):
    section_header("3. TEMPORAL ANALYSIS")

    monthly = trades.groupby("month").agg(
        n=("total_pnl", "count"),
        pnl=("total_pnl", "sum"),
    )
    total_pnl = trades["total_pnl"].sum()
    print("Monthly P&L:")
    max_abs = max(abs(monthly["pnl"].min()), monthly["pnl"].max(), 1e-9)
    for m, row in monthly.iterrows():
        bar_len = int(40 * abs(row["pnl"]) / max_abs)
        bar = ("█" if row["pnl"] >= 0 else "░") * bar_len
        pct = 100 * row["pnl"] / total_pnl if total_pnl else 0
        print(f"  {m}: {int(row['n']):3d} trades  ${row['pnl']:8.3f}  ({pct:+5.1f}%)  {bar}")

    # Top-N trade contribution
    sorted_trades = trades.sort_values("total_pnl", ascending=False).reset_index(drop=True)
    for n in (5, 10, 20):
        top_pnl = sorted_trades.head(n)["total_pnl"].sum()
        print(f"  Best {n:2d} trades contribute: ${top_pnl:.4f}  ({100*top_pnl/total_pnl:.1f}% of net P&L)")

    # Bottom contributors
    worst = sorted_trades.tail(10)["total_pnl"].sum()
    print(f"  Worst 10 trades:                ${worst:.4f}")

    # Hour-of-day pattern
    print("\nEntry hour-of-day (UTC) — count and P&L:")
    hourly = trades.groupby("entry_hour_utc").agg(n=("total_pnl", "count"), pnl=("total_pnl", "sum"))
    for h, row in hourly.iterrows():
        bar = "█" * min(40, int(row["n"]))
        print(f"  {h:02d}:00  n={int(row['n']):3d}  P&L=${row['pnl']:7.3f}  {bar}")


def strategy_variants(trades: pd.DataFrame, hl: pd.DataFrame, kr: pd.DataFrame):
    section_header("4. STRATEGY VARIANTS")

    merged = aligned_data(hl, kr)

    # Baseline
    base = simulate(merged)
    baseline_pnl = base["total_pnl"].sum()

    variants = []
    variants.append(("Baseline (entry 0.115%, exit 0.02%, min_hold 1)", base))

    # Variant: entry 0.20% (2x threshold)
    v1 = simulate(merged, entry_threshold=0.002)
    variants.append(("Entry threshold 0.20% (2x fees)", v1))

    # Variant: exclude bottom-5 win-rate assets (baseline bottom-5)
    baseline_stats = base.groupby("asset").agg(
        total_pnl=("total_pnl", "sum"),
        win_rate=("total_pnl", lambda s: 100.0 * (s > 0).sum() / len(s)),
        n=("total_pnl", "count"),
    )
    # require at least 2 trades to rank
    rankable = baseline_stats[baseline_stats["n"] >= 2].sort_values("win_rate")
    bottom5 = rankable.head(5).index.tolist()
    keep = [a for a in merged["asset"].unique() if a not in bottom5]
    v2 = simulate(merged, asset_filter=keep)
    variants.append((f"Exclude bottom-5 win-rate assets ({','.join(bottom5)})", v2))

    # Variant: 2x min hold
    v3 = simulate(merged, min_hold_periods=2)
    variants.append(("Require min 2 funding periods held", v3))

    # Variant: combine 0.20% entry AND exclude bottom-5
    v4 = simulate(merged, entry_threshold=0.002, asset_filter=keep)
    variants.append(("0.20% entry + exclude bottom-5 WR", v4))

    # Variant: Exclude XPL
    keep_no_xpl = [a for a in merged["asset"].unique() if a != "XPL"]
    v5 = simulate(merged, asset_filter=keep_no_xpl)
    variants.append(("Exclude XPL (robustness test)", v5))

    # Present table
    print(f"{'Variant':<52} {'Trades':>7} {'WR%':>6} {'NetP&L':>10} {'vsBase':>9} {'APY%':>8}")
    days = 180.0
    for name, df in variants:
        if df.empty:
            print(f"{name:<52} {'0':>7} {'-':>6} {'-':>10} {'-':>9} {'-':>8}")
            continue
        n = len(df)
        wr = 100 * (df["total_pnl"] > 0).mean()
        p = df["total_pnl"].sum()
        apy = p / days * 365 / (CAPITAL_PER_LEG * 2) * 100
        vs = p - baseline_pnl
        print(f"{name:<52} {n:>7} {wr:>6.1f} {p:>10.4f} {vs:>+9.4f} {apy:>8.2f}")


def verdict(trades: pd.DataFrame):
    section_header("5. VERDICT")
    xpl_pnl = trades[trades["asset"] == "XPL"]["total_pnl"].sum()
    total = trades["total_pnl"].sum()
    xpl_share = 100 * xpl_pnl / total

    # Robustness: how concentrated is winnings across assets?
    per_asset = trades.groupby("asset")["total_pnl"].sum().sort_values(ascending=False)
    top3_share = 100 * per_asset.head(3).sum() / total
    positive_assets = (per_asset > 0).sum()

    print(f"XPL delivered ${xpl_pnl:.2f} of ${total:.2f} total P&L = {xpl_share:.1f}%")
    print(f"Top 3 assets delivered {top3_share:.1f}% of P&L")
    print(f"Only {positive_assets} of {len(per_asset)} assets had net positive P&L")
    print()

    print("One-time vs repeatable?")
    xpl_trades = trades[trades["asset"] == "XPL"].sort_values("entry_time")
    if not xpl_trades.empty:
        months = xpl_trades["month"].nunique()
        print(f"  XPL traded across {months} distinct months — "
              f"{'pattern recurred' if months >= 3 else 'narrow time window'}.")
        dirs = xpl_trades["direction"].value_counts(normalize=True) * 100
        dominant = dirs.idxmax()
        print(f"  XPL direction bias: {dirs[dominant]:.1f}% '{dominant}' — "
              f"{'one-sided (structural)' if dirs[dominant] > 75 else 'mixed'}.")

    print()
    print("Recommended asset-selection filter to improve robustness:")
    print("  1. Require asset to have a persistent funding-rate divergence across ≥60 days")
    print("     (one-time listing/unlock spikes — like likely what XPL captured — won't qualify)")
    print("  2. Minimum entry threshold 0.20% (2× fees) to filter noise trades")
    print("  3. Blacklist assets with baseline win rate <30% over ≥5 trades")
    print("  4. Cap per-asset exposure to ≤25% of capital to diversify concentration risk")
    print()

    print("Next-step recommendation:")
    print("  NEED MORE DATA.  Drivers:")
    print("   • 88% of P&L from a single asset makes the backtest a sample-size-1 test.")
    print("   • XPL is a recently-listed token (PF_XPLUSD history is ~200 days); the spread")
    print("     it offered likely reflects a post-listing dislocation that decays.")
    print("   • Before allocating live capital, collect ≥6 months of data AFTER XPL's")
    print("     spread normalizes; re-run the backtest on that out-of-sample window.")
    print("   • If the 'Exclude XPL' variant above still shows positive APY with 10+")
    print("     profitable assets, BUILD IT with an asset-selection filter.")
    print("   • If 'Exclude XPL' is break-even / negative, the strategy is really an")
    print("     'XPL-like-new-listings' sniper — worth building with explicit targeting,")
    print("     not as a generic cross-exchange arb.")


def main():
    trades, hl, kr = load()
    print(f"Loaded {len(trades)} trades across {trades['asset'].nunique()} assets")
    print(f"HL:     {len(hl):,} rows  |  Kraken: {len(kr):,} rows")

    xpl_deep_dive(trades, hl, kr)
    asset_characteristics(trades, hl, kr)
    temporal_analysis(trades)
    strategy_variants(trades, hl, kr)
    verdict(trades)


if __name__ == "__main__":
    main()
