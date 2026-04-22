"""D45 — engine.estimate_volumes must compute USD-notional, not coin count.

Mirrors HL ``dayNtlVlm`` (scripts/tiered_scanner.py:76). See
analysis/volume_filter_audit/REPORT.md.
"""
from __future__ import annotations

import math
import pytest

from scripts.backtest.engine import estimate_volumes


def _mk_candle(open_px: float, close_px: float, volume: float, high: float | None = None, low: float | None = None) -> dict:
    return {
        "open": open_px,
        "high": high if high is not None else max(open_px, close_px),
        "low": low if low is not None else min(open_px, close_px),
        "close": close_px,
        "volume": volume,
    }


def _flat_series(n_bars: int, close_px: float, vol_per_bar: float) -> dict[int, dict]:
    """n_bars 1h candles, flat price, fixed volume per bar."""
    return {i * 3_600_000: _mk_candle(close_px, close_px, vol_per_bar) for i in range(n_bars)}


class TestEstimateVolumesUSDSemantic:
    def test_unit_coin_at_unit_price_is_dollar_per_bar(self):
        # 24 bars × 1 coin × $1 = $24 total over the window
        market = {"ASSET": _flat_series(24, close_px=1.0, vol_per_bar=1.0)}
        vol = estimate_volumes(market)
        assert math.isclose(vol["ASSET"], 24.0, rel_tol=1e-9)

    def test_explicit_case_coin_1000_close_1_usd_1000(self):
        # Single bar, 1000 coins, $1 close → $1000 USD. Fewer than 24 bars ⇒ use all.
        market = {"SPOT": {0: _mk_candle(1.0, 1.0, 1000.0)}}
        vol = estimate_volumes(market)
        assert math.isclose(vol["SPOT"], 1000.0, rel_tol=1e-9)

    def test_memecoin_100M_coin_at_cent_clears_1M_threshold(self):
        # 100M coins at $0.01 = $1M USD total across 24 flat bars —
        # clears TIER2_MIN_VOLUME=$500K under USD semantic (would also
        # have cleared under coin-count, but the key is the numeric equality).
        market = {"MEME1": _flat_series(24, close_px=0.01, vol_per_bar=100_000_000 / 24)}
        vol = estimate_volumes(market)
        assert math.isclose(vol["MEME1"], 1_000_000.0, rel_tol=1e-9)
        assert vol["MEME1"] >= 500_000  # USD threshold ✅

    def test_ultra_low_price_fails_threshold_despite_large_coin_count(self):
        # 1M coins at $0.0001 = $100 USD — below USD $500K threshold.
        # Under the OLD coin-count semantic: 1M > 500K → would have PASSED.
        # This is exactly the mismatch D45 fixes.
        market = {"DUST": {0: _mk_candle(0.0001, 0.0001, 1_000_000.0)}}
        vol = estimate_volumes(market)
        assert math.isclose(vol["DUST"], 100.0, rel_tol=1e-9)
        assert vol["DUST"] < 500_000  # USD threshold ❌ (was ✅ under coin-count)

    def test_synthetic_24_bar_series_sum_matches_hand_math(self):
        # Varying prices and volumes — exact expected sum across the window.
        bars: dict[int, dict] = {}
        expected = 0.0
        for i in range(24):
            close = 10.0 + i * 0.5
            vol = 100.0 + i * 10.0
            bars[i * 3_600_000] = _mk_candle(close, close, vol)
            expected += close * vol
        vol_out = estimate_volumes({"VAR": bars})
        assert math.isclose(vol_out["VAR"], expected, rel_tol=1e-9)

    def test_only_last_24_bars_are_used_when_series_is_longer(self):
        # 48 bars: bars 0–23 with close=1 vol=100 ($100 each → total would be
        # $2,400 if included); bars 24–47 with close=5 vol=200 ($1000 each →
        # $24,000 if only these are used). Expect $24,000.
        bars: dict[int, dict] = {}
        for i in range(24):
            bars[i * 3_600_000] = _mk_candle(1.0, 1.0, 100.0)
        for i in range(24, 48):
            bars[i * 3_600_000] = _mk_candle(5.0, 5.0, 200.0)
        vol_out = estimate_volumes({"TRIM": bars})
        assert math.isclose(vol_out["TRIM"], 24_000.0, rel_tol=1e-9)

    def test_fewer_than_24_bars_uses_all(self):
        # 5 bars, flat close=$2, vol=50 coins per bar → 5 × 2 × 50 = $500
        market = {"SHORT": _flat_series(5, close_px=2.0, vol_per_bar=50.0)}
        vol = estimate_volumes(market)
        assert math.isclose(vol["SHORT"], 500.0, rel_tol=1e-9)

    def test_empty_candles_yields_zero(self):
        vol = estimate_volumes({"EMPTY": {}})
        assert vol["EMPTY"] == 0.0

    def test_multi_asset_independent_computation(self):
        market = {
            "A": _flat_series(24, close_px=1.0, vol_per_bar=100.0),   # $2,400
            "B": _flat_series(24, close_px=10.0, vol_per_bar=500.0),  # $120,000
        }
        vol = estimate_volumes(market)
        assert math.isclose(vol["A"], 2_400.0, rel_tol=1e-9)
        assert math.isclose(vol["B"], 120_000.0, rel_tol=1e-9)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
