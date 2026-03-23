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

    @staticmethod
    def get(url, params=None, timeout=0):
        return FakeResponse([
            {
                'conditionId': 'pm-btc-up',
                'question': 'Will BTC close above 60k?',
                'liquidity': 20000,
                'tokens': [
                    {'outcome': 'YES', 'token_id': 'yes-token', 'bestBid': 0.41, 'bestAsk': 0.43, 'price': 0.42},
                    {'outcome': 'NO', 'token_id': 'no-token', 'bestBid': 0.57, 'bestAsk': 0.59, 'price': 0.58},
                ],
            }
        ])


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
        os.environ['OPENCLAW_TRADING_MODE'] = 'mixed'
        sys.modules.pop('config.runtime', None)
        sys.modules['requests'] = FakeRequests

        from models.paper_contracts import canonical_trade_required_fields, paper_position_identifier, validate_signal_contract
        from models.position_state import apply_trade_to_position_state, get_open_positions
        from models.trade_schema import normalize_trade_record, validate_trade_record

        trader = load_module('paper_contracts_trader_test', REPO_ROOT / 'scripts' / 'phase1-paper-trader.py')
        dashboard_module = load_module('paper_contracts_dashboard_test', REPO_ROOT / 'scripts' / 'performance-dashboard.py')
        timeout_module = load_module('paper_contracts_timeout_test', REPO_ROOT / 'scripts' / 'timeout-monitor.py')
        safety_module = load_module('paper_contracts_safety_test', REPO_ROOT / 'scripts' / 'execution-safety-layer.py')
        integrity_module = load_module('paper_contracts_integrity_test', REPO_ROOT / 'scripts' / 'data-integrity-layer.py')

        assert canonical_trade_required_fields('OPEN', 'Polymarket')[-1] == 'market_id'
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
        valid_pm_signal = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'source': 'Polymarket',
            'exchange': 'Polymarket',
            'signal_type': 'polymarket_binary_market',
            'strategy': 'polymarket_spread',
            'asset': 'pm-btc-up',
            'symbol': 'pm-btc-up',
            'market_id': 'pm-btc-up',
            'market_question': 'Will BTC close above 60k?',
            'side': 'YES',
            'direction': 'YES',
            'token_id': 'yes-token',
            'entry_price': 0.42,
            'ev_score': 17.0,
        }

        for signal in (valid_hl_signal, valid_pm_signal):
            contract_valid, contract_reason, contract = validate_signal_contract(signal)
            assert contract_valid is True, contract_reason
            assert contract is not None
            trader_valid, trader_reason = trader.validate_canonical_signal(signal)
            assert trader_valid is True, trader_reason

            integrity = integrity_module.DataIntegrityLayer()
            passed, validations = integrity.validate_signal(signal.copy(), source=signal['source'].lower())
            assert passed is True, validations
            exchange_contract = next(result for result in validations if result.check_name == 'exchange_contract')
            assert exchange_contract.passed is True, validations
            assert exchange_contract.data['required_fields'] == list(contract.required_signal_fields)

        invalid_signals = [
            {
                **valid_hl_signal,
                'timestamp': (datetime.now(timezone.utc) + timedelta(microseconds=1)).isoformat(),
                'direction': None,
            },
            {
                **valid_pm_signal,
                'timestamp': (datetime.now(timezone.utc) + timedelta(microseconds=2)).isoformat(),
                'market_id': None,
            },
        ]
        for signal in invalid_signals:
            contract_valid, _, _ = validate_signal_contract(signal)
            assert contract_valid is False, signal
            trader_valid, _ = trader.validate_canonical_signal(signal)
            assert trader_valid is False, signal
            integrity = integrity_module.DataIntegrityLayer()
            passed, validations = integrity.validate_signal(signal.copy(), source=str(signal['source']).lower())
            assert passed is False, validations
            exchange_contract = next(result for result in validations if result.check_name == 'exchange_contract')
            assert exchange_contract.passed is False, validations

        now = datetime.now(timezone.utc)
        position_state_path = logs_dir / 'position-state.json'
        trades_path = logs_dir / 'phase1-paper-trades.jsonl'

        valid_open_records = [
            {
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
            },
            {
                'trade_id': 'pm-open-1',
                'exchange': 'Polymarket',
                'strategy': 'polymarket_spread',
                'symbol': 'pm-btc-up',
                'asset': 'pm-btc-up',
                'side': 'YES',
                'entry_price': 0.42,
                'position_size': 10.0,
                'position_size_usd': 4.2,
                'status': 'OPEN',
                'entry_timestamp': (now - timedelta(minutes=3)).isoformat(),
                'market_id': 'pm-btc-up',
                'market_question': 'Will BTC close above 60k?',
                'token_id': 'yes-token',
                'signal': valid_pm_signal,
            },
        ]
        for record in valid_open_records:
            assert validate_trade_record(record, context=f"valid-open[{record['trade_id']}]")
            apply_trade_to_position_state(position_state_path, record)

        state_payload = json.loads(position_state_path.read_text())
        state_payload['positions']['pm-bad-open'] = {
            'trade_id': 'pm-bad-open',
            'exchange': 'Polymarket',
            'strategy': 'polymarket_spread',
            'symbol': 'pm-bad-open',
            'side': 'YES',
            'entry_price': 0.35,
            'position_size': 8.0,
            'position_size_usd': 2.8,
            'status': 'OPEN',
            'entry_timestamp': (now - timedelta(minutes=1)).isoformat(),
        }
        position_state_path.write_text(json.dumps(state_payload, indent=2))

        open_positions = sorted(get_open_positions(position_state_path), key=paper_position_identifier)
        timeout_monitor = timeout_module.TimeoutMonitor()
        timeout_positions = sorted(timeout_monitor.load_positions(), key=paper_position_identifier)
        assert [paper_position_identifier(position) for position in open_positions] == ['BTC', 'pm-btc-up'], open_positions
        assert [paper_position_identifier(position) for position in timeout_positions] == ['BTC', 'pm-btc-up'], timeout_positions

        closed_records = [
            {
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
            },
            {
                'trade_id': 'pm-closed-1',
                'exchange': 'Polymarket',
                'strategy': 'polymarket_spread',
                'symbol': 'pm-btc-up',
                'side': 'YES',
                'entry_price': 0.42,
                'exit_price': 0.48,
                'position_size': 10.0,
                'position_size_usd': 4.2,
                'realized_pnl_usd': 0.6,
                'realized_pnl_pct': 14.29,
                'status': 'CLOSED',
                'exit_reason': 'take_profit',
                'entry_timestamp': (now - timedelta(hours=3)).isoformat(),
                'exit_timestamp': (now - timedelta(hours=2, minutes=30)).isoformat(),
                'market_id': 'pm-btc-up',
                'market_question': 'Will BTC close above 60k?',
                'token_id': 'yes-token',
            },
            {
                'trade_id': 'pm-bad-closed',
                'exchange': 'Polymarket',
                'strategy': 'polymarket_spread',
                'symbol': 'pm-bad-open',
                'side': 'YES',
                'entry_price': 0.33,
                'exit_price': 0.31,
                'position_size': 10.0,
                'position_size_usd': 3.3,
                'realized_pnl_usd': -0.2,
                'realized_pnl_pct': -6.06,
                'status': 'CLOSED',
                'exit_reason': 'stop_loss',
                'entry_timestamp': (now - timedelta(hours=4)).isoformat(),
                'exit_timestamp': (now - timedelta(hours=3, minutes=30)).isoformat(),
            },
        ]
        with open(trades_path, 'w') as handle:
            for record in closed_records:
                handle.write(json.dumps(record) + '\n')

        assert validate_trade_record(normalize_trade_record(closed_records[0]), context='closed.hl')
        assert validate_trade_record(normalize_trade_record(closed_records[1]), context='closed.pm')
        assert not validate_trade_record(normalize_trade_record(closed_records[2]), context='closed.pm.invalid')

        dashboard = dashboard_module.PerformanceDashboard()
        assert [paper_position_identifier(position) for position in sorted(dashboard.open_positions, key=paper_position_identifier)] == ['BTC', 'pm-btc-up']
        assert len(dashboard.hl_trades) == 1, dashboard.hl_trades
        assert len(dashboard.pm_trades) == 1, dashboard.pm_trades

        safety = safety_module.ExecutionSafetyLayer()
        canonical_trade_ids = sorted(trade['trade_id'] for trade in safety._canonical_trade_history())
        assert canonical_trade_ids == ['hl-closed-1', 'pm-closed-1'], canonical_trade_ids

        performance = trader.calculate_performance()
        assert performance['total_trades'] == 2, performance
        assert performance['exchange_breakdown']['Hyperliquid']['total_trades'] == 1, performance
        assert performance['exchange_breakdown']['Polymarket']['total_trades'] == 1, performance

        print('[OK] Canonical paper-trading contracts are shared across signal validation, trader execution, persistence, and readers')
