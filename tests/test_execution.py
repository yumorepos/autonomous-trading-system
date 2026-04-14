"""Tests for the execution bridge — safety gates, dry run, kill switch."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.models import RegimeTransitionEvent, RegimeTier, ScoredSignal
from src.execution.executor import Executor, ExecutionResult, HALT_FILE, _ABSOLUTE_MAX_TRADE_USD


def _make_signal(
    asset: str = "BTC",
    exchange: str = "hyperliquid",
    score: float = 80.0,
    is_actionable: bool = True,
    regime: RegimeTier = RegimeTier.HIGH_FUNDING,
    net_apy: float = 150.0,
) -> ScoredSignal:
    event = RegimeTransitionEvent(
        asset=asset,
        exchange=exchange,
        new_regime=regime,
        previous_regime=RegimeTier.MODERATE,
        max_apy_annualized=200.0,
        timestamp_utc=datetime(2026, 4, 13, 12, 0, 0, tzinfo=timezone.utc),
    )
    return ScoredSignal(
        event=event,
        composite_score=score,
        duration_survival_prob=0.85,
        expected_duration_min=45.0,
        liquidity_score=0.7,
        net_expected_apy=net_apy,
        is_actionable=is_actionable,
        rejection_reason=None if is_actionable else "test rejection",
    )


def _make_executor(
    enabled: bool = True,
    dry_run: bool = True,
    min_score: float = 0.7,
    hl_exchange=None,
    hl_info=None,
    hl_address: str = "0xtest",
) -> Executor:
    """Create an Executor with overridden config for testing."""
    with patch.multiple(
        "config.risk_params",
        EXECUTION_ENABLED=enabled,
        EXECUTION_DRY_RUN=dry_run,
        EXECUTION_MIN_SCORE=min_score,
        EXECUTION_MAX_TRADE_USD=15.0,
        EXECUTION_DAILY_LOSS_LIMIT=10.0,
        EXECUTION_MIN_BALANCE=20.0,
        MAX_CONCURRENT=5,
        LEVERAGE=3,
        CIRCUIT_BREAKER_LOSSES=3,
    ):
        executor = Executor(
            hl_exchange=hl_exchange,
            hl_info=hl_info,
            hl_address=hl_address,
        )
    return executor


class TestDryRunMode:
    """DRY_RUN mode logs but doesn't call HL API."""

    def test_dry_run_logs_without_calling_api(self, tmp_path):
        mock_exchange = MagicMock()
        mock_info = MagicMock()
        mock_info.user_state.return_value = {
            "marginSummary": {"accountValue": "100"},
            "assetPositions": [],
        }
        mock_info.spot_user_state.return_value = {"balances": []}

        executor = _make_executor(
            enabled=True,
            dry_run=True,
            hl_exchange=mock_exchange,
            hl_info=mock_info,
        )

        signal = _make_signal(score=80.0)
        with patch.object(executor, "_log_execution"):
            result = executor.execute(signal)

        assert result.action == "dry_run"
        assert result.dry_run is True
        # Exchange should NOT have been called
        mock_exchange.market_open.assert_not_called()

    def test_dry_run_includes_would_have_details(self):
        mock_info = MagicMock()
        mock_info.user_state.return_value = {
            "marginSummary": {"accountValue": "100"},
            "assetPositions": [],
        }
        mock_info.spot_user_state.return_value = {"balances": []}

        executor = _make_executor(
            enabled=True,
            dry_run=True,
            hl_info=mock_info,
        )

        signal = _make_signal(score=80.0)
        with patch.object(executor, "_log_execution"):
            result = executor.execute(signal)

        assert result.action == "dry_run"
        assert "position_size_usd" in result.details
        assert result.details["position_size_usd"] <= _ABSOLUTE_MAX_TRADE_USD


class TestHaltFile:
    """HALT file blocks all execution."""

    def test_halt_file_blocks_execution(self, tmp_path):
        halt_file = tmp_path / "HALT"
        halt_file.write_text("test halt")

        executor = _make_executor(enabled=True, dry_run=True)

        signal = _make_signal(score=80.0)

        with patch("src.execution.executor.HALT_FILE", halt_file):
            with patch.object(executor, "_log_execution"):
                result = executor.execute(signal)

        assert result.action == "rejected"
        assert "HALT" in result.reason

    def test_no_halt_file_allows_execution(self, tmp_path):
        halt_file = tmp_path / "HALT"
        # Don't create it

        mock_info = MagicMock()
        mock_info.user_state.return_value = {
            "marginSummary": {"accountValue": "100"},
            "assetPositions": [],
        }
        mock_info.spot_user_state.return_value = {"balances": []}

        executor = _make_executor(enabled=True, dry_run=True, hl_info=mock_info)
        signal = _make_signal(score=80.0)

        with patch("src.execution.executor.HALT_FILE", halt_file):
            with patch.object(executor, "_log_execution"):
                result = executor.execute(signal)

        assert result.action != "rejected" or "HALT" not in result.reason


class TestValidationGates:
    """Validation gates reject bad signals."""

    def test_rejects_non_actionable_signal(self):
        executor = _make_executor(enabled=True)
        signal = _make_signal(is_actionable=False)

        with patch.object(executor, "_log_execution"):
            result = executor.execute(signal)

        assert result.action == "rejected"
        assert "not actionable" in result.reason

    def test_rejects_low_score(self):
        executor = _make_executor(enabled=True, min_score=0.7)
        signal = _make_signal(score=50.0)  # 50/100 = 0.5 < 0.7

        with patch.object(executor, "_log_execution"):
            result = executor.execute(signal)

        assert result.action == "rejected"
        assert "Score" in result.reason

    def test_accepts_high_score(self):
        mock_info = MagicMock()
        mock_info.user_state.return_value = {
            "marginSummary": {"accountValue": "100"},
            "assetPositions": [],
        }
        mock_info.spot_user_state.return_value = {"balances": []}

        executor = _make_executor(
            enabled=True, dry_run=True, min_score=0.7, hl_info=mock_info,
        )
        signal = _make_signal(score=80.0)  # 80/100 = 0.8 >= 0.7

        with patch.object(executor, "_log_execution"):
            result = executor.execute(signal)

        assert result.action != "rejected"

    def test_rejects_wrong_regime(self):
        executor = _make_executor(enabled=True)
        signal = _make_signal(regime=RegimeTier.LOW_FUNDING)

        with patch.object(executor, "_log_execution"):
            result = executor.execute(signal)

        assert result.action == "rejected"
        assert "Regime" in result.reason or "regime" in result.reason.lower()

    def test_rejects_moderate_regime(self):
        executor = _make_executor(enabled=True)
        signal = _make_signal(regime=RegimeTier.MODERATE)

        with patch.object(executor, "_log_execution"):
            result = executor.execute(signal)

        assert result.action == "rejected"

    def test_rejects_existing_position(self):
        mock_info = MagicMock()
        mock_info.user_state.return_value = {
            "marginSummary": {"accountValue": "100"},
            "assetPositions": [
                {"position": {"coin": "BTC", "szi": "0.001"}},
            ],
        }
        mock_info.spot_user_state.return_value = {"balances": []}

        executor = _make_executor(enabled=True, hl_info=mock_info)
        signal = _make_signal(asset="BTC")

        with patch.object(executor, "_log_execution"):
            result = executor.execute(signal)

        assert result.action == "rejected"
        assert "open position" in result.reason

    def test_rejects_low_balance(self):
        mock_info = MagicMock()
        mock_info.user_state.return_value = {
            "marginSummary": {"accountValue": "5"},  # Below $20 minimum
            "assetPositions": [],
        }
        mock_info.spot_user_state.return_value = {"balances": []}

        executor = _make_executor(enabled=True, hl_info=mock_info)
        signal = _make_signal(score=80.0)

        with patch.object(executor, "_log_execution"):
            result = executor.execute(signal)

        assert result.action == "rejected"
        assert "Balance" in result.reason

    def test_rejects_max_concurrent(self):
        # 5 existing positions
        positions = [
            {"position": {"coin": f"COIN{i}", "szi": "0.1"}}
            for i in range(5)
        ]
        mock_info = MagicMock()
        mock_info.user_state.return_value = {
            "marginSummary": {"accountValue": "100"},
            "assetPositions": positions,
        }
        mock_info.spot_user_state.return_value = {"balances": []}

        executor = _make_executor(enabled=True, hl_info=mock_info)
        signal = _make_signal(asset="NEW_COIN", score=80.0)

        with patch.object(executor, "_log_execution"):
            result = executor.execute(signal)

        assert result.action == "rejected"
        assert "max concurrent" in result.reason.lower() or "concurrent" in result.reason.lower()


class TestDailyLossLimit:
    """Daily loss limit triggers halt."""

    def test_daily_loss_limit_halts_execution(self):
        executor = _make_executor(enabled=True)

        # Record losses exceeding the $10 limit
        executor.record_loss(6.0)
        executor.record_loss(5.0)  # total: $11

        signal = _make_signal(score=80.0)

        with patch.object(executor, "_log_execution"):
            result = executor.execute(signal)

        assert result.action == "rejected"
        assert "Daily loss limit" in result.reason or "daily" in result.reason.lower()

    def test_daily_loss_resets_next_day(self):
        mock_info = MagicMock()
        mock_info.user_state.return_value = {
            "marginSummary": {"accountValue": "100"},
            "assetPositions": [],
        }
        mock_info.spot_user_state.return_value = {"balances": []}

        executor = _make_executor(enabled=True, dry_run=True, hl_info=mock_info)
        executor.record_loss(11.0)

        assert executor._daily_halted is True

        # Simulate day change
        from datetime import date, timedelta
        executor._today = date.today() - timedelta(days=1)

        signal = _make_signal(score=80.0)
        with patch.object(executor, "_log_execution"):
            result = executor.execute(signal)

        # Should not be rejected for daily loss anymore
        assert "Daily loss limit" not in result.reason if result.action == "rejected" else True


class TestPositionSizeRespects:
    """Position size respects config limits."""

    def test_size_capped_at_absolute_max(self):
        mock_info = MagicMock()
        mock_info.user_state.return_value = {
            "marginSummary": {"accountValue": "10000"},  # Large balance
            "assetPositions": [],
        }
        mock_info.spot_user_state.return_value = {"balances": []}

        executor = _make_executor(enabled=True, dry_run=True, hl_info=mock_info)
        signal = _make_signal(score=80.0)

        with patch.object(executor, "_log_execution"):
            result = executor.execute(signal)

        assert result.action == "dry_run"
        assert result.details["position_size_usd"] <= _ABSOLUTE_MAX_TRADE_USD

    def test_size_capped_at_config_max(self):
        mock_info = MagicMock()
        mock_info.user_state.return_value = {
            "marginSummary": {"accountValue": "500"},
            "assetPositions": [],
        }
        mock_info.spot_user_state.return_value = {"balances": []}

        executor = _make_executor(enabled=True, dry_run=True, hl_info=mock_info)
        signal = _make_signal(score=80.0)

        with patch.object(executor, "_log_execution"):
            result = executor.execute(signal)

        assert result.action == "dry_run"
        assert result.details["position_size_usd"] <= 15.0


class TestExecutionEnabled:
    """EXECUTION_ENABLED=False blocks everything."""

    def test_disabled_blocks_all(self):
        executor = _make_executor(enabled=False)
        signal = _make_signal(score=99.0)

        with patch.object(executor, "_log_execution"):
            result = executor.execute(signal)

        assert result.action == "rejected"
        assert "EXECUTION_ENABLED" in result.reason

    def test_enabled_allows_through(self):
        mock_info = MagicMock()
        mock_info.user_state.return_value = {
            "marginSummary": {"accountValue": "100"},
            "assetPositions": [],
        }
        mock_info.spot_user_state.return_value = {"balances": []}

        executor = _make_executor(enabled=True, dry_run=True, hl_info=mock_info)
        signal = _make_signal(score=80.0)

        with patch.object(executor, "_log_execution"):
            result = executor.execute(signal)

        assert result.action == "dry_run"


class TestCircuitBreaker:
    """Circuit breaker blocks after consecutive losses."""

    def test_circuit_breaker_blocks_after_losses(self):
        mock_info = MagicMock()
        mock_info.user_state.return_value = {
            "marginSummary": {"accountValue": "100"},
            "assetPositions": [],
        }
        mock_info.spot_user_state.return_value = {"balances": []}

        executor = _make_executor(enabled=True, hl_info=mock_info)

        # Record 3 consecutive losses (matches CIRCUIT_BREAKER_LOSSES)
        for _ in range(3):
            executor._consecutive_losses += 1

        signal = _make_signal(score=80.0)
        with patch.object(executor, "_log_execution"):
            result = executor.execute(signal)

        assert result.action == "rejected"
        assert "Circuit breaker" in result.reason or "consecutive" in result.reason.lower()

    def test_win_resets_circuit_breaker(self):
        executor = _make_executor(enabled=True)
        executor._consecutive_losses = 2
        executor.record_win()
        assert executor._consecutive_losses == 0


class TestLiveExecution:
    """Test live execution path (with mocked HL API)."""

    def test_successful_execution(self):
        mock_exchange = MagicMock()
        mock_exchange.market_open.return_value = {
            "status": "ok",
            "response": {"data": {"statuses": [{"filled": {"totalSz": "0.001"}}]}},
        }

        mock_info = MagicMock()
        mock_info.user_state.return_value = {
            "marginSummary": {"accountValue": "100"},
            "assetPositions": [],
        }
        mock_info.spot_user_state.return_value = {"balances": []}
        mock_info.all_mids.return_value = {"BTC": "50000"}
        mock_info.meta.return_value = {
            "universe": [{"name": "BTC", "szDecimals": 5}],
        }

        executor = _make_executor(
            enabled=True,
            dry_run=False,
            hl_exchange=mock_exchange,
            hl_info=mock_info,
        )

        signal = _make_signal(score=80.0)
        with patch.object(executor, "_log_execution"):
            result = executor.execute(signal)

        assert result.action == "executed"
        mock_exchange.market_open.assert_called_once()

        # Verify the order was placed with the correct direction.
        # Default ScoredSignal.direction is now "short" (HIGH_FUNDING
        # convention: positive funding → short earns funding), so is_buy
        # must be False. Previously this test asserted is_buy=True, which
        # encoded the "always LONG" bug in the executor — see
        # TestDirectionRouting for full coverage.
        call_args = mock_exchange.market_open.call_args
        assert call_args[0][0] == "BTC"
        assert call_args[0][1] is False  # is_buy=False → SHORT

    def test_exchange_error_doesnt_crash(self):
        mock_exchange = MagicMock()
        mock_exchange.market_open.side_effect = Exception("connection timeout")

        mock_info = MagicMock()
        mock_info.user_state.return_value = {
            "marginSummary": {"accountValue": "100"},
            "assetPositions": [],
        }
        mock_info.spot_user_state.return_value = {"balances": []}
        mock_info.all_mids.return_value = {"BTC": "50000"}
        mock_info.meta.return_value = {
            "universe": [{"name": "BTC", "szDecimals": 5}],
        }

        executor = _make_executor(
            enabled=True,
            dry_run=False,
            hl_exchange=mock_exchange,
            hl_info=mock_info,
        )

        signal = _make_signal(score=80.0)
        with patch.object(executor, "_log_execution"):
            result = executor.execute(signal)

        assert result.action == "rejected"
        assert "Order failed" in result.reason

    def test_order_rejected_by_exchange(self):
        mock_exchange = MagicMock()
        mock_exchange.market_open.return_value = {
            "status": "ok",
            "response": {"data": {"statuses": [{"error": "Insufficient margin"}]}},
        }

        mock_info = MagicMock()
        mock_info.user_state.return_value = {
            "marginSummary": {"accountValue": "100"},
            "assetPositions": [],
        }
        mock_info.spot_user_state.return_value = {"balances": []}
        mock_info.all_mids.return_value = {"BTC": "50000"}
        mock_info.meta.return_value = {
            "universe": [{"name": "BTC", "szDecimals": 5}],
        }

        executor = _make_executor(
            enabled=True,
            dry_run=False,
            hl_exchange=mock_exchange,
            hl_info=mock_info,
        )

        signal = _make_signal(score=80.0)
        with patch.object(executor, "_log_execution"):
            result = executor.execute(signal)

        assert result.action == "rejected"
        assert "Insufficient margin" in result.reason


class TestKillSwitch:
    """Tests for the kill switch module."""

    def test_activate_creates_halt_file(self, tmp_path):
        halt_file = tmp_path / "HALT"
        with patch("src.execution.kill_switch.HALT_FILE", halt_file):
            with patch("src.execution.kill_switch._send_telegram", return_value=True):
                from src.execution.kill_switch import activate, is_halted
                activate("test reason")
                assert halt_file.exists()
                assert "test reason" in halt_file.read_text()

    def test_deactivate_removes_halt_file(self, tmp_path):
        halt_file = tmp_path / "HALT"
        halt_file.write_text("halted")
        with patch("src.execution.kill_switch.HALT_FILE", halt_file):
            with patch("src.execution.kill_switch._send_telegram", return_value=True):
                from src.execution.kill_switch import deactivate, is_halted
                deactivate()
                assert not halt_file.exists()

    def test_is_halted_reflects_file_state(self, tmp_path):
        halt_file = tmp_path / "HALT"
        with patch("src.execution.kill_switch.HALT_FILE", halt_file):
            from src.execution.kill_switch import is_halted
            assert not is_halted()
            halt_file.write_text("halted")
            assert is_halted()


class TestExecutionResult:
    """Test ExecutionResult serialization."""

    def test_to_dict(self):
        result = ExecutionResult(
            action="dry_run",
            asset="BTC",
            reason="test",
            signal_score=80.0,
            dry_run=True,
            details={"key": "value"},
        )
        d = result.to_dict()
        assert d["action"] == "dry_run"
        assert d["asset"] == "BTC"
        assert d["signal_score"] == 80.0
        assert "timestamp" in d



# ============================================================
# Direction handling — guards against the "always LONG" bug
# ============================================================

def _exec_with_full_mocks(direction_on_signal=None, direction_kw=True):
    """Build an executor + mocks ready to reach market_open."""
    mock_exchange = MagicMock()
    mock_exchange.market_open.return_value = {
        "status": "ok",
        "response": {
            "type": "order",
            "data": {"statuses": [{"filled": {"avgPx": "100.0", "totalSz": "1.0"}}]},
        },
    }
    mock_info = MagicMock()
    mock_info.user_state.return_value = {
        "marginSummary": {"accountValue": "100"},
        "assetPositions": [],
    }
    mock_info.spot_user_state.return_value = {"balances": []}
    mock_info.all_mids.return_value = {"BTC": "100.0"}
    mock_info.meta.return_value = {"universe": [{"name": "BTC", "szDecimals": 4}]}

    executor = _make_executor(
        enabled=True, dry_run=False, hl_exchange=mock_exchange, hl_info=mock_info,
    )
    sig_kwargs = {"score": 80.0}
    signal = _make_signal(**sig_kwargs)
    if direction_kw and direction_on_signal is not None:
        signal.direction = direction_on_signal
    return executor, mock_exchange, signal


class TestDirectionRouting:
    """Verify the executor converts signal.direction into the correct
    is_buy flag for hyperliquid.exchange.Exchange.market_open.

    HL SDK convention (verified on VPS): market_open(name, is_buy=True)
    opens LONG, is_buy=False opens SHORT.
    """

    def test_short_signal_routes_to_is_buy_false(self):
        executor, mock_exchange, signal = _exec_with_full_mocks(direction_on_signal="short")
        with patch.object(executor, "_log_execution"):
            executor.execute(signal)
        assert mock_exchange.market_open.called
        args, kwargs = mock_exchange.market_open.call_args
        # market_open(asset, is_buy, size_coins)
        assert args[0] == "BTC"
        assert args[1] is False, "short signal must call market_open with is_buy=False"

    def test_long_signal_routes_to_is_buy_true(self):
        executor, mock_exchange, signal = _exec_with_full_mocks(direction_on_signal="long")
        with patch.object(executor, "_log_execution"):
            executor.execute(signal)
        assert mock_exchange.market_open.called
        args, _ = mock_exchange.market_open.call_args
        assert args[1] is True

    def test_missing_direction_defaults_to_short(self):
        """If signal has no direction attribute, executor must default
        to SHORT (matches backtester convention for HIGH_FUNDING).
        Defending against the historical "always LONG" bug.
        """
        executor, mock_exchange, signal = _exec_with_full_mocks(direction_kw=False)
        # Force-remove the field on this signal instance
        try:
            object.__delattr__(signal, "direction")
        except AttributeError:
            pass
        with patch.object(executor, "_log_execution"):
            executor.execute(signal)
        assert mock_exchange.market_open.called
        args, _ = mock_exchange.market_open.call_args
        assert args[1] is False, "missing direction must default to SHORT (is_buy=False)"

    def test_default_scoredsignal_direction_is_short(self):
        """Defense in depth: a freshly constructed ScoredSignal that
        omits direction must default to short.
        """
        signal = _make_signal()
        assert signal.direction == "short"

    def test_unknown_direction_falls_back_to_short(self):
        executor, mock_exchange, signal = _exec_with_full_mocks(direction_on_signal="sideways")
        with patch.object(executor, "_log_execution"):
            executor.execute(signal)
        args, _ = mock_exchange.market_open.call_args
        assert args[1] is False
