#!/usr/bin/env python3
"""Verify the explicit mixed-mode policy: Hyperliquid-primary, one-entry-per-cycle, advisory secondary-source health."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.elapsed = SimpleNamespace(total_seconds=lambda: 0.01)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f'HTTP {self.status_code}')


class MixedModeRequests:
    hl_up = True
    pm_up = True

    Timeout = RuntimeError
    RequestException = RuntimeError

    @classmethod
    def post(cls, url, json=None, timeout=0):
        if not cls.hl_up:
            raise RuntimeError('Hyperliquid unavailable in mixed-mode policy test')
        return FakeResponse([
            {'universe': [{'name': 'BTC'}] + [{'name': f'ALT{i:03d}'} for i in range(99)]},
            [{'funding': -0.0005, 'markPx': '50000', 'dayNtlVlm': '2000000', 'openInterest': '20'}]
            + [{'funding': '0.00001', 'markPx': '10', 'dayNtlVlm': '1000', 'openInterest': '5'} for _ in range(99)],
        ])

    @classmethod
    def get(cls, url, params=None, timeout=0):
        if not cls.pm_up:
            raise RuntimeError('Polymarket unavailable in mixed-mode policy test')
        return FakeResponse([
            {
                'conditionId': 'pm-btc-up',
                'question': 'Will BTC close above 60k?',
                'liquidity': 20000,
                'tokens': [
                    {'outcome': 'YES', 'token_id': 'yes-token', 'bestBid': 0.41, 'bestAsk': 0.42, 'price': 0.42},
                    {'outcome': 'NO', 'token_id': 'no-token', 'bestBid': 0.57, 'bestAsk': 0.58, 'price': 0.58},
                ],
            },
            {
                'conditionId': 'pm-eth-up',
                'question': 'Will ETH close above 4k?',
                'liquidity': 20000,
                'tokens': [
                    {'outcome': 'YES', 'token_id': 'yes-token-2', 'bestBid': 0.41, 'bestAsk': 0.42, 'price': 0.42},
                    {'outcome': 'NO', 'token_id': 'no-token-2', 'bestBid': 0.57, 'bestAsk': 0.58, 'price': 0.58},
                ],
            },
            {
                'conditionId': 'pm-sol-up',
                'question': 'Will SOL close above 200?',
                'liquidity': 20000,
                'tokens': [
                    {'outcome': 'YES', 'token_id': 'yes-token-3', 'bestBid': 0.41, 'bestAsk': 0.42, 'price': 0.42},
                    {'outcome': 'NO', 'token_id': 'no-token-3', 'bestBid': 0.57, 'bestAsk': 0.58, 'price': 0.58},
                ],
            },
        ])


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_data_integrity(workspace_root: Path):
    os.environ['OPENCLAW_WORKSPACE'] = str(workspace_root)
    os.environ['OPENCLAW_TRADING_MODE'] = 'mixed'
    sys.modules.pop('config.runtime', None)
    sys.modules['requests'] = MixedModeRequests
    return load_module('mixed_mode_policy_data_integrity', REPO_ROOT / 'scripts' / 'data-integrity-layer.py')


def load_trader(workspace_root: Path):
    os.environ['OPENCLAW_WORKSPACE'] = str(workspace_root)
    os.environ['OPENCLAW_TRADING_MODE'] = 'mixed'
    sys.modules.pop('config.runtime', None)
    sys.modules['requests'] = MixedModeRequests
    return load_module('mixed_mode_policy_trader', REPO_ROOT / 'scripts' / 'phase1-paper-trader.py')


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='openclaw-mixed-policy-') as temp_dir:
        workspace_root = Path(temp_dir)
        logs_dir = workspace_root / 'logs'

        MixedModeRequests.hl_up = False
        MixedModeRequests.pm_up = True
        data_integrity = load_data_integrity(workspace_root)
        gate = data_integrity.DataIntegrityLayer().run_pre_scan_gate(include_polymarket=True)
        assert gate['passed'] is False, gate
        assert any(check['data'].get('source') == 'hyperliquid' and check['severity'] == 'CRITICAL' and not check['passed'] for check in gate['checks']), gate

        MixedModeRequests.hl_up = True
        MixedModeRequests.pm_up = False
        data_integrity = load_data_integrity(workspace_root)
        gate = data_integrity.DataIntegrityLayer().run_pre_scan_gate(include_polymarket=True)
        assert gate['passed'] is True, gate
        assert any(check['data'].get('source') == 'polymarket' and check['severity'] == 'WARNING' and not check['passed'] for check in gate['checks']), gate

        trader = load_trader(workspace_root)
        signals_path = logs_dir / 'phase1-signals.jsonl'
        signals_path.parent.mkdir(parents=True, exist_ok=True)
        signals = [
            {
                'timestamp': '2026-01-01T00:00:00+00:00',
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
                'ev_score': 10.0,
                'conviction': 'MEDIUM',
                'recommended_position_size_usd': 5.0,
                'paper_only': True,
                'experimental': True,
            },
            {
                'timestamp': '2026-01-01T00:00:01+00:00',
                'source': 'Hyperliquid',
                'exchange': 'Hyperliquid',
                'signal_type': 'funding_arbitrage',
                'strategy': 'funding_arbitrage',
                'asset': 'ETH',
                'symbol': 'ETH',
                'direction': 'LONG',
                'entry_price': 3000.0,
                'ev_score': 8.0,
                'conviction': 'MEDIUM',
                'recommended_position_size_usd': 1.96,
                'paper_only': True,
                'experimental': False,
            },
        ]
        with open(signals_path, 'w') as handle:
            for signal in signals:
                handle.write(json.dumps(signal) + '\n')

        plan = trader.build_execution_plan()
        assert plan['planned_entry']['exchange'] == 'Hyperliquid', plan
        assert 'current deterministic mixed-mode priority winner' in plan['entry_reason'], plan['entry_reason']
        assert 'max_new_entries_per_cycle=1' in plan['entry_reason'], plan['entry_reason']

        print('[OK] Mixed-mode policy is explicit and enforced: Hyperliquid primary, one new entry per cycle, advisory secondary-source health')
