#!/usr/bin/env python3
"""Verify canonical paper-trading contracts are shared across validators, trader, persistence, and readers."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f'HTTP {self.status_code}')


class FakeRequests:
    Timeout = RuntimeError
    RequestException = RuntimeError

    @staticmethod
    def post(url, json=None, timeout=0):
        if json and json.get('type') == 'allMids':
            return FakeResponse({'BTC': 50500.0})
        if json and json.get('type') == 'metaAndAssetCtxs':
            return FakeResponse([
                {'universe': [{'name': 'BTC'}]},
                [{'funding': -0.0005, 'markPx': '50000', 'dayNtlVlm': '2000000', 'openInterest': '20'}],
            ])
        if json and json.get('type') == 'l2Book':
            return FakeResponse({'levels': [[{'px': '50000'}], [{'px': '50010'}]]})
        raise RuntimeError(f'unexpected POST {url} {json}')


def load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='openclaw-paper-contracts-') as temp_dir:
        workspace_root = Path(temp_dir)
        logs_dir = workspace_root / 'logs'
        logs_dir.mkdir(parents=True, exist_ok=True)

        os.environ['OPENCLAW_WORKSPACE'] = str(workspace_root)
        os.environ['OPENCLAW_TRADING_MODE'] = 'hyperliquid_only'
        sys.modules.pop('config.runtime', None)
        sys.modules['requests'] = FakeRequests

        from models.paper_contracts import canonical_trade_required_fields, paper_position_identifier, validate_signal_contract
        from models.position_state import apply_trade_to_position_state, get_open_positions
        from models.trade_schema import normalize_trade_record, validate_trade_record

        trader = load_module('paper_contracts_trader_test', REPO_ROOT / 'scripts' / 'phase1-paper-trader.py')
        dashboard_module = load_module('paper_contracts_dashboard_test', REPO_ROOT / 'scripts' / 'support' / 'performance-dashboard.py')
        timeout_module = load_module('paper_contracts_timeout_test', REPO_ROOT / 'scripts' / 'timeout-monitor.py')
        safety_module = load_module('paper_contracts_safety_test', REPO_ROOT / 'scripts' / 'execution-safety-layer.py')
        integrity_module = load_module('paper_contracts_integrity_test', REPO_ROOT / 'scripts' / 'data-integrity-layer.py')

        assert 'exit_timestamp' in canonical_trade_required_fields('CLOSED', 'Hyperliquid')

        valid_hl_signal = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'source': 'Hyperliquid',
            'exchange': 'Hyperliquid',
            'signal_type': 'funding_arbitrage',
            'strategy': 'funding_arbitrage',
            'asset': 'BTC',
            'symbol': 'BTC',
            'direction': 'LONG',
            'entry_price': 50000.0,
            'ev_score': 12.0,
        }

        contract_valid, contract_reason, contract = validate_signal_contract(valid_hl_signal)
        assert contract_valid is True, contract_reason
        assert contract is not None
        trader_valid, trader_reason = trader.validate_canonical_signal(valid_hl_signal)
        assert trader_valid is True, trader_reason

        integrity = integrity_module.DataIntegrityLayer()
        passed, validations = integrity.validate_signal(valid_hl_signal.copy(), source='hyperliquid')
        assert passed is True, validations
        exchange_contract = next(result for result in validations if result.check_name == 'exchange_contract')
        assert exchange_contract.passed is True, validations
        assert exchange_contract.data['required_fields'] == list(contract.required_signal_fields)

        invalid_hl_signal = {
            **valid_hl_signal,
            'timestamp': (datetime.now(timezone.utc) + timedelta(microseconds=1)).isoformat(),
            'direction': None,
        }
        contract_valid, _, _ = validate_signal_contract(invalid_hl_signal)
        assert contract_valid is False, invalid_hl_signal
        trader_valid, _ = trader.validate_canonical_signal(invalid_hl_signal)
        assert trader_valid is False, invalid_hl_signal
        integrity = integrity_module.DataIntegrityLayer()
        passed, validations = integrity.validate_signal(invalid_hl_signal.copy(), source='hyperliquid')
        assert passed is False, validations
        exchange_contract = next(result for result in validations if result.check_name == 'exchange_contract')
        assert exchange_contract.passed is False, validations

        now = datetime.now(timezone.utc)
        position_state_path = logs_dir / 'position-state.json'
        trades_path = logs_dir / 'phase1-paper-trades.jsonl'

        valid_open_record = {
            'trade_id': 'hl-open-1',
            'exchange': 'Hyperliquid',
            'strategy': 'funding_arbitrage',
            'symbol': 'BTC',
            'asset': 'BTC',
            'side': 'LONG',
            'entry_price': 50000.0,
            'position_size': 0.001,
            'position_size_usd': 50.0,
            'status': 'OPEN',
            'entry_timestamp': (now - timedelta(minutes=5)).isoformat(),
            'signal': valid_hl_signal,
        }
        assert validate_trade_record(valid_open_record, context="valid-open[hl-open-1]")
        apply_trade_to_position_state(position_state_path, valid_open_record)

        open_positions = sorted(get_open_positions(position_state_path), key=paper_position_identifier)
        timeout_monitor = timeout_module.TimeoutMonitor()
        timeout_positions = sorted(timeout_monitor.load_positions(), key=paper_position_identifier)
        assert [paper_position_identifier(position) for position in open_positions] == ['BTC'], open_positions
        assert [paper_position_identifier(position) for position in timeout_positions] == ['BTC'], timeout_positions

        closed_record = {
            'trade_id': 'hl-closed-1',
            'exchange': 'Hyperliquid',
            'strategy': 'funding_arbitrage',
            'symbol': 'BTC',
            'side': 'LONG',
            'entry_price': 50000.0,
            'exit_price': 50500.0,
            'position_size': 0.001,
            'position_size_usd': 50.0,
            'realized_pnl_usd': 0.5,
            'realized_pnl_pct': 1.0,
            'status': 'CLOSED',
            'exit_reason': 'take_profit',
            'entry_timestamp': (now - timedelta(hours=2)).isoformat(),
            'exit_timestamp': (now - timedelta(hours=1, minutes=30)).isoformat(),
        }
        with open(trades_path, 'w') as handle:
            handle.write(json.dumps(closed_record) + '\n')

        assert validate_trade_record(normalize_trade_record(closed_record), context='closed.hl')

        dashboard = dashboard_module.PerformanceDashboard()
        assert [paper_position_identifier(position) for position in sorted(dashboard.open_positions, key=paper_position_identifier)] == ['BTC']
        assert len(dashboard.hl_trades) == 1, dashboard.hl_trades

        safety = safety_module.ExecutionSafetyLayer()
        canonical_trade_ids = sorted(trade['trade_id'] for trade in safety._canonical_trade_history())
        assert canonical_trade_ids == ['hl-closed-1'], canonical_trade_ids

        performance = trader.calculate_performance()
        assert performance['total_trades'] == 1, performance
        assert performance['exchange_breakdown']['Hyperliquid']['total_trades'] == 1, performance

        print('[OK] Canonical paper-trading contracts are shared across signal validation, trader execution, persistence, and readers')
