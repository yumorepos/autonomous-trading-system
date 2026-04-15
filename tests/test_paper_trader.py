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
        pos = trader.open_position(signal, entry_price=100.0)
        assert pos is not None
        assert pos.asset == "ETH"
        assert pos.exchange == "hyperliquid"
        assert pos.notional_usd == 1000.0
        assert pos.is_open is True
        assert pos.accumulated_fees_usd > 0  # entry fees applied

    def test_entry_fees_computed(self, trader):
        signal = _make_signal()
        pos = trader.open_position(signal, entry_price=100.0)
        # 4 bps fee + 2 bps slippage = 6 bps on $1000 = $0.60
        assert abs(pos.accumulated_fees_usd - 0.60) < 0.01

    def test_respects_max_positions(self, trader):
        for asset in ["ETH", "BTC", "SOL"]:
            pos = trader.open_position(_make_signal(asset=asset), entry_price=100.0)
            assert pos is not None

        # 4th should be rejected (max=3)
        pos = trader.open_position(_make_signal(asset="AVAX"), entry_price=100.0)
        assert pos is None

    def test_no_duplicate_asset_exchange(self, trader):
        trader.open_position(_make_signal(asset="ETH"), entry_price=100.0)
        pos = trader.open_position(_make_signal(asset="ETH"), entry_price=100.0)
        assert pos is None

    def test_same_asset_different_exchange_allowed(self, trader):
        trader.open_position(_make_signal(asset="ETH", exchange="hyperliquid"), entry_price=100.0)
        pos = trader.open_position(_make_signal(asset="ETH", exchange="binance"), entry_price=100.0)
        assert pos is not None

    def test_rejects_none_entry_price(self, trader):
        """Guard: entry_price=None must raise ValueError, not silently open a
        ghost position that gets stale_cleanup'd on restart. See Apr 2026
        incident where 3 YZY signals were lost this way during peak funding.
        """
        with pytest.raises(ValueError, match="entry_price"):
            trader.open_position(_make_signal(), entry_price=None)  # type: ignore[arg-type]
        assert len(trader.open_positions) == 0

    def test_rejects_zero_entry_price(self, trader):
        with pytest.raises(ValueError, match="entry_price"):
            trader.open_position(_make_signal(), entry_price=0.0)
        assert len(trader.open_positions) == 0

    def test_rejects_negative_entry_price(self, trader):
        with pytest.raises(ValueError, match="entry_price"):
            trader.open_position(_make_signal(), entry_price=-1.0)
        assert len(trader.open_positions) == 0


class TestClosePosition:
    def test_close_position(self, trader):
        signal = _make_signal()
        pos = trader.open_position(signal, entry_price=100.0)
        entry_fees = pos.accumulated_fees_usd
        closed = trader.close_position(pos, reason="regime_exit")

        assert closed.is_open is False
        assert closed.exit_reason == "regime_exit"
        assert closed.exit_time_utc is not None
        # Exit fees added on top of entry fees
        assert closed.accumulated_fees_usd > entry_fees

    def test_close_positions_for_asset(self, trader):
        trader.open_position(_make_signal(asset="ETH"), entry_price=100.0)
        trader.open_position(_make_signal(asset="BTC"), entry_price=100.0)

        closed = trader.close_positions_for_asset("ETH", reason="test")
        assert len(closed) == 1
        assert closed[0].asset == "ETH"
        assert len(trader.open_positions) == 1

    def test_close_already_closed_is_noop(self, trader):
        pos = trader.open_position(_make_signal(), entry_price=100.0)
        trader.close_position(pos)
        # Close again — should be a no-op
        result = trader.close_position(pos)
        assert result.is_open is False


class TestFundingAccrual:
    def test_accrue_funding(self, trader):
        trader.open_position(_make_signal(asset="ETH", exchange="hyperliquid"), entry_price=100.0)
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
        trader.open_position(_make_signal(asset="ETH", exchange="hyperliquid"), entry_price=100.0)
        trader.open_position(_make_signal(asset="BTC", exchange="binance"), entry_price=100.0)

        trader.accrue_funding("ETH", "hyperliquid", 100.0)
        eth_pos = [p for p in trader.open_positions if p.asset == "ETH"][0]
        btc_pos = [p for p in trader.open_positions if p.asset == "BTC"][0]

        assert eth_pos.funding_payments == 1
        assert btc_pos.funding_payments == 0


class TestHourlyFundingAccrual:
    def test_short_receives_positive_funding(self, trader):
        """SHORT × 4 hours × 0.01/hr funding on $1000 = +$40."""
        from datetime import timedelta
        pos = trader.open_position(
            _make_signal(asset="ETH"), entry_price=100.0, direction="short",
        )
        # Backdate last_funding_update by exactly 4 hours
        now = datetime.now(timezone.utc)
        pos.last_funding_update = now - timedelta(hours=4)
        trader.accrue_hourly_funding({"ETH": 0.01}, now=now)

        assert pos.accumulated_funding_usd == pytest.approx(40.0)
        assert pos.funding_payments == 1
        assert pos.last_funding_update == now

    def test_long_pays_positive_funding(self, trader):
        """LONG with positive funding → negative cumulative funding."""
        from datetime import timedelta
        pos = trader.open_position(
            _make_signal(asset="ETH"), entry_price=100.0, direction="long",
        )
        now = datetime.now(timezone.utc)
        pos.last_funding_update = now - timedelta(hours=4)
        trader.accrue_hourly_funding({"ETH": 0.01}, now=now)

        assert pos.accumulated_funding_usd == pytest.approx(-40.0)

    def test_close_includes_funding_in_pnl(self, trader):
        """Realized PnL on close must include accrued funding."""
        from datetime import timedelta
        pos = trader.open_position(
            _make_signal(asset="ETH"), entry_price=100.0, direction="short",
        )
        now = datetime.now(timezone.utc)
        pos.last_funding_update = now - timedelta(hours=2)
        trader.accrue_hourly_funding({"ETH": 0.005}, now=now)
        # +$10 funding; flat price → price_pnl = 0
        assert pos.accumulated_funding_usd == pytest.approx(10.0)

        fees_before_exit = pos.accumulated_fees_usd
        closed = trader.close_position(pos, reason="TEST", exit_price=100.0)
        # net_pnl = 0 (price) + 10 (funding) - fees
        expected = 0.0 + 10.0 - closed.accumulated_fees_usd
        assert closed.pnl_usd == pytest.approx(expected)
        assert closed.pnl_usd > -fees_before_exit  # funding outweighs exit fees

    def test_accrue_skipped_when_asset_missing(self, trader):
        """Asset not in funding_rates dict → position untouched."""
        pos = trader.open_position(
            _make_signal(asset="ETH"), entry_price=100.0, direction="short",
        )
        trader.accrue_hourly_funding({"BTC": 0.01})
        assert pos.accumulated_funding_usd == 0.0
        assert pos.funding_payments == 0

    def test_accrue_noop_on_empty_rates(self, trader):
        """Empty funding_rates (e.g. API failure) → no crash, no change."""
        pos = trader.open_position(
            _make_signal(asset="ETH"), entry_price=100.0, direction="short",
        )
        trader.accrue_hourly_funding({})
        assert pos.accumulated_funding_usd == 0.0


class TestStats:
    def test_empty_stats(self, trader):
        stats = trader.get_stats()
        assert stats.total_trades == 0
        assert stats.total_pnl_usd == 0.0

    def test_stats_with_open_and_closed(self, trader):
        trader.open_position(_make_signal(asset="ETH"), entry_price=100.0)
        pos_btc = trader.open_position(_make_signal(asset="BTC"), entry_price=100.0)
        trader.accrue_funding("BTC", "hyperliquid", 200.0, interval_hours=8.0)
        trader.close_position(pos_btc, reason="test")

        stats = trader.get_stats()
        assert stats.total_trades == 2
        assert stats.open_positions == 1
        assert stats.closed_positions == 1
        assert stats.total_funding_collected_usd > 0

    def test_trade_logging(self, trader):
        pos = trader.open_position(_make_signal(), entry_price=100.0)
        trader.close_position(pos)

        lines = trader.log_path.read_text().strip().split("\n")
        assert len(lines) == 2  # OPEN + CLOSE
        open_rec = json.loads(lines[0])
        assert open_rec["action"] == "OPEN"
        close_rec = json.loads(lines[1])
        assert close_rec["action"] == "CLOSE"
        assert close_rec["exit_reason"] == "regime_change"



class TestDirectionalROE:
    def test_short_roe_sign(self, trader):
        """Short: profit when price falls."""
        pos = trader.open_position(_make_signal(), entry_price=100.0, direction="short")
        assert pos.entry_price == 100.0
        assert pos.direction == "short"
        assert pos.compute_roe(90.0) == pytest.approx(0.10)
        assert pos.compute_roe(110.0) == pytest.approx(-0.10)

    def test_long_roe_sign(self, trader):
        pos = trader.open_position(_make_signal(), entry_price=100.0, direction="long")
        assert pos.compute_roe(110.0) == pytest.approx(0.10)
        assert pos.compute_roe(90.0) == pytest.approx(-0.10)

    def test_close_with_exit_price_records_price_pnl(self, trader):
        pos = trader.open_position(_make_signal(), entry_price=100.0, direction="short")
        closed = trader.close_position(pos, reason="TEST", exit_price=80.0)
        # 20% favorable move on $1000 → +$200 price PnL
        assert closed.price_pnl_usd == pytest.approx(200.0)
        assert closed.exit_price == 80.0


class TestCheckExits:
    def test_stop_loss(self, trader):
        from config.risk_params import STOP_LOSS_ROE
        pos = trader.open_position(_make_signal(), entry_price=100.0, direction="short")
        pos.entry_time_utc = datetime.now(timezone.utc)
        # Adverse move past SL threshold
        bad = 100.0 * (1 + abs(STOP_LOSS_ROE) + 0.01)
        closed = trader.check_exits({"ETH": bad})
        assert len(closed) == 1
        assert closed[0].exit_reason == "STOP_LOSS"

    def test_take_profit(self, trader):
        from config.risk_params import TAKE_PROFIT_ROE
        pos = trader.open_position(_make_signal(), entry_price=100.0, direction="short")
        pos.entry_time_utc = datetime.now(timezone.utc)
        # Favorable move past TP threshold
        good = 100.0 * (1 - TAKE_PROFIT_ROE - 0.01)
        closed = trader.check_exits({"ETH": good})
        assert len(closed) == 1
        assert closed[0].exit_reason == "TAKE_PROFIT"

    def test_timeout(self, trader):
        from datetime import timedelta
        from config.risk_params import TIMEOUT_HOURS
        pos = trader.open_position(_make_signal(), entry_price=100.0, direction="short")
        pos.entry_time_utc = datetime.now(timezone.utc) - timedelta(hours=TIMEOUT_HOURS + 1)
        closed = trader.check_exits({"ETH": 100.0})
        assert len(closed) == 1
        assert closed[0].exit_reason == "TIMEOUT"

    def test_trailing_stop(self, trader):
        from config.risk_params import TRAILING_STOP_ACTIVATE, TRAILING_STOP_DISTANCE, TAKE_PROFIT_ROE
        pos = trader.open_position(_make_signal(), entry_price=100.0, direction="short")
        pos.entry_time_utc = datetime.now(timezone.utc)
        # First push ROE above activation but below TP
        favorable_roe = min(TRAILING_STOP_ACTIVATE + 0.01, TAKE_PROFIT_ROE - 0.01)
        peak_price = 100.0 * (1 - favorable_roe)
        trader.check_exits({"ETH": peak_price})
        assert pos.peak_roe >= TRAILING_STOP_ACTIVATE
        # Now price retraces by more than TRAILING_STOP_DISTANCE
        retrace_roe = favorable_roe - TRAILING_STOP_DISTANCE - 0.005
        retrace_price = 100.0 * (1 - retrace_roe)
        closed = trader.check_exits({"ETH": retrace_price})
        assert len(closed) == 1
        assert closed[0].exit_reason == "TRAILING_STOP"

    def test_no_price_skips(self, trader):
        """Missing price for an asset must not crash or close the position."""
        trader.open_position(_make_signal(asset="ETH"), entry_price=100.0, direction="short")
        closed = trader.check_exits({})  # no prices
        assert closed == []
        assert len(trader.open_positions) == 1

    def test_legacy_unpriced_position_skipped(self, trader):
        """Legacy positions with entry_price=0 (from stale JSONL on disk,
        before the open-time guard was added) are still tolerated by
        check_exits — it skips them rather than crashing. New opens can
        no longer produce these (open_position now raises on entry_price<=0),
        so we synthesize the legacy state directly.
        """
        # Bypass open_position guard to simulate a legacy-on-disk position
        pos = trader.open_position(
            _make_signal(asset="ETH"), entry_price=100.0, direction="short",
        )
        pos.entry_price = 0.0  # mutate to legacy shape
        closed = trader.check_exits({"ETH": 9999.0})
        assert closed == []
        assert len(trader.open_positions) == 1
