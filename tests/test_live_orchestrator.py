"""Tests for LiveOrchestrator — event routing and position management."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.models import RegimeTier, RegimeTransitionEvent, ScoredSignal
from src.pipeline.live_orchestrator import LiveOrchestrator


def _mock_config():
    return {
        "simulator": {"log_path": "data/paper_trades.jsonl"},
        "regime_thresholds": {"low_funding_max_apy": 20, "moderate_max_apy": 80},
        "exchanges": {},
        "telegram": {"bot_token": "", "chat_id": ""},
        "history": {"signal_log_path": "data/signal_log.db"},
    }


def _make_event(
    asset="ETH", exchange="hyperliquid",
    new_regime=RegimeTier.HIGH_FUNDING, prev_regime=RegimeTier.MODERATE,
    apy=150.0,
) -> RegimeTransitionEvent:
    return RegimeTransitionEvent(
        asset=asset,
        exchange=exchange,
        new_regime=new_regime,
        previous_regime=prev_regime,
        max_apy_annualized=apy,
        timestamp_utc=datetime(2026, 4, 13, 12, 0, tzinfo=timezone.utc),
    )


def _make_signal(event, actionable=True, score=72.0) -> ScoredSignal:
    return ScoredSignal(
        event=event,
        composite_score=score,
        duration_survival_prob=0.75,
        expected_duration_min=45.0,
        liquidity_score=0.6,
        net_expected_apy=event.max_apy_annualized - 0.08,
        is_actionable=actionable,
    )


@pytest.fixture
def orchestrator(tmp_path):
    connector = MagicMock()
    pipeline = MagicMock()
    pipeline.process = AsyncMock()

    with patch("src.simulator.paper_trader.get_config", return_value=_mock_config()):
        from src.simulator.paper_trader import PaperTrader
        paper_trader = PaperTrader(
            notional_per_trade=1000.0,
            max_open_positions=5,
            log_path=tmp_path / "trades.jsonl",
        )

    return LiveOrchestrator(connector, pipeline, paper_trader)


class TestHandleEvent:
    @pytest.mark.asyncio
    async def test_actionable_opens_position(self, orchestrator):
        event = _make_event()
        signal = _make_signal(event, actionable=True)
        orchestrator.pipeline.process.return_value = signal

        result = await orchestrator.handle_event(event)

        assert result.is_actionable
        assert orchestrator._events_processed == 1
        assert orchestrator._signals_actionable == 1
        assert orchestrator._positions_opened == 1
        assert len(orchestrator.paper_trader.open_positions) == 1

    @pytest.mark.asyncio
    async def test_rejected_signal_no_position(self, orchestrator):
        event = _make_event(new_regime=RegimeTier.MODERATE)
        signal = _make_signal(event, actionable=False)
        orchestrator.pipeline.process.return_value = signal

        await orchestrator.handle_event(event)

        assert orchestrator._events_processed == 1
        assert orchestrator._signals_actionable == 0
        assert orchestrator._positions_opened == 0

    @pytest.mark.asyncio
    async def test_regime_exit_closes_positions(self, orchestrator):
        # First: open a position
        event1 = _make_event(asset="ETH")
        signal1 = _make_signal(event1, actionable=True)
        orchestrator.pipeline.process.return_value = signal1
        await orchestrator.handle_event(event1)
        assert len(orchestrator.paper_trader.open_positions) == 1

        # Then: regime drops from HIGH_FUNDING → MODERATE
        event2 = _make_event(
            asset="ETH",
            new_regime=RegimeTier.MODERATE,
            prev_regime=RegimeTier.HIGH_FUNDING,
        )
        signal2 = _make_signal(event2, actionable=False)
        orchestrator.pipeline.process.return_value = signal2
        await orchestrator.handle_event(event2)

        assert len(orchestrator.paper_trader.open_positions) == 0
        assert orchestrator._positions_closed == 1

    @pytest.mark.asyncio
    async def test_multiple_assets_tracked(self, orchestrator):
        for asset in ["ETH", "BTC", "SOL"]:
            event = _make_event(asset=asset)
            signal = _make_signal(event, actionable=True)
            orchestrator.pipeline.process.return_value = signal
            await orchestrator.handle_event(event)

        assert len(orchestrator.paper_trader.open_positions) == 3
        assert orchestrator._positions_opened == 3


class TestGetStatus:
    @pytest.mark.asyncio
    async def test_status_structure(self, orchestrator):
        event = _make_event()
        signal = _make_signal(event, actionable=True)
        orchestrator.pipeline.process.return_value = signal
        await orchestrator.handle_event(event)

        status = orchestrator.get_status()
        assert "orchestrator" in status
        assert "paper_trading" in status
        assert "open_positions" in status
        assert status["orchestrator"]["events_processed"] == 1
        assert status["orchestrator"]["positions_opened"] == 1
        assert len(status["open_positions"]) == 1
