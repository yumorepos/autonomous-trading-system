"""Regression tests for the direction-sign fix.

The live engine only emits NEGATIVE-funding signals:
    scripts/regime_detector.py:163-165 — filters `if funding < 0`
    scripts/trading_engine.py:806-807  — filters `if funding >= 0: continue`

The regime_updated JSONL events therefore always reference an asset where
Hyperliquid funding is negative, and the earning side is LONG (longs
collect when funding is negative; shorts pay).

Before this fix, CompositeSignalScorer hardcoded direction="short" on
every ScoredSignal and LiveOrchestrator passed a hardcoded direction
kwarg too. The result: every paper/real trade went the WRONG way —
shorts on negative-funding assets pay funding instead of collecting it,
mirror-imaging the backtest's 82.6% win rate into ~17.4%.

These tests lock in:
  1. ScoredSignal default is "long"
  2. CompositeSignalScorer emits direction="long"
  3. LiveOrchestrator opens a LONG paper position from that signal
  4. LONG on a negative funding rate produces POSITIVE funding income
  5. All four (direction × rate-sign) combinations accrue with the
     correct sign.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.models import (
    RegimeTier,
    RegimeTransitionEvent,
    ScoredSignal,
    SimulatedPosition,
)


# ---------------------------------------------------------------------------
# 1. ScoredSignal model default
# ---------------------------------------------------------------------------


def test_scored_signal_default_direction_is_long():
    """A freshly constructed ScoredSignal that omits direction must
    default to LONG. The engine only emits negative-funding signals,
    so LONG is the earning side.
    """
    event = RegimeTransitionEvent(
        asset="ETH",
        exchange="hyperliquid",
        new_regime=RegimeTier.HIGH_FUNDING,
        previous_regime=RegimeTier.MODERATE,
        max_apy_annualized=150.0,
    )
    signal = ScoredSignal(
        event=event,
        composite_score=80.0,
        duration_survival_prob=0.8,
        expected_duration_min=60.0,
        liquidity_score=0.7,
        net_expected_apy=140.0,
        is_actionable=True,
    )
    assert signal.direction == "long"


# ---------------------------------------------------------------------------
# 2. CompositeSignalScorer emits direction="long"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_composite_scorer_emits_long_direction():
    """CompositeSignalScorer must stamp direction="long" on every
    ScoredSignal — the engine upstream only emits negative-funding
    assets, so LONG is the earning side.
    """
    from src.scoring.composite_scorer import CompositeSignalScorer

    cfg = {
        "scoring_weights": {
            "net_apy": 0.4,
            "duration_confidence": 0.3,
            "liquidity": 0.2,
            "cross_exchange_spread": 0.1,
        },
        "exchanges": {"hyperliquid": {
            "fee_rate_round_trip": 0.0008,
            "funding_interval_hours": 1,
        }},
        "duration_filter": {"min_duration_minutes": 15, "min_survival_probability": 0.5},
        "liquidity_filter": {"min_liquidity_score": 0.4},
        "min_net_apy_annualized": 50.0,
        "min_composite_score": 40.0,
    }

    duration_pred = MagicMock()
    duration_pred.predict.return_value = MagicMock(
        survival_probability=0.9,
        expected_duration_min=60.0,
    )
    liq_scorer = MagicMock()
    liq_scorer.score = AsyncMock(return_value=0.8)

    with patch("src.scoring.composite_scorer.get_config", return_value=cfg):
        scorer = CompositeSignalScorer(
            duration_predictor=duration_pred,
            liquidity_scorer=liq_scorer,
            adapters={},
        )
        event = RegimeTransitionEvent(
            asset="YZY",
            exchange="hyperliquid",
            new_regime=RegimeTier.HIGH_FUNDING,
            previous_regime=RegimeTier.MODERATE,
            max_apy_annualized=200.0,
        )
        signal = await scorer.score(event)

    assert signal.direction == "long", (
        "scorer must emit 'long' — engine only emits negative-funding "
        "signals, on which LONG is the earning side"
    )


# ---------------------------------------------------------------------------
# 3. LiveOrchestrator opens a LONG paper position
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_opens_long_from_actionable_signal(tmp_path):
    """End-to-end: an actionable ScoredSignal with direction="long"
    must result in a paper position opened with direction="long".
    """
    from src.pipeline.live_orchestrator import LiveOrchestrator
    from src.simulator.paper_trader import PaperTrader

    connector = MagicMock()
    pipeline = MagicMock()
    pipeline.process = AsyncMock()

    mock_cfg = {
        "simulator": {"log_path": str(tmp_path / "trades.jsonl")},
        "regime_thresholds": {"low_funding_max_apy": 20, "moderate_max_apy": 80},
        "exchanges": {},
        "telegram": {"bot_token": "", "chat_id": ""},
        "history": {"signal_log_path": str(tmp_path / "signal_log.db")},
    }
    with patch("src.simulator.paper_trader.get_config", return_value=mock_cfg):
        paper_trader = PaperTrader(
            notional_per_trade=1000.0,
            max_open_positions=5,
            log_path=tmp_path / "trades.jsonl",
        )

    orch = LiveOrchestrator(connector, pipeline, paper_trader)
    orch._get_mid_prices = lambda: {"YZY": 1.5}
    orch._get_funding_rates = lambda: {}

    event = RegimeTransitionEvent(
        asset="YZY",
        exchange="hyperliquid",
        new_regime=RegimeTier.HIGH_FUNDING,
        previous_regime=RegimeTier.MODERATE,
        max_apy_annualized=900.0,
        timestamp_utc=datetime.now(timezone.utc),
    )
    signal = ScoredSignal(
        event=event,
        composite_score=85.0,
        duration_survival_prob=0.8,
        expected_duration_min=60.0,
        liquidity_score=0.7,
        net_expected_apy=899.0,
        is_actionable=True,
        # explicit — also tests the orchestrator reads signal.direction
        direction="long",
    )
    pipeline.process.return_value = signal

    await orch.handle_event(event)

    assert len(paper_trader.open_positions) == 1
    pos = paper_trader.open_positions[0]
    assert pos.direction == "long"
    assert pos.asset == "YZY"
    assert pos.entry_price == 1.5


# ---------------------------------------------------------------------------
# 4 + 5. Funding accrual sign — all four combinations.
# ---------------------------------------------------------------------------


def _make_position(direction: str) -> SimulatedPosition:
    return SimulatedPosition(
        position_id="test",
        asset="ETH",
        exchange="hyperliquid",
        entry_time_utc=datetime.now(timezone.utc) - timedelta(hours=2),
        entry_regime=RegimeTier.HIGH_FUNDING,
        notional_usd=1000.0,
        entry_funding_apy=150.0,
        entry_price=100.0,
        direction=direction,
        last_funding_update=datetime.now(timezone.utc) - timedelta(hours=2),
    )


def _accrue(trader, pos, rate: float):
    """Run one 2-hour accrual tick at the given per-hour rate."""
    trader.positions = [pos]
    trader.accrue_hourly_funding({pos.asset: rate})


@pytest.fixture
def trader(tmp_path):
    from src.simulator.paper_trader import PaperTrader
    mock_cfg = {
        "simulator": {"log_path": str(tmp_path / "trades.jsonl")},
        "regime_thresholds": {"low_funding_max_apy": 20, "moderate_max_apy": 80},
        "exchanges": {},
        "telegram": {"bot_token": "", "chat_id": ""},
        "history": {"signal_log_path": str(tmp_path / "signal_log.db")},
    }
    with patch("src.simulator.paper_trader.get_config", return_value=mock_cfg):
        return PaperTrader(
            notional_per_trade=1000.0,
            max_open_positions=5,
            log_path=tmp_path / "trades.jsonl",
        )


def test_funding_long_on_negative_rate_is_positive_income(trader):
    """The canonical live scenario: LONG position on a negative-funding
    asset. Longs collect when funding is negative, so accrued funding
    MUST be positive (income).

    This is the regression test for the actual production bug: before
    the fix, the engine emitted negative-funding signals but the
    orchestrator opened SHORTs on them, and every exit_check tick logged
    a NEGATIVE funding_usd — a slow bleed. With direction="long" the
    sign flips to income.
    """
    pos = _make_position(direction="long")
    _accrue(trader, pos, rate=-0.005)  # -0.5%/hr negative funding
    # sign = -1 (long), payment = -1 * -0.005 * 1000 * 2 = +$10
    assert pos.accumulated_funding_usd == pytest.approx(10.0, rel=0.01)
    assert pos.accumulated_funding_usd > 0


def test_funding_short_on_positive_rate_is_positive_income(trader):
    """Sanity check the other earning side: SHORT on positive funding
    also collects. (Not the live scenario, but the backtester uses this
    convention for HIGH_FUNDING regime.)
    """
    pos = _make_position(direction="short")
    _accrue(trader, pos, rate=+0.005)  # +0.5%/hr positive funding
    # sign = +1 (short), payment = +1 * +0.005 * 1000 * 2 = +$10
    assert pos.accumulated_funding_usd == pytest.approx(10.0, rel=0.01)
    assert pos.accumulated_funding_usd > 0


def test_funding_long_on_positive_rate_is_negative_expense(trader):
    """Wrong-side check: LONG on positive funding — longs PAY."""
    pos = _make_position(direction="long")
    _accrue(trader, pos, rate=+0.005)
    # sign = -1 (long), payment = -1 * +0.005 * 1000 * 2 = -$10
    assert pos.accumulated_funding_usd == pytest.approx(-10.0, rel=0.01)
    assert pos.accumulated_funding_usd < 0


def test_funding_short_on_negative_rate_is_negative_expense(trader):
    """The production-bug scenario: SHORT on negative funding —
    shorts PAY. Before the direction-sign fix, this was the state
    the orchestrator was putting every live position into.
    """
    pos = _make_position(direction="short")
    _accrue(trader, pos, rate=-0.005)
    # sign = +1 (short), payment = +1 * -0.005 * 1000 * 2 = -$10
    assert pos.accumulated_funding_usd == pytest.approx(-10.0, rel=0.01)
    assert pos.accumulated_funding_usd < 0
