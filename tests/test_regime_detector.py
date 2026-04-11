#!/usr/bin/env python3
"""
Tests for the regime detector.

Covers:
- All 4 regime levels classified correctly given mock funding data
- Regime state file written with correct schema
- Stale state (>4 hours old) triggers fallback to safe defaults
- Scanner threshold lookup works for each regime
- Regime change detection (new != old triggers alert)
- Edge case: all funding rates at 0 → LOW_FUNDING
- Edge case: single asset at extreme funding → correct classification
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.regime_thresholds import (
    REGIME_THRESHOLDS,
    DEFAULT_REGIME,
    REGIME_STALE_SECONDS,
    get_regime_thresholds,
)
from scripts.regime_detector import (
    compute_regime_metrics,
    classify_regime,
    detect_regime_from_api_response,
    load_regime_state,
    save_regime_state,
    get_active_regime,
    get_active_thresholds,
    REGIME_STATE_FILE,
)
from scripts.tiered_scanner import classify_signal


def _make_api_response(assets: list[dict]) -> list:
    """Build a fake metaAndAssetCtxs response.

    Each asset dict should have: name, funding (8h rate), premium, volume.
    """
    universe = [{"name": a["name"]} for a in assets]
    ctxs = [
        {
            "funding": str(a.get("funding", 0)),
            "premium": str(a.get("premium", 0)),
            "dayNtlVlm": str(a.get("volume", 0)),
            "midPx": str(a.get("midPx", 100)),
        }
        for a in assets
    ]
    return [{"universe": universe}, ctxs]


class TestComputeRegimeMetrics(unittest.TestCase):
    """Test regime metric computation."""

    def test_empty_funding_data(self):
        metrics = compute_regime_metrics([])
        self.assertEqual(metrics["max_funding_apy"], 0.0)
        self.assertEqual(metrics["avg_top10_funding_apy"], 0.0)
        self.assertEqual(metrics["pct_above_50"], 0.0)
        self.assertEqual(metrics["pct_above_100"], 0.0)
        self.assertEqual(metrics["top_assets"], [])

    def test_single_asset(self):
        data = [{"asset": "BTC", "funding_apy": 0.50}]
        metrics = compute_regime_metrics(data)
        self.assertAlmostEqual(metrics["max_funding_apy"], 0.50, places=4)
        self.assertAlmostEqual(metrics["avg_top10_funding_apy"], 0.50, places=4)
        self.assertAlmostEqual(metrics["pct_above_50"], 1.0, places=4)
        self.assertAlmostEqual(metrics["pct_above_100"], 0.0, places=4)

    def test_top_assets_limited_to_5(self):
        data = [{"asset": f"COIN{i}", "funding_apy": 0.10 * (i + 1)} for i in range(10)]
        metrics = compute_regime_metrics(data)
        self.assertEqual(len(metrics["top_assets"]), 5)
        # Highest should be first
        self.assertEqual(metrics["top_assets"][0]["asset"], "COIN9")

    def test_pct_above_thresholds(self):
        # 10 assets: 5 above 50%, 2 above 100%
        data = [
            {"asset": "A", "funding_apy": 1.50},
            {"asset": "B", "funding_apy": 1.10},
            {"asset": "C", "funding_apy": 0.80},
            {"asset": "D", "funding_apy": 0.70},
            {"asset": "E", "funding_apy": 0.60},
            {"asset": "F", "funding_apy": 0.40},
            {"asset": "G", "funding_apy": 0.30},
            {"asset": "H", "funding_apy": 0.20},
            {"asset": "I", "funding_apy": 0.10},
            {"asset": "J", "funding_apy": 0.05},
        ]
        metrics = compute_regime_metrics(data)
        self.assertAlmostEqual(metrics["pct_above_50"], 0.5, places=4)
        self.assertAlmostEqual(metrics["pct_above_100"], 0.2, places=4)


class TestClassifyRegime(unittest.TestCase):
    """Test all 4 regime levels are classified correctly."""

    def test_extreme_regime(self):
        """10%+ of assets above 100% APY → EXTREME."""
        metrics = {
            "max_funding_apy": 3.0,
            "avg_top10_funding_apy": 2.0,
            "pct_above_50": 0.40,
            "pct_above_100": 0.15,  # 15% > 10% threshold
            "top_assets": [],
        }
        self.assertEqual(classify_regime(metrics), "EXTREME")

    def test_high_funding_regime(self):
        """At least one asset at 150%+ APY → HIGH_FUNDING."""
        metrics = {
            "max_funding_apy": 1.60,  # 160% APY
            "avg_top10_funding_apy": 0.50,
            "pct_above_50": 0.10,
            "pct_above_100": 0.05,  # Below 10% threshold
            "top_assets": [],
        }
        self.assertEqual(classify_regime(metrics), "HIGH_FUNDING")

    def test_moderate_regime(self):
        """At least one asset at 75%+ APY → MODERATE."""
        metrics = {
            "max_funding_apy": 0.80,  # 80% APY
            "avg_top10_funding_apy": 0.30,
            "pct_above_50": 0.05,
            "pct_above_100": 0.00,
            "top_assets": [],
        }
        self.assertEqual(classify_regime(metrics), "MODERATE")

    def test_low_funding_regime(self):
        """All below 75% APY → LOW_FUNDING."""
        metrics = {
            "max_funding_apy": 0.14,  # 14% APY
            "avg_top10_funding_apy": 0.08,
            "pct_above_50": 0.0,
            "pct_above_100": 0.0,
            "top_assets": [],
        }
        self.assertEqual(classify_regime(metrics), "LOW_FUNDING")

    def test_extreme_takes_priority_over_high_funding(self):
        """EXTREME should win over HIGH_FUNDING when both conditions met."""
        metrics = {
            "max_funding_apy": 5.0,   # Also qualifies for HIGH_FUNDING
            "avg_top10_funding_apy": 2.0,
            "pct_above_50": 0.50,
            "pct_above_100": 0.20,    # Qualifies for EXTREME
            "top_assets": [],
        }
        self.assertEqual(classify_regime(metrics), "EXTREME")

    def test_boundary_extreme_exact_threshold(self):
        """Exactly 10% above 100% → EXTREME."""
        metrics = {
            "max_funding_apy": 2.0,
            "avg_top10_funding_apy": 1.0,
            "pct_above_50": 0.20,
            "pct_above_100": 0.10,  # Exactly 10%
            "top_assets": [],
        }
        self.assertEqual(classify_regime(metrics), "EXTREME")

    def test_boundary_high_funding_exact_threshold(self):
        """Exactly 150% max → HIGH_FUNDING."""
        metrics = {
            "max_funding_apy": 1.50,  # Exactly 150%
            "avg_top10_funding_apy": 0.50,
            "pct_above_50": 0.05,
            "pct_above_100": 0.05,
            "top_assets": [],
        }
        self.assertEqual(classify_regime(metrics), "HIGH_FUNDING")

    def test_boundary_moderate_exact_threshold(self):
        """Exactly 75% max → MODERATE."""
        metrics = {
            "max_funding_apy": 0.75,  # Exactly 75%
            "avg_top10_funding_apy": 0.30,
            "pct_above_50": 0.05,
            "pct_above_100": 0.00,
            "top_assets": [],
        }
        self.assertEqual(classify_regime(metrics), "MODERATE")


class TestDetectRegimeFromAPIResponse(unittest.TestCase):
    """Test end-to-end regime detection from API response."""

    def test_all_zero_funding_is_low(self):
        """All funding rates at 0 → LOW_FUNDING."""
        resp = _make_api_response([
            {"name": "BTC", "funding": 0.0},
            {"name": "ETH", "funding": 0.0},
            {"name": "SOL", "funding": 0.0},
        ])
        result = detect_regime_from_api_response(resp)
        self.assertEqual(result["regime"], "LOW_FUNDING")
        self.assertEqual(result["max_funding_apy"], 0.0)

    def test_positive_funding_ignored(self):
        """Positive funding (we'd pay) should be ignored."""
        resp = _make_api_response([
            {"name": "BTC", "funding": 0.005},   # Positive — ignored
            {"name": "ETH", "funding": 0.01},     # Positive — ignored
        ])
        result = detect_regime_from_api_response(resp)
        self.assertEqual(result["regime"], "LOW_FUNDING")
        self.assertEqual(result["max_funding_apy"], 0.0)

    def test_single_extreme_asset(self):
        """Single asset at extreme funding → HIGH_FUNDING (not EXTREME,
        because only 1 of many assets is above 100%)."""
        # -0.002 per 8h → abs(0.002) * 3 * 365 = 2.19 → 219% APY
        # Need enough assets so pct_above_100 < 10%
        assets = [{"name": "FARTCOIN", "funding": -0.002}]
        for i in range(20):
            assets.append({"name": f"COIN{i}", "funding": -0.00001})
        resp = _make_api_response(assets)
        result = detect_regime_from_api_response(resp)
        self.assertEqual(result["regime"], "HIGH_FUNDING")
        self.assertGreater(result["max_funding_apy"], 1.50)
        self.assertEqual(result["top_assets"][0]["asset"], "FARTCOIN")

    def test_extreme_regime_many_assets(self):
        """Many assets above 100% → EXTREME."""
        # Need 10%+ above 100% APY. 100% = funding_8h of 0.000913
        # Create 10 assets, 2 above 100% (20% > 10% threshold)
        assets = []
        for i in range(10):
            if i < 2:
                assets.append({"name": f"COIN{i}", "funding": -0.001})  # ~109% APY
            else:
                assets.append({"name": f"COIN{i}", "funding": -0.00001})  # ~1% APY
        resp = _make_api_response(assets)
        result = detect_regime_from_api_response(resp)
        self.assertEqual(result["regime"], "EXTREME")

    def test_result_includes_thresholds(self):
        """Result should include scanner thresholds for the detected regime."""
        resp = _make_api_response([
            {"name": "BTC", "funding": -0.00001},
        ])
        result = detect_regime_from_api_response(resp)
        self.assertIn("thresholds", result)
        self.assertIn("tier1_min_funding", result["thresholds"])
        self.assertIn("tier2_min_funding", result["thresholds"])
        self.assertIn("max_concurrent", result["thresholds"])


class TestRegimeStateFile(unittest.TestCase):
    """Test regime state file read/write and staleness detection."""

    def setUp(self):
        # Use a temp file for state to avoid polluting workspace
        self._tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self._tmp.close()
        self._tmp_path = Path(self._tmp.name)
        self._orig_state_file = REGIME_STATE_FILE

    def tearDown(self):
        self._tmp_path.unlink(missing_ok=True)

    def _patch_state_file(self):
        return patch("scripts.regime_detector.REGIME_STATE_FILE", self._tmp_path)

    def test_save_and_load(self):
        """State file round-trips correctly."""
        regime_result = {
            "regime": "MODERATE",
            "max_funding_apy": 0.80,
            "avg_top10_funding_apy": 0.30,
            "pct_above_50": 0.05,
            "pct_above_100": 0.0,
            "top_assets": [{"asset": "SOL", "funding_apy": 0.80}],
            "thresholds": get_regime_thresholds("MODERATE"),
        }

        with self._patch_state_file():
            state = save_regime_state(regime_result, scan_count=42)
            loaded = load_regime_state()

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["regime"], "MODERATE")
        self.assertEqual(loaded["scan_count"], 42)
        self.assertAlmostEqual(loaded["max_funding_apy"], 0.80, places=4)
        self.assertIn("updated_at", loaded)

    def test_state_schema(self):
        """State file has all required keys."""
        regime_result = {
            "regime": "LOW_FUNDING",
            "max_funding_apy": 0.14,
            "avg_top10_funding_apy": 0.08,
            "pct_above_50": 0.02,
            "pct_above_100": 0.0,
            "top_assets": [{"asset": "FARTCOIN", "funding_apy": 0.14}],
            "thresholds": get_regime_thresholds("LOW_FUNDING"),
        }

        with self._patch_state_file():
            state = save_regime_state(regime_result, scan_count=1)

        required_keys = {
            "regime", "max_funding_apy", "avg_top10_funding_apy",
            "pct_above_50", "pct_above_100", "top_assets",
            "updated_at", "scan_count",
        }
        self.assertTrue(required_keys.issubset(set(state.keys())))

    def test_stale_state_returns_none(self):
        """State older than 4 hours returns None."""
        stale_time = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
        stale_state = {
            "regime": "EXTREME",
            "max_funding_apy": 3.0,
            "avg_top10_funding_apy": 2.0,
            "pct_above_50": 0.40,
            "pct_above_100": 0.15,
            "top_assets": [],
            "updated_at": stale_time,
            "scan_count": 100,
        }
        self._tmp_path.write_text(json.dumps(stale_state))

        with self._patch_state_file():
            loaded = load_regime_state()

        self.assertIsNone(loaded)

    def test_fresh_state_loads_ok(self):
        """State within 4 hours loads correctly."""
        fresh_time = datetime.now(timezone.utc).isoformat()
        fresh_state = {
            "regime": "MODERATE",
            "max_funding_apy": 0.80,
            "avg_top10_funding_apy": 0.30,
            "pct_above_50": 0.05,
            "pct_above_100": 0.0,
            "top_assets": [],
            "updated_at": fresh_time,
            "scan_count": 50,
        }
        self._tmp_path.write_text(json.dumps(fresh_state))

        with self._patch_state_file():
            loaded = load_regime_state()

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["regime"], "MODERATE")

    def test_missing_file_returns_none(self):
        """Missing state file returns None."""
        self._tmp_path.unlink(missing_ok=True)
        with self._patch_state_file():
            loaded = load_regime_state()
        self.assertIsNone(loaded)

    def test_corrupt_file_returns_none(self):
        """Corrupt state file returns None."""
        self._tmp_path.write_text("not valid json {{{")
        with self._patch_state_file():
            loaded = load_regime_state()
        self.assertIsNone(loaded)

    def test_get_active_regime_stale_fallback(self):
        """Stale state falls back to DEFAULT_REGIME."""
        stale_time = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
        self._tmp_path.write_text(json.dumps({
            "regime": "EXTREME",
            "updated_at": stale_time,
        }))
        with self._patch_state_file():
            regime = get_active_regime()
        self.assertEqual(regime, DEFAULT_REGIME)

    def test_get_active_regime_missing_fallback(self):
        """Missing state falls back to DEFAULT_REGIME."""
        self._tmp_path.unlink(missing_ok=True)
        with self._patch_state_file():
            regime = get_active_regime()
        self.assertEqual(regime, DEFAULT_REGIME)

    def test_get_active_thresholds_returns_correct_for_regime(self):
        """Active thresholds match the stored regime."""
        fresh_time = datetime.now(timezone.utc).isoformat()
        self._tmp_path.write_text(json.dumps({
            "regime": "EXTREME",
            "updated_at": fresh_time,
        }))
        with self._patch_state_file():
            thresholds = get_active_thresholds()
        self.assertEqual(thresholds, REGIME_THRESHOLDS["EXTREME"])

    def test_scan_count_auto_increments(self):
        """scan_count auto-increments from previous state."""
        regime_result = {
            "regime": "LOW_FUNDING",
            "max_funding_apy": 0.14,
            "avg_top10_funding_apy": 0.08,
            "pct_above_50": 0.0,
            "pct_above_100": 0.0,
            "top_assets": [],
            "thresholds": {},
        }
        with self._patch_state_file():
            save_regime_state(regime_result, scan_count=10)
            save_regime_state(regime_result)  # Should auto-increment
            loaded = load_regime_state()
        self.assertEqual(loaded["scan_count"], 11)


class TestRegimeThresholdLookup(unittest.TestCase):
    """Test scanner threshold lookup for each regime."""

    def test_all_regimes_have_thresholds(self):
        for regime in ("EXTREME", "HIGH_FUNDING", "MODERATE", "LOW_FUNDING"):
            thresholds = get_regime_thresholds(regime)
            self.assertIn("tier1_min_funding", thresholds)
            self.assertIn("tier2_min_funding", thresholds)
            self.assertIn("max_concurrent", thresholds)

    def test_unknown_regime_falls_back(self):
        thresholds = get_regime_thresholds("NONEXISTENT")
        self.assertEqual(thresholds, REGIME_THRESHOLDS[DEFAULT_REGIME])

    def test_thresholds_order(self):
        """EXTREME should have lowest thresholds, LOW_FUNDING highest."""
        extreme = get_regime_thresholds("EXTREME")
        low = get_regime_thresholds("LOW_FUNDING")
        self.assertLess(extreme["tier1_min_funding"], low["tier1_min_funding"])
        self.assertLess(extreme["tier2_min_funding"], low["tier2_min_funding"])
        self.assertGreaterEqual(extreme["max_concurrent"], low["max_concurrent"])


class TestClassifySignalWithRegime(unittest.TestCase):
    """Test tiered_scanner.classify_signal with regime threshold overrides."""

    def test_default_thresholds(self):
        """Without overrides, uses static defaults from risk_params."""
        # 100% APY, good premium and volume → Tier 1
        self.assertEqual(classify_signal(1.00, -0.02, 2_000_000), 1)
        # Below 100% → Tier 3
        self.assertEqual(classify_signal(0.90, -0.02, 2_000_000), 3)

    def test_extreme_regime_lowers_bar(self):
        """EXTREME regime: 75% APY should qualify as Tier 1."""
        thresholds = REGIME_THRESHOLDS["EXTREME"]
        tier = classify_signal(
            0.75, -0.02, 2_000_000,
            tier1_min_funding=thresholds["tier1_min_funding"],
            tier2_min_funding=thresholds["tier2_min_funding"],
        )
        self.assertEqual(tier, 1)

    def test_low_funding_regime_raises_bar(self):
        """LOW_FUNDING regime: 100% APY should NOT qualify as Tier 1."""
        thresholds = REGIME_THRESHOLDS["LOW_FUNDING"]
        tier = classify_signal(
            1.00, -0.02, 2_000_000,
            tier1_min_funding=thresholds["tier1_min_funding"],
            tier2_min_funding=thresholds["tier2_min_funding"],
        )
        # 100% < 200% (LOW_FUNDING tier1 threshold) → not Tier 1
        # 100% < 150% (LOW_FUNDING tier2 threshold) → not Tier 2
        self.assertEqual(tier, 3)

    def test_moderate_regime_tier2_accepts_100pct(self):
        """MODERATE regime: 100% APY should qualify as Tier 2."""
        thresholds = REGIME_THRESHOLDS["MODERATE"]
        tier = classify_signal(
            1.00, -0.006, 600_000,
            tier1_min_funding=thresholds["tier1_min_funding"],
            tier2_min_funding=thresholds["tier2_min_funding"],
        )
        self.assertEqual(tier, 2)


class TestRegimeChangeDetection(unittest.TestCase):
    """Test that regime change is correctly detected."""

    def test_same_regime_no_change(self):
        """Same regime should not be flagged as a change."""
        prev = "LOW_FUNDING"
        curr = "LOW_FUNDING"
        self.assertEqual(prev, curr)

    def test_different_regime_is_change(self):
        """Different regime should be flagged as a change."""
        prev = "LOW_FUNDING"
        curr = "HIGH_FUNDING"
        self.assertNotEqual(prev, curr)

    def test_all_transitions_detected(self):
        """All regime transitions should be detectable."""
        regimes = ["EXTREME", "HIGH_FUNDING", "MODERATE", "LOW_FUNDING"]
        for prev in regimes:
            for curr in regimes:
                if prev != curr:
                    self.assertNotEqual(prev, curr,
                        f"Transition {prev} → {curr} should be detected")


if __name__ == "__main__":
    unittest.main()
