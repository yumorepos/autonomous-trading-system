"""D52 followup — tests for the four display-layer alerter changes.

Covers:
1. Cohort filter logic (post-cutoff, non-admin) on a mixed fixture.
2. Trade-close cohort tag ("cohort #N" vs "pre-cutoff tail").
3. Actionable signal score line normalized + raw + gate verdict.
4. Regime change directional callout for HIGH_FUNDING entry/exit, with
   passthrough for other transitions.

These are display-layer assertions only — no signal/scoring/sizing/exit
logic is exercised. Indirectly verifies that SAMPLE_CUTOFF_TS imports
cleanly from config.risk_params (item 1.5).
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.risk_params import EXECUTION_MIN_SCORE, SAMPLE_CUTOFF_TS
from src.models import (
    RegimeTier,
    RegimeTransitionEvent,
    ScoredSignal,
    SimulatedPosition,
)
from src.pipeline.live_orchestrator import (
    _CUTOFF_DT,
    _cohort_index,
    _cohort_metrics,
)
from scripts.trading_engine import _format_regime_alert


# --- helpers ---------------------------------------------------------------


def _pos(
    pid: str,
    asset: str,
    entry_offset_hours: float,
    pnl_usd: float,
    exit_reason: str = "TRAILING_STOP",
) -> SimulatedPosition:
    """Build a closed SimulatedPosition with entry_time relative to cutoff."""
    entry = _CUTOFF_DT + timedelta(hours=entry_offset_hours)
    return SimulatedPosition(
        position_id=pid,
        asset=asset,
        exchange="hyperliquid",
        entry_time_utc=entry,
        entry_regime=RegimeTier.HIGH_FUNDING,
        notional_usd=1000.0,
        entry_funding_apy=100.0,
        entry_price=1.0,
        direction="long",
        exit_time_utc=entry + timedelta(hours=2),
        exit_reason=exit_reason,
        pnl_usd=pnl_usd,
        is_open=False,
    )


def _is_admin(p: SimulatedPosition) -> bool:
    return (p.exit_reason or "").startswith("admin_")


# --- 1. cohort filter ------------------------------------------------------


def test_sample_cutoff_ts_parses():
    """The pinned constant must parse as a tz-aware ISO-8601 timestamp."""
    parsed = datetime.fromisoformat(SAMPLE_CUTOFF_TS)
    assert parsed.tzinfo is not None
    assert parsed == datetime(2026, 4, 22, 23, 6, 3, tzinfo=timezone.utc)


def test_cohort_metrics_filters_pre_and_admin():
    """Pre-cutoff entries and admin closes must be excluded from cohort."""
    closed = [
        _pos("pre1", "BLUR", -10.0, +50.0),       # pre-cutoff: drop
        _pos("pre2", "MET", -5.0, -20.0),          # pre-cutoff: drop
        _pos("post1", "APE", +1.0, +160.0),        # post-cutoff win
        _pos("post2", "HYPER", +2.0, -30.0),       # post-cutoff loss
        _pos("post3", "CHIP", +3.0, +20.0),        # post-cutoff win
        _pos("admin1", "ZETA", +4.0, -100.0,
             exit_reason="admin_legacy_cleanup"),  # admin, drop
    ]
    metrics = _cohort_metrics(closed, _is_admin)
    assert metrics["n"] == 3
    assert metrics["wr"] == pytest.approx(2 / 3)
    assert metrics["pnl"] == pytest.approx(150.0)
    # PF = 180 / 30 = 6.0
    assert metrics["pf"] == pytest.approx(6.0)
    assert metrics["best_asset"] == "APE"
    assert metrics["best_pnl"] == pytest.approx(160.0)
    assert metrics["worst_asset"] == "HYPER"
    assert metrics["worst_pnl"] == pytest.approx(-30.0)


def test_cohort_metrics_n_zero_when_no_post_cutoff():
    """No post-cutoff non-admin closes ⇒ n=0, no aggregates."""
    closed = [
        _pos("pre1", "BLUR", -10.0, +50.0),
        _pos("admin1", "ZETA", +4.0, -100.0,
             exit_reason="admin_legacy_cleanup"),
    ]
    metrics = _cohort_metrics(closed, _is_admin)
    assert metrics == {"n": 0}


def test_cohort_index_post_cutoff_is_one_indexed():
    """A post-cutoff trade gets a 1-indexed cohort number."""
    p1 = _pos("post1", "APE", +1.0, +50.0)
    p2 = _pos("post2", "HYPER", +2.0, -10.0)
    p3 = _pos("post3", "CHIP", +3.0, +20.0)
    closed = [p1, p2, p3]
    assert _cohort_index(closed, _is_admin, p1) == 1
    assert _cohort_index(closed, _is_admin, p2) == 2
    assert _cohort_index(closed, _is_admin, p3) == 3


def test_cohort_index_skips_admin_and_pre_cutoff():
    """Admin and pre-cutoff entries must not consume cohort numbers."""
    pre = _pos("pre1", "BLUR", -10.0, +50.0)
    admin = _pos("admin1", "ZETA", +0.5, -100.0,
                 exit_reason="admin_legacy_cleanup")
    p1 = _pos("post1", "APE", +1.0, +50.0)
    p2 = _pos("post2", "HYPER", +2.0, -10.0)
    closed = [pre, admin, p1, p2]
    assert _cohort_index(closed, _is_admin, p1) == 1
    assert _cohort_index(closed, _is_admin, p2) == 2


# --- 2. trade-close cohort tag --------------------------------------------


def _mock_config(tmp_path):
    return {
        "simulator": {"log_path": str(tmp_path / "trades.jsonl")},
        "telegram": {"bot_token": "fake", "chat_id": "123"},
        "history": {"signal_log_path": str(tmp_path / "signal.db")},
    }


def _build_orchestrator(tmp_path):
    from src.pipeline.live_orchestrator import LiveOrchestrator
    from src.simulator.paper_trader import PaperTrader

    with patch(
        "src.simulator.paper_trader.get_config",
        return_value=_mock_config(tmp_path),
    ):
        trader = PaperTrader(
            notional_per_trade=1000.0,
            max_open_positions=5,
            log_path=tmp_path / "trades.jsonl",
        )
    connector = MagicMock()
    connector.on_tick = MagicMock()
    pipeline = MagicMock()
    pipeline._send_telegram = MagicMock(return_value=True)
    orch = LiveOrchestrator(connector, pipeline, trader)
    return orch, trader, pipeline


def test_trade_close_emits_cohort_tag_for_post_cutoff(tmp_path):
    orch, trader, pipeline = _build_orchestrator(tmp_path)
    pos = _pos("post1", "APE", +1.0, +160.0)
    trader.closed_positions.append(pos)

    orch._send_trade_close_telegram(pos)

    pipeline._send_telegram.assert_called_once()
    msg = pipeline._send_telegram.call_args[0][0]
    assert "<b>TRADE CLOSED</b> · cohort #1" in msg
    assert "pre-cutoff tail" not in msg


def test_trade_close_emits_pre_cutoff_tail_for_pre_cutoff(tmp_path):
    orch, trader, pipeline = _build_orchestrator(tmp_path)
    pos = _pos("pre1", "BLUR", -10.0, +168.77)
    trader.closed_positions.append(pos)

    orch._send_trade_close_telegram(pos)

    msg = pipeline._send_telegram.call_args[0][0]
    assert "<b>TRADE CLOSED</b> · pre-cutoff tail" in msg
    assert "cohort #" not in msg


def test_trade_close_footer_has_lifetime_and_cohort_lines(tmp_path):
    orch, trader, pipeline = _build_orchestrator(tmp_path)
    p1 = _pos("post1", "APE", +1.0, +160.0)
    trader.closed_positions.extend([
        _pos("pre1", "BLUR", -10.0, +50.0),
        _pos("admin1", "ZETA", +0.5, -100.0,
             exit_reason="admin_legacy_cleanup"),
        p1,
    ])
    orch._send_trade_close_telegram(p1)
    msg = pipeline._send_telegram.call_args[0][0]
    assert "<b>Lifetime</b>" in msg
    assert "<b>Cohort</b> (n=1 since D46 cutoff 2026-04-22)" in msg


def test_trade_close_footer_cohort_n_zero_message(tmp_path):
    """Pre-cutoff close with no cohort members yet → 'no closes yet'."""
    orch, trader, pipeline = _build_orchestrator(tmp_path)
    pos = _pos("pre1", "BLUR", -10.0, +50.0)
    trader.closed_positions.append(pos)
    orch._send_trade_close_telegram(pos)
    msg = pipeline._send_telegram.call_args[0][0]
    assert "Cohort</b> (n=0 since D46 cutoff 2026-04-22): no closes yet" in msg


# --- 3. actionable signal score line --------------------------------------


def _make_signal(score: float) -> ScoredSignal:
    event = RegimeTransitionEvent(
        asset="ETH",
        exchange="hyperliquid",
        new_regime=RegimeTier.HIGH_FUNDING,
        previous_regime=RegimeTier.MODERATE,
        max_apy_annualized=150.0,
    )
    return ScoredSignal(
        event=event,
        composite_score=score,
        duration_survival_prob=0.99,
        expected_duration_min=60.0,
        liquidity_score=0.7,
        net_expected_apy=149.0,
        is_actionable=True,
        direction="long",
    )


@pytest.mark.parametrize("score,expected_norm,expected_verdict", [
    (65.0, "0.65", "REJECTED"),
    (70.0, "0.70", "ACCEPTED"),  # at-gate is ACCEPTED (>=)
    (92.0, "0.92", "ACCEPTED"),
])
def test_actionable_score_line_normalized_form(
    tmp_path, score, expected_norm, expected_verdict
):
    from src.pipeline.signal_filter import SignalFilterPipeline

    cfg = {
        "telegram": {"bot_token": "", "chat_id": "", "send_rejected": False},
        "history": {"signal_log_path": str(tmp_path / "signal.db")},
    }
    with patch("src.pipeline.signal_filter.get_config", return_value=cfg):
        pipeline = SignalFilterPipeline(
            scorer=MagicMock(),
            signal_log_path=tmp_path / "signal.db",
        )

    sig = _make_signal(score)
    alert = pipeline._format_actionable_alert(sig)
    assert f"<b>{expected_norm}</b> normalized" in alert
    assert f"({score:.0f}/100 raw)" in alert
    assert f"gate {EXECUTION_MIN_SCORE:.2f}: {expected_verdict}" in alert
    assert "Paper: opens regardless of gate" in alert


# --- 4. regime change directional callout ---------------------------------


def test_regime_alert_high_funding_entry():
    msg, level = _format_regime_alert(
        previous_regime="MODERATE",
        current_regime="HIGH_FUNDING",
        max_funding_apy=2.5,
        top_asset_name="BLUR",
        duration_str="4h 12m",
        fallback_top_info="UNUSED",
    )
    assert level == "WARN"
    assert msg.startswith("· HIGH_FUNDING entered\n")
    assert "Max funding: 250% APY (BLUR)" in msg
    assert "MODERATE lasted 4h 12m" in msg


def test_regime_alert_high_funding_exit():
    msg, level = _format_regime_alert(
        previous_regime="HIGH_FUNDING",
        current_regime="MODERATE",
        max_funding_apy=0.5,
        top_asset_name="ETH",
        duration_str="2h 30m",
        fallback_top_info="UNUSED",
    )
    assert level == "INFO"
    assert msg.startswith("· HIGH_FUNDING exited\n")
    assert "HIGH_FUNDING lasted 2h 30m" in msg


def test_regime_alert_other_transition_uses_legacy_format():
    """MODERATE → LOW_FUNDING is not a HIGH_FUNDING boundary; preserve format."""
    msg, level = _format_regime_alert(
        previous_regime="MODERATE",
        current_regime="LOW_FUNDING",
        max_funding_apy=0.1,
        top_asset_name="BTC",
        duration_str="1h 0m",
        fallback_top_info=" | x",
    )
    assert level == "WARN"
    assert msg == "REGIME CHANGE: MODERATE → LOW_FUNDING | x"
    assert "HIGH_FUNDING" not in msg


def test_regime_alert_no_previous_duration():
    """duration_str empty ⇒ no 'lasted' suffix in directional callouts."""
    msg, _ = _format_regime_alert(
        previous_regime="LOW_FUNDING",
        current_regime="HIGH_FUNDING",
        max_funding_apy=1.0,
        top_asset_name=None,
        duration_str="",
        fallback_top_info="UNUSED",
    )
    assert msg == "· HIGH_FUNDING entered\nMax funding: 100% APY"
