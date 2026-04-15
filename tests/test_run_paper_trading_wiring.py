"""Tests for scripts/run_paper_trading.py Executor wiring.

Regression guard against the silent misconfiguration where
`LiveOrchestrator(connector, pipeline, paper_trader)` was called without
the `executor=` kwarg, leaving self.executor=None and suppressing all
execution telemetry — 9 actionable signals in 24h produced zero DRY_RUN
log lines before this was fixed.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.execution.executor import Executor
from src.models import RegimeTier, RegimeTransitionEvent, ScoredSignal


# ---------------------------------------------------------------------------
# 1. build_executor() constructs a usable Executor in dry-run mode
# ---------------------------------------------------------------------------

def test_build_executor_returns_dry_run_executor(monkeypatch):
    """build_executor() returns a properly configured dry-run Executor.

    The critical invariant: enabled=True and dry_run=True match config flags.
    hl_exchange must be None (second safety lock — live execution refused
    even if DRY_RUN were flipped).
    """
    import scripts.run_paper_trading as rpt

    fake_info = MagicMock(name="FakeInfo")
    # Patch Info at the import site inside build_executor()
    with patch("hyperliquid.info.Info", return_value=fake_info) as info_cls:
        monkeypatch.setenv("HL_WALLET_ADDRESS", "0xabc")
        executor = rpt.build_executor()

    assert executor is not None, "build_executor() returned None in happy path"
    assert isinstance(executor, Executor)
    assert executor.enabled is True, "EXECUTION_ENABLED config must propagate"
    assert executor.dry_run is True, "EXECUTION_DRY_RUN config must propagate"
    assert executor.hl_exchange is None, (
        "hl_exchange MUST be None — second safety lock against accidental "
        "live execution even if DRY_RUN is flipped"
    )
    assert executor.hl_info is fake_info
    assert executor.hl_address == "0xabc"
    info_cls.assert_called_once_with(skip_ws=True, timeout=10)


def test_build_executor_without_wallet_address_still_constructs(monkeypatch):
    """Missing HL_WALLET_ADDRESS must not crash construction.

    The balance gate will reject every signal, but we still get the
    wiring + structured rejection logs — which is the whole point of this
    change vs the pre-fix silent no-op.
    """
    import scripts.run_paper_trading as rpt

    monkeypatch.delenv("HL_WALLET_ADDRESS", raising=False)
    with patch("hyperliquid.info.Info", return_value=MagicMock()):
        executor = rpt.build_executor()

    assert executor is not None
    assert executor.hl_address is None


def test_build_executor_returns_none_when_sdk_unimportable(monkeypatch):
    """If the hyperliquid SDK can't import, return None — do not crash.

    Mirrors the existing intermittent-ImportError pattern documented in
    system_state.md (ghost positions from `No module named 'hyperliquid'`).
    The service must stay up and paper-trade even if execution is
    unavailable.
    """
    import scripts.run_paper_trading as rpt

    # Force ImportError at the `from hyperliquid.info import Info` line
    # by injecting a shim module that raises on the submodule import.
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **kw):
        if name == "hyperliquid.info":
            raise ImportError("simulated SDK missing")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    executor = rpt.build_executor()
    assert executor is None


# ---------------------------------------------------------------------------
# 2. Executor without HL credentials still emits structured rejection logs
# ---------------------------------------------------------------------------

def _make_actionable_signal() -> ScoredSignal:
    event = RegimeTransitionEvent(
        asset="YZY",
        exchange="hyperliquid",
        new_regime=RegimeTier.HIGH_FUNDING,
        previous_regime=RegimeTier.MODERATE,
        max_apy_annualized=150.0,
        timestamp_utc=datetime.now(timezone.utc),
    )
    return ScoredSignal(
        event=event,
        composite_score=85.0,       # above 0.7 threshold
        duration_survival_prob=0.9,
        expected_duration_min=60.0,
        liquidity_score=0.8,
        net_expected_apy=145.0,
        is_actionable=True,
    )


def test_executor_without_credentials_rejects_on_balance_gate():
    """Proves the wiring produces useful telemetry even with no HL creds.

    With hl_info=None, the balance query returns 0.0 and Gate 9 rejects.
    The rejection carries a structured reason string and flows into the
    execution log — exactly the evidence Gate 1 audits against.
    """
    executor = Executor(
        hl_exchange=None, hl_info=None, hl_address=None, telegram_send_fn=None,
    )
    assert executor.enabled is True
    assert executor.dry_run is True

    signal = _make_actionable_signal()
    result = executor.execute(signal)

    assert result.action == "rejected"
    assert "Balance" in result.reason, (
        f"Expected balance-gate rejection, got: {result.reason!r}"
    )
    assert result.signal_score == 85.0
