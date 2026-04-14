"""Test HL 429 retry + graceful degradation in trading_engine.

Covers:
- get_state() retries on 429 and succeeds on a later attempt
- get_state() re-raises after exhausting 3 retries (4 attempts total)
- get_state() re-raises immediately on non-429 ClientError
- protect_capital() skips cycle on client.get_state() failure
- periodic_reconciliation() skips cycle on client.get_state() failure
"""
from __future__ import annotations

import os
import sys
import time
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# HL_PRIVATE_KEY must be set for HyperliquidClient.__init__; we don't actually
# instantiate it via the real constructor, but importing the module may touch it.
os.environ.setdefault("HL_PRIVATE_KEY", "0x" + "1" * 64)

# Stub the hyperliquid SDK before importing the engine so tests don't need the
# real package installed on the host (container has it; CI host may not).
if "hyperliquid" not in sys.modules:
    hl = types.ModuleType("hyperliquid")
    hl_info = types.ModuleType("hyperliquid.info")
    hl_exchange = types.ModuleType("hyperliquid.exchange")
    hl_utils = types.ModuleType("hyperliquid.utils")
    hl_error = types.ModuleType("hyperliquid.utils.error")

    class ClientError(Exception):
        def __init__(self, status_code, error_code=None, error_message=None,
                     header=None, error_data=None):
            super().__init__(status_code, error_code, error_message, header, error_data)
            self.status_code = status_code
            self.error_message = error_message

    hl_error.ClientError = ClientError
    hl_info.Info = MagicMock
    hl_exchange.Exchange = MagicMock

    sys.modules["hyperliquid"] = hl
    sys.modules["hyperliquid.info"] = hl_info
    sys.modules["hyperliquid.exchange"] = hl_exchange
    sys.modules["hyperliquid.utils"] = hl_utils
    sys.modules["hyperliquid.utils.error"] = hl_error

# eth_account stub (engine imports Account.from_key at client init, but we bypass
# __init__ in these tests — still, guard against transitive imports).
if "eth_account" not in sys.modules:
    eth = types.ModuleType("eth_account")
    eth.Account = MagicMock()
    sys.modules["eth_account"] = eth

# Now import the engine module
import importlib
trading_engine = importlib.import_module("scripts.trading_engine")
HyperliquidClient = trading_engine.HyperliquidClient
_HLClientError = trading_engine._HLClientError


def _make_client():
    """Build a HyperliquidClient without running __init__ (no real SDK calls)."""
    c = HyperliquidClient.__new__(HyperliquidClient)
    c.info = MagicMock()
    c.exchange = MagicMock()
    c.address = "0xTEST"
    c.asset_metadata = {}
    return c


def _user_state_ok():
    return {
        "marginSummary": {"accountValue": "100.0"},
        "assetPositions": [],
    }


def _err(status):
    return _HLClientError(status, None, "rate limited", None, {})


# ---------------------------------------------------------------------------
# get_state retry behaviour
# ---------------------------------------------------------------------------

class TestGetStateRetry:
    def test_succeeds_first_try(self):
        c = _make_client()
        c.info.user_state.return_value = _user_state_ok()
        c.info.spot_user_state.return_value = {"balances": []}
        with patch.object(trading_engine.time, "sleep") as sleep:
            state = c.get_state()
        assert state["account_value"] == 100.0
        assert c.info.user_state.call_count == 1
        sleep.assert_not_called()

    def test_retries_on_429_then_succeeds(self):
        c = _make_client()
        c.info.user_state.side_effect = [
            _err(429),
            _err(429),
            _user_state_ok(),
        ]
        c.info.spot_user_state.return_value = {"balances": []}
        with patch.object(trading_engine.time, "sleep") as sleep:
            state = c.get_state()
        assert state["account_value"] == 100.0
        assert c.info.user_state.call_count == 3
        # Two backoff sleeps for the two retries before success: 1s, 2s
        assert [call.args[0] for call in sleep.call_args_list] == [1, 2]

    def test_raises_after_exhausting_retries(self):
        c = _make_client()
        c.info.user_state.side_effect = _err(429)
        with patch.object(trading_engine.time, "sleep"):
            with pytest.raises(_HLClientError) as excinfo:
                c.get_state()
        assert excinfo.value.status_code == 429
        # 1 initial + 3 retries = 4 attempts
        assert c.info.user_state.call_count == 4

    def test_non_429_error_reraises_immediately(self):
        c = _make_client()
        c.info.user_state.side_effect = _err(500)
        with patch.object(trading_engine.time, "sleep") as sleep:
            with pytest.raises(_HLClientError) as excinfo:
                c.get_state()
        assert excinfo.value.status_code == 500
        assert c.info.user_state.call_count == 1
        sleep.assert_not_called()


# ---------------------------------------------------------------------------
# protect_capital / periodic_reconciliation graceful degradation
# ---------------------------------------------------------------------------

def _make_engine():
    """Construct a TradingEngine skeleton without running __init__."""
    engine = trading_engine.TradingEngine.__new__(trading_engine.TradingEngine)
    engine.client = MagicMock()
    engine.state = MagicMock()
    engine.state.data = {"open_positions": {}, "peak_roe": {}}
    engine.dry_run = True
    engine.last_reconcile = 0.0
    return engine


class TestProtectCapitalGraceful:
    def test_skip_cycle_on_api_error(self):
        engine = _make_engine()
        engine.client.get_state.side_effect = _err(429)

        events = []
        with patch.object(trading_engine, "log_event", lambda e: events.append(e)):
            # Must NOT raise
            engine.protect_capital()

        assert any(e.get("event") == "protect_capital_error" for e in events)
        skip = next(e for e in events if e.get("event") == "protect_capital_error")
        assert skip["action"] == "skip_cycle"
        assert skip["error_type"] == "ClientError"

    def test_normal_path_still_runs(self):
        engine = _make_engine()
        engine.client.get_state.return_value = {"positions": []}
        with patch.object(trading_engine, "log_event", lambda e: None):
            engine.protect_capital()  # no positions -> no-op, no raise


class TestPeriodicReconciliationGraceful:
    def test_skip_cycle_on_api_error(self):
        engine = _make_engine()
        engine.client.get_state.side_effect = _err(429)

        events = []
        with patch.object(trading_engine, "log_event", lambda e: events.append(e)):
            engine.periodic_reconciliation()

        assert any(e.get("event") == "periodic_reconciliation_error" for e in events)
        # Timer must advance so we don't hot-spin
        assert engine.last_reconcile > 0
