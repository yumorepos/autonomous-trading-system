"""Tests for SignalFilterPipeline — end-to-end signal processing."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models import RegimeTransitionEvent, RegimeTier, ScoredSignal
from src.pipeline.signal_filter import SignalFilterPipeline
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
        # Use a "now"-anchored timestamp so stats queries with 24h windows
        # in get_stats() keep finding these events as wall-clock time
        # advances past the originally hardcoded 2026-04-13 date.
        timestamp_utc=datetime.now(timezone.utc),
    )


_TEST_CONFIG = {
    "history": {"signal_log_path": ":memory:", "db_path": "data/regime_history.db", "backfill_days": 30},
    "telegram": {"bot_token": "", "chat_id": "", "send_rejected": False},
    "scoring_weights": {"net_apy": 0.35, "duration_confidence": 0.30, "liquidity": 0.20, "cross_exchange_spread": 0.15},
    "exchanges": {"binance": {"fee_rate_round_trip": 0.0008, "funding_interval_hours": 8}},
    "duration_filter": {"min_duration_minutes": 15, "min_survival_probability": 0.40},
    "liquidity_filter": {"min_liquidity_score": 0.15},
    "min_composite_score": 35.0,
    "min_net_apy_annualized": 15.0,
    "regime_thresholds": {"low_funding_max_apy": 20, "moderate_max_apy": 80},
}


def _make_actionable_signal(event: RegimeTransitionEvent) -> ScoredSignal:
    return ScoredSignal(
        event=event,
        composite_score=72.5,
        duration_survival_prob=0.65,
        expected_duration_min=25.0,
        liquidity_score=0.55,
        net_expected_apy=149.92,
        is_actionable=True,
        rejection_reason=None,
        cross_exchange_spread=None,
    )


def _make_rejected_signal(event: RegimeTransitionEvent, reason: str = "Test rejection") -> ScoredSignal:
    return ScoredSignal(
        event=event,
        composite_score=15.0,
        duration_survival_prob=0.20,
        expected_duration_min=3.0,
        liquidity_score=0.05,
        net_expected_apy=8.0,
        is_actionable=False,
        rejection_reason=reason,
        cross_exchange_spread=None,
    )


@pytest.fixture
def pipeline(tmp_path):
    """Create pipeline with mocked scorer."""
    signal_log = tmp_path / "signal_log.db"

    scorer = AsyncMock(spec=CompositeSignalScorer)

    with patch("src.pipeline.signal_filter.get_config", return_value=_TEST_CONFIG):
        p = SignalFilterPipeline(scorer, signal_log_path=signal_log)

    return p, scorer, signal_log


class TestSignalFilterPipeline:

    @pytest.mark.asyncio
    async def test_process_actionable_signal(self, pipeline):
        p, scorer, log_path = pipeline
        event = _make_event()
        scorer.score = AsyncMock(return_value=_make_actionable_signal(event))

        result = await p.process(event)

        assert result.is_actionable
        assert result.composite_score == 72.5

        # Verify logged to DB
        conn = sqlite3.connect(str(log_path))
        count = conn.execute("SELECT COUNT(*) FROM signal_log").fetchone()[0]
        conn.close()
        assert count == 1

    @pytest.mark.asyncio
    async def test_process_rejected_signal(self, pipeline):
        p, scorer, log_path = pipeline
        event = _make_event(new_regime=RegimeTier.LOW_FUNDING)
        scorer.score = AsyncMock(return_value=_make_rejected_signal(event))

        result = await p.process(event)

        assert not result.is_actionable

        # Still logged
        conn = sqlite3.connect(str(log_path))
        count = conn.execute("SELECT COUNT(*) FROM signal_log WHERE is_actionable=0").fetchone()[0]
        conn.close()
        assert count == 1

    @pytest.mark.asyncio
    async def test_process_batch(self, pipeline):
        p, scorer, _ = pipeline

        events = [
            _make_event(asset="BTC", max_apy=150.0),
            _make_event(asset="ETH", max_apy=200.0),
            _make_event(asset="BLAST", new_regime=RegimeTier.LOW_FUNDING, max_apy=10.0),
        ]

        scorer.score = AsyncMock(side_effect=[
            _make_actionable_signal(events[0]),
            _make_actionable_signal(events[1]),
            _make_rejected_signal(events[2]),
        ])

        results = await p.process_batch(events)

        assert len(results) == 3
        assert results[0].is_actionable
        assert results[1].is_actionable
        assert not results[2].is_actionable

    @pytest.mark.asyncio
    async def test_synthetic_10_events_correct_filtering(self, pipeline):
        """Test with 10 synthetic events — verify correct actionable subset."""
        p, scorer, _ = pipeline

        # 10 events: 4 HIGH_FUNDING (good), 3 MODERATE, 3 LOW_FUNDING
        events = [
            _make_event(asset="BTC", max_apy=200.0),
            _make_event(asset="ETH", max_apy=180.0),
            _make_event(asset="IMX", max_apy=120.0),
            _make_event(asset="JTO", max_apy=105.0),
            _make_event(asset="BLAST", new_regime=RegimeTier.MODERATE, max_apy=50.0),
            _make_event(asset="YZY", new_regime=RegimeTier.MODERATE, max_apy=40.0),
            _make_event(asset="0G", new_regime=RegimeTier.MODERATE, max_apy=60.0),
            _make_event(asset="STABLE", new_regime=RegimeTier.LOW_FUNDING, max_apy=5.0),
            _make_event(asset="BTC", new_regime=RegimeTier.LOW_FUNDING, max_apy=10.0),
            _make_event(asset="ETH", new_regime=RegimeTier.LOW_FUNDING, max_apy=8.0),
        ]

        signals = []
        for e in events:
            if e.new_regime == RegimeTier.HIGH_FUNDING and e.max_apy_annualized >= 100:
                signals.append(_make_actionable_signal(e))
            else:
                reason = "Test"
                if e.new_regime != RegimeTier.HIGH_FUNDING:
                    reason = f"Regime is {e.new_regime.value}, not HIGH_FUNDING"
                signals.append(_make_rejected_signal(e, reason))

        scorer.score = AsyncMock(side_effect=signals)
        results = await p.process_batch(events)

        actionable = [r for r in results if r.is_actionable]
        rejected = [r for r in results if not r.is_actionable]

        # First 4 are HIGH_FUNDING with high APY
        assert len(actionable) == 4
        assert len(rejected) == 6

        # Verify actionable assets
        actionable_assets = {r.event.asset for r in actionable}
        assert actionable_assets == {"BTC", "ETH", "IMX", "JTO"}

    def test_get_stats_empty(self, pipeline):
        p, _, _ = pipeline
        stats = p.get_stats()

        assert stats["total_signals"] == 0
        assert stats["actionable_signals"] == 0
        assert stats["actionable_rate_pct"] == 0.0

    @pytest.mark.asyncio
    async def test_get_stats_after_processing(self, pipeline):
        p, scorer, _ = pipeline

        events = [
            _make_event(asset="BTC"),
            _make_event(asset="ETH", new_regime=RegimeTier.LOW_FUNDING),
        ]

        scorer.score = AsyncMock(side_effect=[
            _make_actionable_signal(events[0]),
            _make_rejected_signal(events[1]),
        ])

        await p.process_batch(events)
        stats = p.get_stats()

        assert stats["total_signals"] == 2
        assert stats["actionable_signals"] == 1
        assert stats["actionable_rate_pct"] == 50.0

    def test_telegram_alert_format(self, pipeline):
        p, _, _ = pipeline
        event = _make_event()
        signal = _make_actionable_signal(event)

        alert = p._format_actionable_alert(signal)

        assert "ACTIONABLE SIGNAL" in alert
        assert "BTC" in alert
        assert "binance" in alert
        assert "/100" in alert
