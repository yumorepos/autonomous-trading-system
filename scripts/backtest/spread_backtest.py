"""
Backtest cross-exchange (HL ↔ Kraken) funding spread profitability against
90 days of historical funding-rate data.

Inputs:
  data/historical/funding_rates.csv         (HL, hourly, 8h-normalized rate)
  data/historical/kraken_funding_rates.csv  (Kraken, 4-hourly, 8h-normalized rate)

Output:
  - Printed report
  - data/spreads/historical_spread_analysis.csv (per-trade records)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HL_CSV = Path("data/historical/funding_rates.csv")
KRAKEN_CSV = Path("data/historical/kraken_funding_rates.csv")
OUT_CSV = Path("data/spreads/historical_spread_analysis.csv")

# Fee constants (mirror src/collectors/spread_scanner.py FEES).
# Round-trip (maker+taker) per leg:
HL_RT_FEE = 0.0001 + 0.00035    # 0.045%
KRAKEN_RT_FEE = 0.0002 + 0.0005  # 0.07%
ROUND_TRIP_FEE = HL_RT_FEE + KRAKEN_RT_FEE  # 0.115%

ENTRY_THRESHOLD = ROUND_TRIP_FEE            # 0.00115
EXIT_MIN_THRESHOLD = 0.0002                  # 0.02%

CAPITAL_PER_LEG = 47.50  # USD

# ms tolerance when snapping HL hourly to Kraken 4h tick:
HL_SNAP_TOLERANCE_MS = 2 * 3600 * 1000  # ±2h


def load_data():
    hl = pd.read_csv(HL_CSV).rename(columns={"funding_rate_8h": "hl_rate_8h"})
    kr = pd.read_csv(KRAKEN_CSV).rename(columns={"funding_rate_8h": "kr_rate_8h"})
    hl = hl[["timestamp", "asset", "hl_rate_8h"]].sort_values(["asset", "timestamp"])
    kr = kr[["timestamp", "asset", "kr_rate_8h"]].sort_values(["asset", "timestamp"])
    return hl, kr


def align_to_kraken(hl: pd.DataFrame, kr: pd.DataFrame) -> pd.DataFrame:
    """For each Kraken row, find the nearest HL row (same asset, within tolerance)."""
    merged_parts = []
    for asset in sorted(set(kr["asset"]).intersection(hl["asset"])):
        hl_a = hl[hl["asset"] == asset].sort_values("timestamp")
        kr_a = kr[kr["asset"] == asset].sort_values("timestamp")
        if hl_a.empty or kr_a.empty:
            continue
        m = pd.merge_asof(
            kr_a,
            hl_a[["timestamp", "hl_rate_8h"]],
            on="timestamp",
            direction="nearest",
            tolerance=HL_SNAP_TOLERANCE_MS,
        )
        m = m.dropna(subset=["hl_rate_8h"])
        merged_parts.append(m)
    if not merged_parts:
        return pd.DataFrame(columns=["timestamp", "asset", "kr_rate_8h", "hl_rate_8h", "spread"])
    merged = pd.concat(merged_parts, ignore_index=True)
    merged["spread"] = merged["hl_rate_8h"] - merged["kr_rate_8h"]
    return merged


def backtest_asset(df: pd.DataFrame, asset: str) -> list[dict]:
    """Walk the asset's 4h ticks chronologically, opening/closing trades."""
    trades: list[dict] = []
    df = df.sort_values("timestamp").reset_index(drop=True)
    in_trade = False
    direction = 0        # +1 short HL / long Kraken; -1 long HL / short Kraken
    entry_ts = None
    cum_pnl_pct = 0.0    # accumulated funding receipts (in decimal, 8h-scaled half per tick)
    spread_samples: list[float] = []
    hold_periods = 0

    for _, row in df.iterrows():
        spread = row["spread"]
        ts = int(row["timestamp"])

        if not in_trade:
            if abs(spread) > ENTRY_THRESHOLD:
                in_trade = True
                direction = 1 if spread > 0 else -1
                entry_ts = ts
                cum_pnl_pct = 0.0
                spread_samples = []
                hold_periods = 0
            continue

        # in trade → check exit conditions
        same_sign = (spread > 0 and direction > 0) or (spread < 0 and direction < 0)
        below_min = abs(spread) < EXIT_MIN_THRESHOLD
        if (not same_sign) or below_min:
            # close — record trade (based on periods already accrued)
            exit_ts = ts
            avg_spread = float(np.mean(spread_samples)) if spread_samples else 0.0
            gross_pnl_dollar = cum_pnl_pct * CAPITAL_PER_LEG
            fee_dollar = ROUND_TRIP_FEE * CAPITAL_PER_LEG
            net_pnl_dollar = gross_pnl_dollar - fee_dollar
            trades.append({
                "asset": asset,
                "entry_time": entry_ts,
                "exit_time": exit_ts,
                "direction": "short_HL_long_KR" if direction > 0 else "long_HL_short_KR",
                "avg_spread": avg_spread,
                "hold_periods": hold_periods,
                "gross_pnl": gross_pnl_dollar,
                "fees": fee_dollar,
                "total_pnl": net_pnl_dollar,
            })
            in_trade = False
            direction = 0
            continue

        # accrue: per 4h tick we earn spread*direction*0.5 (8h rate → 4h portion)
        cum_pnl_pct += spread * direction * 0.5
        spread_samples.append(abs(spread))
        hold_periods += 1

    # close any open trade at end
    if in_trade and hold_periods > 0:
        avg_spread = float(np.mean(spread_samples)) if spread_samples else 0.0
        gross_pnl_dollar = cum_pnl_pct * CAPITAL_PER_LEG
        fee_dollar = ROUND_TRIP_FEE * CAPITAL_PER_LEG
        trades.append({
            "asset": asset,
            "entry_time": entry_ts,
            "exit_time": int(df.iloc[-1]["timestamp"]),
            "direction": "short_HL_long_KR" if direction > 0 else "long_HL_short_KR",
            "avg_spread": avg_spread,
            "hold_periods": hold_periods,
            "gross_pnl": gross_pnl_dollar,
            "fees": fee_dollar,
            "total_pnl": gross_pnl_dollar - fee_dollar,
        })
    return trades


def format_ts(ts_ms: int) -> str:
    return pd.to_datetime(ts_ms, unit="ms", utc=True).strftime("%Y-%m-%d %H:%M")


def main() -> int:
    print("Loading historical funding rates...")
    hl, kr = load_data()
    print(f"  HL:     {len(hl):,} rows, {hl['asset'].nunique()} assets")
    print(f"  Kraken: {len(kr):,} rows, {kr['asset'].nunique()} assets")

    print("\nAligning Kraken 4h ticks to nearest HL rate (±2h)...")
    merged = align_to_kraken(hl, kr)
    total_rows = len(merged)
    assets = sorted(merged["asset"].unique().tolist())
    print(f"  {total_rows:,} aligned observations across {len(assets)} assets")

    # Entry opportunity count (independent — number of ticks with |spread| > fee)
    entry_opps = int((merged["spread"].abs() > ENTRY_THRESHOLD).sum())

    # Window duration
    ts_min = int(merged["timestamp"].min())
    ts_max = int(merged["timestamp"].max())
    days = (ts_max - ts_min) / (1000 * 3600 * 24)

    print("\nRunning strategy simulation per asset...")
    all_trades: list[dict] = []
    for asset in assets:
        asset_df = merged[merged["asset"] == asset]
        all_trades.extend(backtest_asset(asset_df, asset))

    trades_df = pd.DataFrame(all_trades)

    # Save per-trade records
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    if not trades_df.empty:
        trades_df_out = trades_df[[
            "asset", "entry_time", "exit_time", "direction",
            "avg_spread", "hold_periods", "gross_pnl", "fees", "total_pnl",
        ]].copy()
        trades_df_out.to_csv(OUT_CSV, index=False)

    # Report
    print()
    print("=" * 72)
    print("HL ↔ KRAKEN CROSS-EXCHANGE FUNDING SPREAD BACKTEST")
    print("=" * 72)
    print(f"Window:                {format_ts(ts_min)} → {format_ts(ts_max)}  ({days:.1f} days)")
    print(f"Capital per leg:       ${CAPITAL_PER_LEG:.2f}  (total notional ${CAPITAL_PER_LEG*2:.2f})")
    print(f"Entry threshold:       |spread_8h| > {ENTRY_THRESHOLD*100:.3f}%  (round-trip fees)")
    print(f"Exit threshold:        sign flip OR |spread_8h| < {EXIT_MIN_THRESHOLD*100:.3f}%")
    print(f"Round-trip fee / trade: {ROUND_TRIP_FEE*100:.3f}%  (= ${ROUND_TRIP_FEE*CAPITAL_PER_LEG:.4f} per trade)")
    print()
    print(f"Total overlapping asset-periods:   {total_rows:,}")
    print(f"Entry opportunities (|spread| > fee threshold, per-tick): {entry_opps:,}")
    print(f"Total trades simulated:            {len(trades_df)}")

    if trades_df.empty:
        print("\nNo trades generated — spread never exceeded entry threshold.")
        return 0

    wins = trades_df[trades_df["total_pnl"] > 0]
    avg_hold = trades_df["hold_periods"].mean()
    win_rate = 100.0 * len(wins) / len(trades_df)
    avg_pnl = trades_df["total_pnl"].mean()
    total_pnl = trades_df["total_pnl"].sum()
    total_gross = trades_df["gross_pnl"].sum()
    total_fees = trades_df["fees"].sum()

    monthly_pnl = total_pnl / days * 30
    annual_pnl = total_pnl / days * 365
    apy = annual_pnl / (CAPITAL_PER_LEG * 2) * 100  # on total notional

    print(f"Average hold duration:             {avg_hold:.2f} funding periods (4h each ≈ {avg_hold*4/24:.2f} days)")
    print(f"Win rate:                          {win_rate:.1f}%")
    print(f"Average P&L per trade:             ${avg_pnl:.4f}")
    print(f"Gross P&L (pre-fees):              ${total_gross:.4f}")
    print(f"Total fees:                        ${total_fees:.4f}")
    print(f"Net P&L over {days:.0f} days:              ${total_pnl:.4f}")
    print(f"Projected monthly return:          ${monthly_pnl:.4f}")
    print(f"Annualized (on ${CAPITAL_PER_LEG*2:.0f} notional):     ${annual_pnl:.2f}  ({apy:.2f}% APY)")

    # Per-asset P&L ranking
    per_asset = trades_df.groupby("asset").agg(
        n_trades=("total_pnl", "count"),
        total_pnl=("total_pnl", "sum"),
        avg_pnl=("total_pnl", "mean"),
        win_rate=("total_pnl", lambda s: 100.0 * (s > 0).sum() / len(s)),
        avg_hold=("hold_periods", "mean"),
    ).sort_values("total_pnl", ascending=False)

    print("\n--- Best 5 asset pairs by total P&L ---")
    print(per_asset.head(5).to_string(float_format=lambda x: f"{x:.4f}"))
    print("\n--- Worst 5 asset pairs by total P&L ---")
    print(per_asset.tail(5).to_string(float_format=lambda x: f"{x:.4f}"))

    # Binance comparison
    binance_csv = Path("data/historical/binance_funding_rates.csv")
    if binance_csv.exists():
        try:
            bn = pd.read_csv(binance_csv).rename(columns={"funding_rate_8h": "bn_rate_8h"})
            bn = bn[["timestamp", "asset", "bn_rate_8h"]].sort_values(["asset", "timestamp"])
            bn_parts = []
            for asset in sorted(set(bn["asset"]).intersection(hl["asset"])):
                hl_a = hl[hl["asset"] == asset].sort_values("timestamp")
                bn_a = bn[bn["asset"] == asset].sort_values("timestamp")
                if hl_a.empty or bn_a.empty:
                    continue
                m = pd.merge_asof(
                    bn_a, hl_a[["timestamp", "hl_rate_8h"]],
                    on="timestamp", direction="nearest", tolerance=HL_SNAP_TOLERANCE_MS,
                )
                m = m.dropna(subset=["hl_rate_8h"])
                bn_parts.append(m)
            if bn_parts:
                bn_merged = pd.concat(bn_parts, ignore_index=True)
                bn_merged["spread"] = bn_merged["hl_rate_8h"] - bn_merged["bn_rate_8h"]
                bn_opps = int((bn_merged["spread"].abs() > ENTRY_THRESHOLD).sum())
                print(f"\n--- Binance (data-only) comparison ---")
                print(f"Kraken entry opportunities:  {entry_opps:,}")
                print(f"Binance entry opportunities: {bn_opps:,}  (not tradeable from Canada)")
        except Exception as e:
            print(f"\nBinance comparison skipped ({e})")
    else:
        print("\n--- Binance comparison ---")
        print("(skipped: no data/historical/binance_funding_rates.csv)")

    print(f"\nPer-trade records → {OUT_CSV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
