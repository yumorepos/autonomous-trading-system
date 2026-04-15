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

    orch = LiveOrchestrator(connector, pipeline, paper_trader)
    # Stub price and funding fetches so unit tests don't hit Hyperliquid API
    orch._get_mid_prices = lambda: {}
    orch._get_funding_rates = lambda: {}
    return orch


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
    async def test_regime_downgrade_does_not_close_position(self, orchestrator):
        """Regime downgrade from HIGH_FUNDING must NOT close the paper
        position — SL/TP/TIMEOUT/TRAILING now manage exits (matches
        backtester). Behavior diverged from legacy regime_exit close.
        """
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

        # Position still open — only SL/TP/TIMEOUT/TRAILING can close it.
        assert len(orchestrator.paper_trader.open_positions) == 1
        assert orchestrator._positions_closed == 0

    @pytest.mark.asyncio
    async def test_multiple_assets_tracked(self, orchestrator):
        for asset in ["ETH", "BTC", "SOL"]:
            event = _make_event(asset=asset)
            signal = _make_signal(event, actionable=True)
            orchestrator.pipeline.process.return_value = signal
            await orchestrator.handle_event(event)

        assert len(orchestrator.paper_trader.open_positions) == 3
        assert orchestrator._positions_opened == 3


class TestStartupRegimeEvaluation:
    @pytest.mark.asyncio
    async def test_startup_high_funding_opens_position(self, orchestrator):
        """On startup with HIGH_FUNDING regime cached, a position opens."""
        orchestrator.connector.current_regime_status.return_value = {
            "regime": "HIGH_FUNDING",
            "max_funding_apy": 1.01,
            "top_asset": "YZY",
        }
        orchestrator.connector._resolve_top_asset.return_value = ("YZY", "hyperliquid")

        signal_event = _make_event(asset="YZY", apy=101.0)
        signal = _make_signal(signal_event, actionable=True)
        orchestrator.pipeline.process.return_value = signal

        await orchestrator._evaluate_startup_regime()

        assert orchestrator._events_processed == 1
        assert orchestrator._positions_opened == 1
        assert len(orchestrator.paper_trader.open_positions) == 1

    @pytest.mark.asyncio
    async def test_startup_non_high_funding_does_nothing(self, orchestrator):
        orchestrator.connector.current_regime_status.return_value = {
            "regime": "MODERATE",
            "max_funding_apy": 0.80,
            "top_asset": "YZY",
        }

        await orchestrator._evaluate_startup_regime()

        assert orchestrator._events_processed == 0
        assert orchestrator._positions_opened == 0

    @pytest.mark.asyncio
    async def test_startup_no_status_does_nothing(self, orchestrator):
        orchestrator.connector.current_regime_status.return_value = None

        await orchestrator._evaluate_startup_regime()

        assert orchestrator._events_processed == 0

    @pytest.mark.asyncio
    async def test_startup_unknown_asset_skips(self, orchestrator):
        orchestrator.connector.current_regime_status.return_value = {
            "regime": "HIGH_FUNDING",
            "max_funding_apy": 1.05,
        }
        orchestrator.connector._resolve_top_asset.return_value = ("UNKNOWN", "hyperliquid")

        await orchestrator._evaluate_startup_regime()

        assert orchestrator._events_processed == 0


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



# --- New tests: directional exit triggers via _check_paper_exits ---

from datetime import timedelta


class TestPaperExitChecks:
    @pytest.mark.asyncio
    async def test_stop_loss_closes_position(self, orchestrator):
        """With entry_price set, a big adverse move closes via STOP_LOSS."""
        from config.risk_params import STOP_LOSS_ROE
        # Open short at 100
        event = _make_event(asset="ETH")
        event.timestamp_utc = datetime.now(timezone.utc)
        signal = _make_signal(event, actionable=True)
        orchestrator.pipeline.process.return_value = signal
        orchestrator._get_mid_prices = lambda: {"ETH": 100.0}
        await orchestrator.handle_event(event)
        assert len(orchestrator.paper_trader.open_positions) == 1
        pos = orchestrator.paper_trader.open_positions[0]
        assert pos.entry_price == 100.0
        assert pos.direction == "short"

        # Price spikes up — short loses. Use |SL|+1% buffer.
        bad_price = 100.0 * (1 + abs(STOP_LOSS_ROE) + 0.01)
        orchestrator._get_mid_prices = lambda: {"ETH": bad_price}
        # Any further event triggers the exit check
        event2 = _make_event(asset="BTC", new_regime=RegimeTier.MODERATE,
                             prev_regime=RegimeTier.MODERATE)
        signal2 = _make_signal(event2, actionable=False)
        orchestrator.pipeline.process.return_value = signal2
        await orchestrator.handle_event(event2)

        assert len(orchestrator.paper_trader.open_positions) == 0
        closed = orchestrator.paper_trader.closed_positions[-1]
        assert closed.exit_reason == "STOP_LOSS"

    @pytest.mark.asyncio
    async def test_timeout_closes_position(self, orchestrator):
        from config.risk_params import TIMEOUT_HOURS
        event = _make_event(asset="ETH")
        event.timestamp_utc = datetime.now(timezone.utc)
        signal = _make_signal(event, actionable=True)
        orchestrator.pipeline.process.return_value = signal
        orchestrator._get_mid_prices = lambda: {"ETH": 100.0}
        await orchestrator.handle_event(event)
        pos = orchestrator.paper_trader.open_positions[0]
        # Backdate entry so it looks like TIMEOUT_HOURS+1h old
        pos.entry_time_utc = datetime.now(timezone.utc) - timedelta(
            hours=TIMEOUT_HOURS + 1
        )
        # Price unchanged — TIMEOUT should fire before any ROE trigger
        event2 = _make_event(asset="BTC", new_regime=RegimeTier.MODERATE,
                             prev_regime=RegimeTier.MODERATE)
        signal2 = _make_signal(event2, actionable=False)
        orchestrator.pipeline.process.return_value = signal2
        await orchestrator.handle_event(event2)

        assert len(orchestrator.paper_trader.open_positions) == 0
        assert orchestrator.paper_trader.closed_positions[-1].exit_reason == "TIMEOUT"

    @pytest.mark.asyncio
    async def test_funding_fetch_failure_is_graceful(self, orchestrator):
        """Funding API failure must NOT crash the exit check loop."""
        event = _make_event(asset="ETH")
        event.timestamp_utc = datetime.now(timezone.utc)
        signal = _make_signal(event, actionable=True)
        orchestrator.pipeline.process.return_value = signal
        orchestrator._get_mid_prices = lambda: {"ETH": 100.0}

        # Force funding fetch to raise as if the HL API blew up
        def boom():
            raise RuntimeError("hyperliquid down")
        orchestrator._get_funding_rates = boom
        await orchestrator.handle_event(event)
        # Position opens cleanly despite funding being unavailable
        assert len(orchestrator.paper_trader.open_positions) == 1

        # A subsequent tick with failing funding fetch — still graceful.
        event2 = _make_event(asset="BTC", new_regime=RegimeTier.MODERATE,
                             prev_regime=RegimeTier.MODERATE)
        signal2 = _make_signal(event2, actionable=False)
        orchestrator.pipeline.process.return_value = signal2
        await orchestrator.handle_event(event2)
        # Still open — no crash, no accrual.
        assert len(orchestrator.paper_trader.open_positions) == 1
        pos = orchestrator.paper_trader.open_positions[0]
        assert pos.accumulated_funding_usd == 0.0

    @pytest.mark.asyncio
    async def test_funding_accrual_via_exit_tick(self, orchestrator):
        """Successful funding fetch → funding accrues on the exit tick."""
        from datetime import timedelta
        event = _make_event(asset="ETH")
        event.timestamp_utc = datetime.now(timezone.utc)
        signal = _make_signal(event, actionable=True)
        orchestrator.pipeline.process.return_value = signal
        orchestrator._get_mid_prices = lambda: {"ETH": 100.0}
        orchestrator._get_funding_rates = lambda: {}
        await orchestrator.handle_event(event)

        pos = orchestrator.paper_trader.open_positions[0]
        # Backdate last_funding_update by 2h to simulate prior tick age
        pos.last_funding_update = datetime.now(timezone.utc) - timedelta(hours=2)

        # Next tick: funding rate 0.005/hr on a SHORT → +$10 on $1000
        orchestrator._get_funding_rates = lambda: {"ETH": 0.005}
        event2 = _make_event(asset="BTC", new_regime=RegimeTier.MODERATE,
                             prev_regime=RegimeTier.MODERATE)
        signal2 = _make_signal(event2, actionable=False)
        orchestrator.pipeline.process.return_value = signal2
        await orchestrator.handle_event(event2)

        assert pos.accumulated_funding_usd == pytest.approx(10.0, rel=0.01)

    @pytest.mark.asyncio
    async def test_price_fetch_failure_is_graceful(self, orchestrator):
        """If mid-price fetch returns {}, exit check must skip silently."""
        event = _make_event(asset="ETH")
        event.timestamp_utc = datetime.now(timezone.utc)
        signal = _make_signal(event, actionable=True)
        orchestrator.pipeline.process.return_value = signal
        orchestrator._get_mid_prices = lambda: {"ETH": 100.0}
        await orchestrator.handle_event(event)

        # Simulate fetch failure
        orchestrator._get_mid_prices = lambda: {}
        event2 = _make_event(asset="BTC", new_regime=RegimeTier.MODERATE,
                             prev_regime=RegimeTier.MODERATE)
        signal2 = _make_signal(event2, actionable=False)
        orchestrator.pipeline.process.return_value = signal2
        await orchestrator.handle_event(event2)

        # Position still open; no crash.
        assert len(orchestrator.paper_trader.open_positions) == 1
