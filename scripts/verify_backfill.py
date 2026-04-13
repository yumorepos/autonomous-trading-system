#!/usr/bin/env python3
"""
Post-backfill data integrity verification.

Checks:
    1. Total regime transitions >= 500
    2. No duplicate (asset, exchange, start_time) tuples
    3. All regime values are valid
    4. All durations are positive and < 30 days
    5. All APY values are non-negative and < 10000%
    6. Per-asset-exchange coverage: flag if < 10 transitions
    7. Print summary table

EXIT CODE:
    0 if all checks pass
    1 if any critical check fails
    2 if only warnings (low sample count)
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.config import load_config

VALID_REGIMES = {"LOW_FUNDING", "MODERATE", "HIGH_FUNDING"}
MAX_DURATION_SECONDS = 30 * 24 * 3600  # 30 days
MAX_APY = 10000  # 10,000%


def main():
    cfg = load_config()
    db_path = Path(cfg["history"]["db_path"])

    if not db_path.exists():
        print("ERROR: Database not found at", db_path)
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))
    critical_failures = []
    warnings = []

    # --- Check 1: Total transitions ---
    total = conn.execute("SELECT COUNT(*) FROM regime_transitions").fetchone()[0]
    print(f"\n  Total regime transitions: {total}")
    if total < 500:
        warnings.append(f"Only {total} transitions (target: ≥500)")
    else:
        print(f"  ✓ Check 1: {total} transitions ≥ 500")

    # --- Check 2: Duplicates ---
    dup_count = conn.execute("""
        SELECT COUNT(*) FROM (
            SELECT asset, exchange, start_time_utc, COUNT(*) as cnt
            FROM regime_transitions
            GROUP BY asset, exchange, start_time_utc
            HAVING cnt > 1
        )
    """).fetchone()[0]
    if dup_count > 0:
        critical_failures.append(f"{dup_count} duplicate (asset, exchange, start_time) tuples")
    else:
        print("  ✓ Check 2: No duplicates")

    # --- Check 3: Valid regime values ---
    invalid_regimes = conn.execute("""
        SELECT DISTINCT regime FROM regime_transitions
        WHERE regime NOT IN ('LOW_FUNDING', 'MODERATE', 'HIGH_FUNDING')
    """).fetchall()
    if invalid_regimes:
        critical_failures.append(f"Invalid regime values: {[r[0] for r in invalid_regimes]}")
    else:
        print("  ✓ Check 3: All regime values valid")

    # --- Check 4: Duration sanity ---
    bad_durations = conn.execute("""
        SELECT COUNT(*) FROM regime_transitions
        WHERE duration_seconds IS NOT NULL
          AND (duration_seconds <= 0 OR duration_seconds > ?)
    """, (MAX_DURATION_SECONDS,)).fetchone()[0]
    if bad_durations > 0:
        critical_failures.append(f"{bad_durations} transitions with invalid duration (<=0 or >30d)")
    else:
        print("  ✓ Check 4: All durations in valid range")

    # --- Check 5: APY sanity ---
    bad_apy = conn.execute("""
        SELECT COUNT(*) FROM regime_transitions
        WHERE max_apy < 0 OR max_apy > ?
    """, (MAX_APY,)).fetchone()[0]
    if bad_apy > 0:
        critical_failures.append(f"{bad_apy} transitions with invalid APY (<0 or >{MAX_APY}%)")
    else:
        print("  ✓ Check 5: All APY values in valid range")

    # --- Check 6 + 7: Per-asset-exchange coverage ---
    print()
    print("=" * 100)
    print("  REGIME TRANSITION SUMMARY")
    print("=" * 100)
    print(f"  {'Asset':<10} {'Exchange':<14} {'Transitions':>12} {'Avg Duration':>14} {'Median':>10} {'P(≥15m)':>10}")
    print("-" * 100)

    pairs = conn.execute("""
        SELECT asset, exchange, COUNT(*) as cnt
        FROM regime_transitions
        GROUP BY asset, exchange
        ORDER BY asset, exchange
    """).fetchall()

    for asset, exchange, cnt in pairs:
        durations = [
            r[0] for r in conn.execute(
                "SELECT duration_seconds FROM regime_transitions WHERE asset=? AND exchange=? AND duration_seconds IS NOT NULL",
                (asset, exchange),
            ).fetchall()
        ]

        if durations:
            arr = np.array(durations)
            avg_str = _format_duration(arr.mean())
            med_str = _format_duration(np.median(arr))
            p15m = float(np.mean(arr >= 900))  # 15 min = 900s
            p15m_str = f"{p15m:.2%}"
        else:
            avg_str = "N/A"
            med_str = "N/A"
            p15m_str = "N/A"

        flag = " ⚠️" if cnt < 10 else ""
        print(f"  {asset:<10} {exchange:<14} {cnt:>12} {avg_str:>14} {med_str:>10} {p15m_str:>10}{flag}")

        if cnt < 10:
            warnings.append(f"{asset}/{exchange}: only {cnt} transitions")

    print("-" * 100)

    # Date range
    date_range = conn.execute("""
        SELECT MIN(start_time_utc), MAX(end_time_utc)
        FROM regime_transitions
    """).fetchone()
    if date_range[0] and date_range[1]:
        print(f"\n  Date range: {date_range[0][:19]} to {date_range[1][:19]}")

    # Funding rates count
    fr_count = conn.execute("SELECT COUNT(*) FROM funding_rates").fetchone()[0]
    print(f"  Total funding rate records: {fr_count:,}")
    print(f"  Total regime transitions: {total:,}")

    conn.close()

    # --- Results ---
    print()
    if critical_failures:
        print("  ✗ CRITICAL FAILURES:")
        for f in critical_failures:
            print(f"    - {f}")
        sys.exit(1)
    elif warnings:
        print("  ⚠️  WARNINGS (non-critical):")
        for w in warnings:
            print(f"    - {w}")
        sys.exit(2)
    else:
        print("  ✓ ALL CHECKS PASSED")
        sys.exit(0)


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.1f}m"
    hours = minutes / 60
    return f"{hours:.1f}h"


if __name__ == "__main__":
    main()
