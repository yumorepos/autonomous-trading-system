"""Tests for CompositeSignalScorer — gating logic and scoring."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models import RegimeTransitionEvent, RegimeTier, ScoredSignal
from src.scoring.composite_scorer import CompositeSignalScorer
from src.scoring.duration_predictor import DurationEstimate


def _make_event(
    asset: str = "BTC",
    exchange: str = "binance",
    new_regime: RegimeTier = RegimeTier.HIGH_FUNDING,
    previous_regime: RegimeTier = RegimeTier.MODERATE,
    max_apy: float = 150.0,
) -> RegimeTransitionEvent:
    return RegimeTransitionEvent(
        asset=asset,
        exchange=exchange,
        new_regime=new_regime,
        previous_regime=previous_regime,
        max_apy_annualized=max_apy,
        timestamp_utc=datetime(2026, 4, 13, 12, 0, 0, tzinfo=timezone.utc),
    )


_TEST_CONFIG = {
    "scoring_weights": {
        "net_apy": 0.35,
        "duration_confidence": 0.30,
        "liquidity": 0.20,
        "cross_exchange_spread": 0.15,
    },
    "exchanges": {
        "binance": {
            "enabled": True,
            "base_url": "https://fapi.binance.com",
            "fee_rate_round_trip": 0.0008,
            "funding_interval_hours": 8,
        },
        "hyperliquid": {
            "enabled": True,
            "base_url": "https://api.hyperliquid.xyz",
            "fee_rate_round_trip": 0.0005,
            "funding_interval_hours": 1,
        },
    },
    "duration_filter": {"min_duration_minutes": 15, "min_survival_probability": 0.40},
    "liquidity_filter": {"min_liquidity_score": 0.15},
    "min_composite_score": 35.0,
    "min_net_apy_annualized": 15.0,
    "regime_thresholds": {"low_funding_max_apy": 20, "moderate_max_apy": 80},
}


@pytest.fixture
def scorer():
    duration_pred = MagicMock()
    duration_pred.predict.return_value = DurationEstimate(
        survival_probability=0.65,
        expected_duration_min=25.0,
        sample_count=100,
        used_fallback=False,
    )

    liquidity = AsyncMock()
    liquidity.score = AsyncMock(return_value=0.55)

    with patch("src.scoring.composite_scorer.get_config", return_value=_TEST_CONFIG):
        s = CompositeSignalScorer(duration_pred, liquidity)

    return s, duration_pred, liquidity


class TestCompositeScorer:

    @pytest.mark.asyncio
    async def test_actionable_high_funding(self, scorer):
        """HIGH_FUNDING with good metrics should be actionable."""
        s, _, _ = scorer
        event = _make_event(max_apy=150.0)
        result = await s.score(event)

        assert result.is_actionable
        assert result.rejection_reason is None
        assert result.composite_score > 35.0

    @pytest.mark.asyncio
    async def test_rejects_moderate_regime(self, scorer):
        """MODERATE regime should be rejected."""
        s, _, _ = scorer
        event = _make_event(new_regime=RegimeTier.MODERATE)
        result = await s.score(event)

        assert not result.is_actionable
        assert "not HIGH_FUNDING" in result.rejection_reason

    @pytest.mark.asyncio
    async def test_rejects_low_survival_prob(self, scorer):
        """Low duration survival probability should reject."""
        s, dp, _ = scorer
        dp.predict.return_value = DurationEstimate(
            survival_probability=0.20,  # Below 0.40 threshold
            expected_duration_min=5.0,
            sample_count=50,
            used_fallback=False,
        )
        event = _make_event()
        result = await s.score(event)

        assert not result.is_actionable
        assert "Duration survival prob" in result.rejection_reason

    @pytest.mark.asyncio
    async def test_rejects_low_liquidity(self, scorer):
        """Low liquidity should reject."""
        s, _, liq = scorer
        liq.score = AsyncMock(return_value=0.05)  # Below 0.15

        event = _make_event()
        result = await s.score(event)

        assert not result.is_actionable
        assert "Liquidity score" in result.rejection_reason

    @pytest.mark.asyncio
    async def test_rejects_low_net_apy(self, scorer):
        """Net APY below threshold should reject."""
        s, _, _ = scorer
        event = _make_event(max_apy=10.0)  # After fees, well below 15%
        result = await s.score(event)

        assert not result.is_actionable
        assert "Net APY" in result.rejection_reason

    @pytest.mark.asyncio
    async def test_multiple_rejection_reasons(self, scorer):
        """Multiple gate failures should all appear in rejection reason."""
        s, dp, liq = scorer
        dp.predict.return_value = DurationEstimate(
            survival_probability=0.10, expected_duration_min=2.0,
            sample_count=50, used_fallback=False,
        )
        liq.score = AsyncMock(return_value=0.05)

        event = _make_event(new_regime=RegimeTier.LOW_FUNDING, max_apy=5.0)
        result = await s.score(event)

        assert not result.is_actionable
        reasons = result.rejection_reason
        assert "not HIGH_FUNDING" in reasons
        assert "Duration survival prob" in reasons
        assert "Liquidity score" in reasons
        assert "Net APY" in reasons

    @pytest.mark.asyncio
    async def test_score_bounded_0_100(self, scorer):
        """Composite score should always be in [0, 100]."""
        s, dp, liq = scorer

        # Test with extreme high values
        dp.predict.return_value = DurationEstimate(
            survival_probability=1.0, expected_duration_min=1000.0,
            sample_count=500, used_fallback=False,
        )
        liq.score = AsyncMock(return_value=1.0)

        event = _make_event(max_apy=1000.0)
        result = await s.score(event)
        assert 0.0 <= result.composite_score <= 100.0

        # Test with extreme low values
        dp.predict.return_value = DurationEstimate(
            survival_probability=0.0, expected_duration_min=0.0,
            sample_count=0, used_fallback=True,
        )
        liq.score = AsyncMock(return_value=0.0)

        event = _make_event(max_apy=0.0)
        result = await s.score(event)
        assert 0.0 <= result.composite_score <= 100.0

    @pytest.mark.asyncio
    async def test_net_apy_accounts_for_fees(self, scorer):
        """Net APY should be gross APY minus fee cost."""
        s, _, _ = scorer
        event = _make_event(max_apy=100.0, exchange="binance")
        result = await s.score(event)

        # Binance fee: 0.08% = 0.0008 * 100 = 0.08
        expected_net = 100.0 - 0.08
        assert abs(result.net_expected_apy - expected_net) < 0.1
