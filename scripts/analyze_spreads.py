#!/usr/bin/env python3
"""
Analyze historical funding spread scans from data/spreads/funding_spreads.jsonl.

Reports:
  - Per (asset, exchange) pair: avg/max abs spread, % of scans above fee threshold
  - Kraken vs Binance vs Bybit opportunity quality
  - Executable vs data-only opportunity counts
  - Estimated daily return if every executable opportunity is captured
  - Average opportunity duration (consecutive scans where an asset is present)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = _REPO_ROOT / "data" / "spreads" / "funding_spreads.jsonl"


def _load(path: Path) -> list[dict]:
    if not path.exists():
        print(f"No scan history at {path}", file=sys.stderr)
        return []
    scans = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                scans.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    scans.sort(key=lambda s: s.get("timestamp_utc", ""))
    return scans


def analyze(scans: list[dict]) -> None:
    if not scans:
        print("Nothing to analyze.")
        return

    # Per-pair accumulators keyed by (asset, exchange)
    per_pair_abs_spread: dict[tuple[str, str], list[float]] = defaultdict(list)
    per_pair_net_apy: dict[tuple[str, str], list[float]] = defaultdict(list)
    per_pair_above_fee: dict[tuple[str, str], int] = defaultdict(int)
    per_pair_scan_count: dict[tuple[str, str], int] = defaultdict(int)
    per_pair_presence: dict[tuple[str, str], list[bool]] = defaultdict(list)

    per_exchange_count: dict[str, int] = defaultdict(int)
    executable_count = 0
    data_only_count = 0
    # For estimated daily return: sum of best executable net_spread_8h across scans
    executable_best_net_spread_8h: list[float] = []

    for scan in scans:
        spreads = scan.get("spreads", [])
        seen_pairs = set()
        # Best executable opportunity this scan (pick the largest net_apy, one asset)
        best_exec_spread_8h = 0.0
        for s in spreads:
            key = (s["asset"], s["other_exchange"])
            seen_pairs.add(key)
            per_pair_abs_spread[key].append(s["abs_spread_8h"])
            per_pair_net_apy[key].append(s["net_apy_optimistic"])
            per_pair_scan_count[key] += 1
            # "above fee threshold" = optimistic net_apy > 0, which is already our inclusion rule
            if s["net_apy_optimistic"] > 0:
                per_pair_above_fee[key] += 1
            per_exchange_count[s["other_exchange"]] += 1
            if s["executable"]:
                executable_count += 1
                if s["net_spread_8h_optimistic"] > best_exec_spread_8h:
                    best_exec_spread_8h = s["net_spread_8h_optimistic"]
            else:
                data_only_count += 1

        executable_best_net_spread_8h.append(best_exec_spread_8h)

        # Presence tracking — for duration estimation we need a per-scan present flag
        # Use union of pairs we've EVER seen so far.
        for key in list(per_pair_presence.keys()) + list(seen_pairs):
            if key not in per_pair_presence:
                per_pair_presence[key] = []
        for key in per_pair_presence:
            per_pair_presence[key].append(key in seen_pairs)

    total_scans = len(scans)
    print(f"\n=== Spread Scan History Analysis ===")
    print(f"Scans loaded: {total_scans}")
    try:
        start = scans[0]["timestamp_utc"]
        end = scans[-1]["timestamp_utc"]
        print(f"Range: {start} → {end}")
    except (KeyError, IndexError):
        pass

    print(f"\nTotal opportunity-records: {executable_count + data_only_count}")
    print(f"  Executable (Kraken):   {executable_count}")
    print(f"  Data-only (BIN/Bybit): {data_only_count}")

    print("\n  Per-exchange occurrence count:")
    for ex, cnt in sorted(per_exchange_count.items(), key=lambda x: -x[1]):
        print(f"    {ex:<10} {cnt}")

    # Per-pair table (top 20 by avg net APY)
    rows = []
    for (asset, ex), apys in per_pair_net_apy.items():
        abs_list = per_pair_abs_spread[(asset, ex)]
        above = per_pair_above_fee[(asset, ex)]
        cnt = per_pair_scan_count[(asset, ex)]
        rows.append({
            "asset": asset,
            "exchange": ex,
            "count": cnt,
            "avg_abs_spread": mean(abs_list) if abs_list else 0.0,
            "max_abs_spread": max(abs_list) if abs_list else 0.0,
            "avg_net_apy": mean(apys) if apys else 0.0,
            "max_net_apy": max(apys) if apys else 0.0,
            "pct_above_fee": (above / cnt * 100) if cnt else 0.0,
        })
    rows.sort(key=lambda r: r["avg_net_apy"], reverse=True)

    print("\n  Top 20 pairs by avg net APY:")
    print(f"  {'Asset':<8} {'Ex':<8} {'#':>4} {'AvgSpread':>10} "
          f"{'MaxSpread':>10} {'AvgAPY':>8} {'MaxAPY':>8} {'%AboveFee':>10}")
    print("  " + "-" * 78)
    for r in rows[:20]:
        print(f"  {r['asset']:<8} {r['exchange']:<8} {r['count']:>4} "
              f"{r['avg_abs_spread']*100:>9.4f}% {r['max_abs_spread']*100:>9.4f}% "
              f"{r['avg_net_apy']:>7.1f}% {r['max_net_apy']:>7.1f}% "
              f"{r['pct_above_fee']:>9.1f}%")

    # Kraken vs Binance vs Bybit quality
    print("\n  Exchange quality comparison (among opportunity-records):")
    for ex in ("Kraken", "Binance", "Bybit"):
        pair_apys = [apy for (_a, e), apys in per_pair_net_apy.items() if e == ex for apy in apys]
        if not pair_apys:
            print(f"    {ex:<10}: no records")
            continue
        print(f"    {ex:<10}: n={len(pair_apys):>4}, avg net APY={mean(pair_apys):.1f}%, "
              f"max={max(pair_apys):.1f}%")

    # Estimated daily return if we captured the best executable opp each scan
    if executable_best_net_spread_8h:
        # Each scan is a snapshot; conservatively assume we realize one 8h cycle
        # per "capture". Daily = 3 cycles/day. We approximate by taking the mean
        # per-scan best and multiplying by 3.
        avg_best_8h = mean(executable_best_net_spread_8h)
        est_daily_pct = avg_best_8h * 3 * 100
        print(f"\n  Estimated daily return (best executable opp per scan, avg): "
              f"{est_daily_pct:.3f}%  "
              f"(≈ {est_daily_pct * 365:.1f}% APY naive)")

    # Opportunity duration — consecutive True runs per pair
    print("\n  Avg opportunity duration (consecutive scans present):")
    duration_rows = []
    for key, presence in per_pair_presence.items():
        runs = []
        cur = 0
        for p in presence:
            if p:
                cur += 1
            else:
                if cur > 0:
                    runs.append(cur)
                cur = 0
        if cur > 0:
            runs.append(cur)
        if runs:
            duration_rows.append((key, mean(runs), max(runs), len(runs)))
    duration_rows.sort(key=lambda x: -x[1])
    for (asset, ex), avg_d, max_d, n_runs in duration_rows[:15]:
        print(f"    {asset:<8} {ex:<10}: avg_run={avg_d:.1f} scans, "
              f"max_run={max_d}, n_runs={n_runs}")

    print()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default=str(DEFAULT_PATH),
                    help=f"jsonl file (default: {DEFAULT_PATH})")
    args = ap.parse_args()
    scans = _load(Path(args.path))
    analyze(scans)
    return 0


if __name__ == "__main__":
    sys.exit(main())
