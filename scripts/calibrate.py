#!/usr/bin/env python3
"""
Calibration script: validates duration predictor accuracy against empirical data.

Usage:
    python3 scripts/calibrate.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.config import load_config
from src.factory import build_adapters
from src.collectors.regime_history import RegimeHistoryCollector
from src.scoring.duration_predictor import DurationPredictor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    cfg = load_config()
    adapters = build_adapters(cfg)
    collector = RegimeHistoryCollector(adapters)
    predictor = DurationPredictor(collector)

    min_duration = cfg["duration_filter"]["min_duration_minutes"]
    logger.info("Running calibration for min_duration=%d minutes...", min_duration)

    table = predictor.calibration_table(min_duration_minutes=min_duration)

    if not table:
        logger.warning("No (asset, regime) pairs with sufficient data for calibration.")
        return

    print()
    print("=" * 90)
    print(f"  DURATION PREDICTOR CALIBRATION (threshold = {min_duration}m)")
    print("=" * 90)
    print(f"  {'Asset':<10} {'Regime':<15} {'N':>5} {'Empirical':>10} {'Predicted':>10} {'Error(pp)':>10} {'Pass':>6}")
    print("-" * 90)

    all_pass = True
    for row in sorted(table, key=lambda r: (r["asset"], r["regime"])):
        passed = "✓" if row["calibrated"] else "✗"
        if not row["calibrated"] and row["n_samples"] >= 50:
            all_pass = False

        print(
            f"  {row['asset']:<10} {row['regime']:<15} {row['n_samples']:>5} "
            f"{row['empirical_survival']:>10.2%} {row['predicted_survival']:>10.2%} "
            f"{row['error_pp']:>9.1f}pp {passed:>6}"
        )

    print("-" * 90)

    calibrated_count = sum(1 for r in table if r["calibrated"])
    significant = [r for r in table if r["n_samples"] >= 50]
    sig_calibrated = sum(1 for r in significant if r["calibrated"])

    print(f"  All pairs: {calibrated_count}/{len(table)} calibrated (error < 10pp)")
    if significant:
        print(f"  Significant (n≥50): {sig_calibrated}/{len(significant)} calibrated")
    print()

    if all_pass:
        print("  ✓ CALIBRATION PASSED — all significant pairs within 10pp tolerance")
    else:
        print("  ✗ CALIBRATION FAILED — some significant pairs exceed 10pp tolerance")

    print()


if __name__ == "__main__":
    main()
