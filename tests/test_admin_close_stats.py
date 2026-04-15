"""Regression tests for admin-close exclusion from Gate 1 stats.

Positions closed with an ``admin_*`` exit_reason are one-time operational
interventions (e.g. correcting bug-direction legacy positions). They are
NOT strategy samples and MUST NOT contaminate win_rate, pnl aggregates,
or trade counts — Gate 1 GO/NO-GO needs a clean evidence base.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.models import RegimeTier, RegimeTransitionEvent, ScoredSignal
from src.simulator.paper_trader import PaperTrader


def _mock_config(tmp_path):
    return {
        "simulator": {"log_path": str(tmp_path / "trades.jsonl")},
    }


def _make_signal(asset="ETH"):
    event = RegimeTransitionEvent(
        asset=asset,
        exchange="hyperliquid",
        new_regime=RegimeTier.HIGH_FUNDING,
        previous_regime=RegimeTier.MODERATE,
        max_apy_annualized=150.0,
        timestamp_utc=datetime.now(timezone.utc),
    )
    return ScoredSignal(
        event=event,
        composite_score=80.0,
        duration_survival_prob=0.8,
        expected_duration_min=60.0,
        liquidity_score=0.7,
        net_expected_apy=149.0,
        is_actionable=True,
        direction="long",
    )


@pytest.fixture
def trader(tmp_path):
    with patch("src.simulator.paper_trader.get_config", return_value=_mock_config(tmp_path)):
        return PaperTrader(
            notional_per_trade=1000.0,
            max_open_positions=5,
            log_path=tmp_path / "trades.jsonl",
        )


def test_admin_close_excluded_from_stats(trader):
    """An admin_-prefixed exit_reason must not appear in any aggregate.

    Scenario: one legitimate closed winner + one admin-closed loser.
    Stats must show 1 closed position, 100% win rate, positive total PnL —
    as if the admin close never happened.
    """
    # Legitimate winner — TAKE_PROFIT close
    winner = trader.open_position(
        _make_signal(asset="ETH"), entry_price=100.0, direction="long",
    )
    winner.accumulated_funding_usd = 20.0  # +$20 funding income
    trader.close_position(winner, reason="TAKE_PROFIT", exit_price=105.0)

    # Bug-direction position — force into a loss, then admin-close
    loser = trader.open_position(
        _make_signal(asset="BTC"), entry_price=50000.0, direction="short",
    )
    loser.accumulated_funding_usd = -50.0  # -$50 from wrong-side funding
    trader.close_position(loser, reason="admin_direction_bug_correction", exit_price=50000.0)

    stats = trader.get_stats()

    # Only the winner counts
    assert stats.closed_positions == 1, "admin_ close must not count"
    assert stats.total_trades == 1
    assert stats.win_rate == 1.0
    assert stats.best_trade_pnl > 0
    # The -$50 bug loss must not contaminate total_pnl
    assert stats.total_pnl_usd > 0
    # Admin-close funding bleed must not pollute total_funding_collected_usd
    assert stats.total_funding_collected_usd == pytest.approx(20.0 + winner.accumulated_fees_usd * 0 + 0, abs=1.0)


def test_non_admin_close_still_counts(trader):
    """Sanity: a normal STOP_LOSS close IS included (exit_reason without admin_ prefix)."""
    pos = trader.open_position(
        _make_signal(asset="ETH"), entry_price=100.0, direction="long",
    )
    pos.accumulated_funding_usd = -5.0
    trader.close_position(pos, reason="STOP_LOSS", exit_price=85.0)

    stats = trader.get_stats()
    assert stats.closed_positions == 1
    assert stats.total_trades == 1
    assert stats.worst_trade_pnl < 0  # real loss recorded


def test_open_position_still_counts_despite_admin_closed_peer(trader):
    """Open positions always count toward exposure aggregates; admin-closed
    peers are simply absent. Guards against over-filtering."""
    # Admin-close one position
    p1 = trader.open_position(
        _make_signal(asset="ETH"), entry_price=100.0, direction="long",
    )
    trader.close_position(p1, reason="admin_direction_bug_correction", exit_price=100.0)

    # Open another, leave it open
    p2 = trader.open_position(
        _make_signal(asset="BTC"), entry_price=50000.0, direction="long",
    )
    p2.accumulated_funding_usd = 3.0

    stats = trader.get_stats()
    assert stats.open_positions == 1
    assert stats.closed_positions == 0  # admin close excluded
    assert stats.total_trades == 1      # open counts, admin doesn't
    assert stats.total_funding_collected_usd == pytest.approx(3.0, abs=0.01)
