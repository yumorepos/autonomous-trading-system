#!/usr/bin/env python3
"""Verify canonical scanner persistence is gated by signal-level data-integrity validation."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
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


class FakeRequests:
    Timeout = RuntimeError
    RequestException = RuntimeError

    @staticmethod
    def post(url, json=None, timeout=0):
        if json and json.get('type') == 'metaAndAssetCtxs':
            return FakeResponse([
                {'universe': [{'name': 'BTC'}]},
                [{'funding': -0.0005, 'markPx': '50000', 'dayNtlVlm': '2000000', 'openInterest': '20'}],
            ])
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


def load_scanner(workspace_root: Path):
    os.environ['OPENCLAW_WORKSPACE'] = str(workspace_root)
    os.environ['OPENCLAW_TRADING_MODE'] = 'mixed'
    for module_name in [
        'config.runtime',
        'utils.api_connectivity',
        'utils.runtime_logging',
        'phase1_signal_scanner_signal_integrity_test',
    ]:
        sys.modules.pop(module_name, None)
    sys.modules['requests'] = FakeRequests
    spec = importlib.util.spec_from_file_location(
        'phase1_signal_scanner_signal_integrity_test',
        REPO_ROOT / 'scripts' / 'phase1-signal-scanner.py',
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules['phase1_signal_scanner_signal_integrity_test'] = module
    spec.loader.exec_module(module)
    return module


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='openclaw-signal-integrity-') as temp_dir:
        workspace_root = Path(temp_dir)
        logs_dir = workspace_root / 'logs'
        data_state = logs_dir / 'data-integrity-state.json'
        data_state.parent.mkdir(parents=True, exist_ok=True)
        data_state.write_text(json.dumps({
            'health': 'HEALTHY',
            'last_update': None,
            'sources': {
                'hyperliquid': {'last_success': None, 'last_failure': None, 'consecutive_failures': 0, 'health': 'UNKNOWN'},
                'polymarket': {'last_success': None, 'last_failure': None, 'consecutive_failures': 0, 'health': 'UNKNOWN'},
            },
            'last_validated_data': {},
            'validation_failures': [],
            'recent_signals': [],
        }, indent=2))

        scanner = load_scanner(workspace_root)
        base = datetime.now(timezone.utc)
        scanner.scan_hyperliquid_funding = lambda: [
            {
                'timestamp': base.isoformat(),
                'source': 'Hyperliquid',
                'exchange': 'Hyperliquid',
                'signal_type': 'funding_arbitrage',
                'strategy': 'funding_arbitrage',
                'asset': 'BTC',
                'symbol': 'BTC',
                'entry_price': 50000.0,
                'ev_score': 12.0,
                'conviction': 'MEDIUM',
                'recommended_position_size_usd': 1.96,
                'paper_only': True,
                'experimental': False,
            }
        ]
        scanner.scan_polymarket_markets = lambda: [
            {
                'timestamp': (base.replace(microsecond=1)).isoformat(),
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
                'entry_price': 0.43,
                'best_bid': 0.41,
                'best_ask': 0.43,
                'last_price': 0.42,
                'spread_pct': 4.65,
                'liquidity_usd': 20000.0,
                'ev_score': 17.05,
                'conviction': 'HIGH',
                'recommended_position_size_usd': 5.0,
                'paper_only': True,
                'experimental': True,
            },
            {
                'timestamp': (base.replace(microsecond=2)).isoformat(),
                'source': 'Polymarket',
                'exchange': 'Polymarket',
                'signal_type': 'polymarket_binary_market',
                'strategy': 'polymarket_spread',
                'asset': 'pm-btc-down',
                'symbol': 'pm-btc-down',
                'market_id': 'pm-btc-down',
                'side': 'NO',
                'direction': 'NO',
                'token_id': 'no-token',
                'entry_price': 0.57,
                'best_bid': 0.55,
                'best_ask': 0.57,
                'last_price': 0.56,
                'spread_pct': 3.51,
                'liquidity_usd': 18000.0,
                'ev_score': 9.25,
                'conviction': 'MEDIUM',
                'recommended_position_size_usd': 5.0,
                'paper_only': True,
                'experimental': True,
            }
        ]
        scanner.main()

        signals_path = logs_dir / 'phase1-signals.jsonl'
        rejected_path = logs_dir / 'rejected-signals.jsonl'
        report_path = workspace_root / 'PHASE1_SIGNAL_REPORT.md'

        persisted_signals = [json.loads(line) for line in signals_path.read_text().splitlines() if line.strip()]
        assert len(persisted_signals) == 1, persisted_signals
        assert persisted_signals[0]['exchange'] == 'Polymarket', persisted_signals
        assert persisted_signals[0]['market_id'] == 'pm-btc-up', persisted_signals

        rejected_signals = [json.loads(line) for line in rejected_path.read_text().splitlines() if line.strip()]
        assert len(rejected_signals) == 2, rejected_signals
        rejected_sources = {rejection['source'] for rejection in rejected_signals}
        assert rejected_sources == {'hyperliquid', 'polymarket'}, rejected_signals
        failed_checks_by_exchange = {
            rejection['signal']['exchange']: {
                validation['check_name']
                for validation in rejection['validations']
                if not validation['passed']
            }
            for rejection in rejected_signals
        }
        assert failed_checks_by_exchange['Hyperliquid'] == {'exchange_contract'}, failed_checks_by_exchange
        assert failed_checks_by_exchange['Polymarket'] == {'exchange_contract'}, failed_checks_by_exchange

        report = report_path.read_text()
        assert 'Accepted signals this scan: 1' in report, report
        assert 'Rejected signals this scan: 2' in report, report
        assert 'validate_signal()' in report, report

        print('[OK] Canonical scanner rejects exchange-invalid Hyperliquid and Polymarket signals before persistence')
