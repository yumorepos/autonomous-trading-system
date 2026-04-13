"""
DurationPredictor — Estimates probability that a regime persists for at least min_duration.

Uses log-normal survival curve fitted to historical regime duration distributions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from scipy import stats

from src.collectors.regime_history import RegimeHistoryCollector

logger = logging.getLogger(__name__)

_MIN_SAMPLES_SPECIFIC = 20  # Minimum samples before falling back to pooled
_MIN_SAMPLES_FIT = 5        # Absolute minimum to attempt a fit


@dataclass
class DurationEstimate:
    survival_probability: float   # P(duration >= threshold)
    expected_duration_min: float  # Median of fitted distribution (minutes)
    sample_count: int
    used_fallback: bool


class DurationPredictor:
    """Predicts regime duration using log-normal survival curves."""

    def __init__(self, history_collector: RegimeHistoryCollector):
        self.history = history_collector
        self._cache: dict[tuple[str | None, str], stats.lognorm | None] = {}

    def predict(
        self,
        asset: str,
        regime: str,
        min_duration_minutes: float = 15.0,
    ) -> DurationEstimate:
        """Estimate P(duration >= min_duration_minutes) for the given asset/regime pair.

        Falls back to pooled distribution across all assets if insufficient
        samples for the specific (asset, regime) pair.
        """
        # Try specific (asset, regime) first
        durations = self.history.get_regime_durations(asset=asset, regime=regime)
        used_fallback = False

        if len(durations) < _MIN_SAMPLES_SPECIFIC:
            logger.warning(
                "Only %d samples for (%s, %s) — using pooled distribution for regime %s",
                len(durations), asset, regime, regime,
            )
            durations = self.history.get_regime_durations(regime=regime)
            used_fallback = True

        if len(durations) < _MIN_SAMPLES_FIT:
            logger.warning(
                "Insufficient data for regime %s (%d samples) — returning conservative estimate",
                regime, len(durations),
            )
            return DurationEstimate(
                survival_probability=0.0,
                expected_duration_min=0.0,
                sample_count=len(durations),
                used_fallback=used_fallback,
            )

        # Convert to minutes
        durations_min = np.array(durations) / 60.0
        # Filter out zero/negative durations for log-normal fit
        durations_min = durations_min[durations_min > 0]

        if len(durations_min) < _MIN_SAMPLES_FIT:
            return DurationEstimate(
                survival_probability=0.0,
                expected_duration_min=0.0,
                sample_count=len(durations_min),
                used_fallback=used_fallback,
            )

        # Fit log-normal distribution
        try:
            shape, loc, scale = stats.lognorm.fit(durations_min, floc=0)
            dist = stats.lognorm(shape, loc=loc, scale=scale)
        except Exception as e:
            logger.warning("Log-normal fit failed for (%s, %s): %s", asset, regime, e)
            # Fallback: empirical survival
            survival_prob = float(np.mean(durations_min >= min_duration_minutes))
            return DurationEstimate(
                survival_probability=survival_prob,
                expected_duration_min=float(np.median(durations_min)),
                sample_count=len(durations_min),
                used_fallback=used_fallback,
            )

        # P(duration >= threshold) = 1 - CDF(threshold)
        survival_prob = 1.0 - dist.cdf(min_duration_minutes)
        median_duration = float(dist.median())

        return DurationEstimate(
            survival_probability=float(np.clip(survival_prob, 0.0, 1.0)),
            expected_duration_min=median_duration,
            sample_count=len(durations_min),
            used_fallback=used_fallback,
        )

    def calibration_table(self, min_duration_minutes: float = 15.0) -> list[dict]:
        """Run calibration check across all (asset, regime) pairs.

        Returns a list of dicts with predicted vs empirical survival rates.
        """
        import sqlite3
        conn = sqlite3.connect(str(self.history.db_path))

        pairs = conn.execute(
            "SELECT DISTINCT asset, regime FROM regime_transitions"
        ).fetchall()
        conn.close()

        results = []
        for asset, regime in pairs:
            durations = self.history.get_regime_durations(asset=asset, regime=regime)
            if not durations:
                continue

            durations_min = np.array(durations) / 60.0
            durations_min = durations_min[durations_min > 0]

            if len(durations_min) < _MIN_SAMPLES_FIT:
                continue

            # Empirical survival rate
            empirical = float(np.mean(durations_min >= min_duration_minutes))

            # Predicted survival rate
            estimate = self.predict(asset, regime, min_duration_minutes)

            error = abs(estimate.survival_probability - empirical)
            results.append({
                "asset": asset,
                "regime": regime,
                "n_samples": len(durations_min),
                "empirical_survival": round(empirical, 4),
                "predicted_survival": round(estimate.survival_probability, 4),
                "error_pp": round(error * 100, 2),
                "median_duration_min": round(estimate.expected_duration_min, 1),
                "calibrated": error <= 0.10,
            })

        return results
