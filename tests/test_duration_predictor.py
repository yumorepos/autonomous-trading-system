"""Tests for DurationPredictor."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from src.config import load_config
from src.collectors.regime_history import RegimeHistoryCollector
from src.scoring.duration_predictor import DurationPredictor


@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary DB with synthetic regime transitions."""
    db_path = tmp_path / "test_regime_history.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS funding_rates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset TEXT, exchange TEXT, timestamp_utc TEXT,
            funding_rate REAL, funding_rate_annualized REAL,
            funding_interval_hours REAL,
            UNIQUE(asset, exchange, timestamp_utc)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS regime_transitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset TEXT, exchange TEXT, regime TEXT,
            start_time_utc TEXT, end_time_utc TEXT,
            duration_seconds REAL, max_apy REAL, avg_apy REAL,
            UNIQUE(asset, exchange, start_time_utc)
        )
    """)

    # Insert synthetic regime transitions with log-normal-ish durations
    rng = np.random.default_rng(42)
    # HIGH_FUNDING durations: many short, some long (log-normal with median ~10 min)
    high_durations = rng.lognormal(mean=np.log(600), sigma=0.8, size=100)
    for i, dur in enumerate(high_durations):
        conn.execute(
            """INSERT INTO regime_transitions
               (asset, exchange, regime, start_time_utc, end_time_utc, duration_seconds, max_apy, avg_apy)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("BTC", "binance", "HIGH_FUNDING",
             f"2026-03-{(i % 28) + 1:02d}T{i % 24:02d}:00:00+00:00",
             f"2026-03-{(i % 28) + 1:02d}T{i % 24:02d}:30:00+00:00",
             float(dur), 150.0, 120.0),
        )

    # LOW_FUNDING durations: mostly short
    low_durations = rng.lognormal(mean=np.log(120), sigma=0.5, size=60)
    for i, dur in enumerate(low_durations):
        conn.execute(
            """INSERT INTO regime_transitions
               (asset, exchange, regime, start_time_utc, end_time_utc, duration_seconds, max_apy, avg_apy)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("BTC", "binance", "LOW_FUNDING",
             f"2026-02-{(i % 28) + 1:02d}T{i % 24:02d}:00:00+00:00",
             f"2026-02-{(i % 28) + 1:02d}T{i % 24:02d}:10:00+00:00",
             float(dur), 15.0, 10.0),
        )

    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def collector(tmp_db):
    """Create a RegimeHistoryCollector with the test DB."""
    with patch("src.collectors.regime_history.get_config") as mock_cfg:
        mock_cfg.return_value = {
            "history": {"backfill_days": 30, "db_path": str(tmp_db), "signal_log_path": "data/signal_log.db"},
            "regime_thresholds": {"low_funding_max_apy": 20, "moderate_max_apy": 80},
            "assets": ["BTC"],
            "exchanges": {},
        }
        c = RegimeHistoryCollector([], db_path=tmp_db)
    return c


@pytest.fixture
def predictor(collector):
    return DurationPredictor(collector)


class TestDurationPredictor:

    def test_predict_returns_valid_probability(self, predictor):
        est = predictor.predict("BTC", "HIGH_FUNDING", min_duration_minutes=15.0)
        assert 0.0 <= est.survival_probability <= 1.0
        assert est.expected_duration_min > 0
        assert est.sample_count == 100

    def test_predict_high_vs_low_regime(self, predictor):
        high_est = predictor.predict("BTC", "HIGH_FUNDING", min_duration_minutes=15.0)
        low_est = predictor.predict("BTC", "LOW_FUNDING", min_duration_minutes=15.0)

        # HIGH_FUNDING has longer durations (median ~600s=10m) vs LOW (median ~120s=2m)
        # So HIGH should have higher survival prob at 15m
        assert high_est.survival_probability > low_est.survival_probability

    def test_fallback_to_pooled(self, predictor):
        # Asset with no specific data should fall back to pooled
        est = predictor.predict("UNKNOWN_ASSET", "HIGH_FUNDING", min_duration_minutes=15.0)
        assert est.used_fallback
        assert est.survival_probability > 0.0

    def test_insufficient_data_returns_zero(self, predictor):
        est = predictor.predict("UNKNOWN", "NONEXISTENT_REGIME", min_duration_minutes=15.0)
        assert est.survival_probability == 0.0
        assert est.sample_count < 5

    def test_short_threshold_gives_higher_prob(self, predictor):
        est_short = predictor.predict("BTC", "HIGH_FUNDING", min_duration_minutes=1.0)
        est_long = predictor.predict("BTC", "HIGH_FUNDING", min_duration_minutes=60.0)

        assert est_short.survival_probability >= est_long.survival_probability

    def test_calibration_table(self, predictor):
        table = predictor.calibration_table(min_duration_minutes=15.0)
        assert len(table) > 0

        for row in table:
            assert "asset" in row
            assert "regime" in row
            assert "empirical_survival" in row
            assert "predicted_survival" in row
            assert "error_pp" in row
            assert "calibrated" in row

    def test_calibration_accuracy_for_large_samples(self, predictor):
        """Pairs with ≥50 samples should have calibration error < 10pp."""
        table = predictor.calibration_table(min_duration_minutes=15.0)
        significant = [r for r in table if r["n_samples"] >= 50]

        for row in significant:
            assert row["error_pp"] <= 10.0, (
                f"{row['asset']}/{row['regime']}: error={row['error_pp']}pp > 10pp"
            )
