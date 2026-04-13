"""Tests for PaperTrader — simulated position management."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.models import (
    RegimeTier,
    RegimeTransitionEvent,
    ScoredSignal,
    SimulatedPosition,
)
from src.simulator.paper_trader import PaperTrader


def _mock_config():
    return {
        "simulator": {"log_path": "data/paper_trades.jsonl"},
        "regime_thresholds": {"low_funding_max_apy": 20, "moderate_max_apy": 80},
        "exchanges": {},
        "telegram": {"bot_token": "", "chat_id": ""},
        "history": {"signal_log_path": "data/signal_log.db"},
    }


def _make_signal(asset="ETH", exchange="hyperliquid", apy=150.0, score=72.0) -> ScoredSignal:
    event = RegimeTransitionEvent(
        asset=asset,
        exchange=exchange,
        new_regime=RegimeTier.HIGH_FUNDING,
        previous_regime=RegimeTier.MODERATE,
        max_apy_annualized=apy,
        timestamp_utc=datetime(2026, 4, 13, 12, 0, tzinfo=timezone.utc),
    )
    return ScoredSignal(
        event=event,
        composite_score=score,
        duration_survival_prob=0.75,
        expected_duration_min=45.0,
        liquidity_score=0.6,
        net_expected_apy=apy - 0.08,
        is_actionable=True,
    )


@pytest.fixture
def trader(tmp_path):
    log_path = tmp_path / "trades.jsonl"
    with patch("src.simulator.paper_trader.get_config", return_value=_mock_config()):
        return PaperTrader(
            notional_per_trade=1000.0,
            max_open_positions=3,
            entry_fee_bps=4.0,
            exit_fee_bps=4.0,
            slippage_bps=2.0,
            log_path=log_path,
        )


class TestOpenPosition:
    def test_opens_position(self, trader):
        signal = _make_signal()
        pos = trader.open_position(signal)
        assert pos is not None
        assert pos.asset == "ETH"
        assert pos.exchange == "hyperliquid"
        assert pos.notional_usd == 1000.0
        assert pos.is_open is True
        assert pos.accumulated_fees_usd > 0  # entry fees applied

    def test_entry_fees_computed(self, trader):
        signal = _make_signal()
        pos = trader.open_position(signal)
        # 4 bps fee + 2 bps slippage = 6 bps on $1000 = $0.60
        assert abs(pos.accumulated_fees_usd - 0.60) < 0.01

    def test_respects_max_positions(self, trader):
        for asset in ["ETH", "BTC", "SOL"]:
            pos = trader.open_position(_make_signal(asset=asset))
            assert pos is not None

        # 4th should be rejected (max=3)
        pos = trader.open_position(_make_signal(asset="AVAX"))
        assert pos is None

    def test_no_duplicate_asset_exchange(self, trader):
        trader.open_position(_make_signal(asset="ETH"))
        pos = trader.open_position(_make_signal(asset="ETH"))
        assert pos is None

    def test_same_asset_different_exchange_allowed(self, trader):
        trader.open_position(_make_signal(asset="ETH", exchange="hyperliquid"))
        pos = trader.open_position(_make_signal(asset="ETH", exchange="binance"))
        assert pos is not None


class TestClosePosition:
    def test_close_position(self, trader):
        signal = _make_signal()
        pos = trader.open_position(signal)
        entry_fees = pos.accumulated_fees_usd
        closed = trader.close_position(pos, reason="regime_exit")

        assert closed.is_open is False
        assert closed.exit_reason == "regime_exit"
        assert closed.exit_time_utc is not None
        # Exit fees added on top of entry fees
        assert closed.accumulated_fees_usd > entry_fees

    def test_close_positions_for_asset(self, trader):
        trader.open_position(_make_signal(asset="ETH"))
        trader.open_position(_make_signal(asset="BTC"))

        closed = trader.close_positions_for_asset("ETH", reason="test")
        assert len(closed) == 1
        assert closed[0].asset == "ETH"
        assert len(trader.open_positions) == 1

    def test_close_already_closed_is_noop(self, trader):
        pos = trader.open_position(_make_signal())
        trader.close_position(pos)
        # Close again — should be a no-op
        result = trader.close_position(pos)
        assert result.is_open is False


class TestFundingAccrual:
    def test_accrue_funding(self, trader):
        trader.open_position(_make_signal(asset="ETH", exchange="hyperliquid"))
        trader.accrue_funding("ETH", "hyperliquid", 150.0, interval_hours=1.0)

        pos = trader.open_positions[0]
        assert pos.funding_payments == 1
        assert pos.accumulated_funding_usd > 0

        # 150% APY, 1h interval → 365*24 = 8760 intervals/year
        # per_interval = 1.50 / 8760 ≈ 0.000171
        # payment = 1000 * 0.000171 ≈ $0.171
        expected = 1000.0 * (1.50 / 8760)
        assert abs(pos.accumulated_funding_usd - expected) < 0.001

    def test_accrue_only_matches_asset_exchange(self, trader):
        trader.open_position(_make_signal(asset="ETH", exchange="hyperliquid"))
        trader.open_position(_make_signal(asset="BTC", exchange="binance"))

        trader.accrue_funding("ETH", "hyperliquid", 100.0)
        eth_pos = [p for p in trader.open_positions if p.asset == "ETH"][0]
        btc_pos = [p for p in trader.open_positions if p.asset == "BTC"][0]

        assert eth_pos.funding_payments == 1
        assert btc_pos.funding_payments == 0


class TestStats:
    def test_empty_stats(self, trader):
        stats = trader.get_stats()
        assert stats.total_trades == 0
        assert stats.total_pnl_usd == 0.0

    def test_stats_with_open_and_closed(self, trader):
        trader.open_position(_make_signal(asset="ETH"))
        pos_btc = trader.open_position(_make_signal(asset="BTC"))
        trader.accrue_funding("BTC", "hyperliquid", 200.0, interval_hours=8.0)
        trader.close_position(pos_btc, reason="test")

        stats = trader.get_stats()
        assert stats.total_trades == 2
        assert stats.open_positions == 1
        assert stats.closed_positions == 1
        assert stats.total_funding_collected_usd > 0

    def test_trade_logging(self, trader):
        pos = trader.open_position(_make_signal())
        trader.close_position(pos)

        lines = trader.log_path.read_text().strip().split("\n")
        assert len(lines) == 2  # OPEN + CLOSE
        open_rec = json.loads(lines[0])
        assert open_rec["action"] == "OPEN"
        close_rec = json.loads(lines[1])
        assert close_rec["action"] == "CLOSE"
        assert close_rec["exit_reason"] == "regime_change"
