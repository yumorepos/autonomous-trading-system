#!/usr/bin/env python3
"""Schema and scanner-mode validation for Hyperliquid + Polymarket paper modes."""

import os
import sys
import tempfile
from types import SimpleNamespace
import types
import importlib.util
from pathlib import Path

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
    sys.modules.pop('config.runtime', None)
    sys.modules['requests'] = FakeRequests
    spec = importlib.util.spec_from_file_location('phase1_signal_scanner_test', REPO_ROOT / 'scripts' / 'phase1-signal-scanner.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules['phase1_signal_scanner_test'] = module
    spec.loader.exec_module(module)
    return module


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='openclaw-schema-test-') as temp_dir:
        scanner = load_scanner(Path(temp_dir))
        hl = scanner.scan_hyperliquid_funding()
        pm = scanner.scan_polymarket_markets()

        assert len(hl) == 1, 'Expected one Hyperliquid signal'
        assert len(pm) == 1, 'Expected one Polymarket signal'

        hl_signal = hl[0]
        assert hl_signal['exchange'] == 'Hyperliquid'
        assert hl_signal['signal_type'] == 'funding_arbitrage'
        assert hl_signal['direction'] in {'LONG', 'SHORT'}
        assert hl_signal['entry_price'] > 0

        pm_signal = pm[0]
        required_pm_fields = {'exchange', 'signal_type', 'market_id', 'market_question', 'side', 'entry_price', 'token_id'}
        assert required_pm_fields.issubset(pm_signal), f'Missing fields: {required_pm_fields - set(pm_signal)}'
        assert pm_signal['exchange'] == 'Polymarket'
        assert pm_signal['signal_type'] == 'polymarket_binary_market'
        assert pm_signal['side'] in {'YES', 'NO'}
        assert pm_signal['entry_price'] > 0

        print('[OK] Scanner schema validation passed for Hyperliquid and Polymarket')
