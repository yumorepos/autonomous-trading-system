#!/usr/bin/env python3
"""Verify the pre-scan gate respects the selected trading mode."""

import importlib.util
import os
import sys
import tempfile
from types import SimpleNamespace
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

    class exceptions:
        RequestException = RuntimeError

    @staticmethod
    def post(url, json=None, timeout=0):
        raise RuntimeError('Hyperliquid unavailable in test')

    @staticmethod
    def get(url, params=None, timeout=0):
        return FakeResponse(
            [
                {
                    'conditionId': 'pm-btc-up',
                    'question': 'Will BTC close above 60k?',
                    'tokens': [{'outcome': 'YES'}, {'outcome': 'NO'}],
                },
                {
                    'conditionId': 'pm-eth-up',
                    'question': 'Will ETH close above 4k?',
                    'tokens': [{'outcome': 'YES'}, {'outcome': 'NO'}],
                },
                {
                    'conditionId': 'pm-sol-up',
                    'question': 'Will SOL close above 200?',
                    'tokens': [{'outcome': 'YES'}, {'outcome': 'NO'}],
                }
            ]
        )


def load_module(workspace_root: Path):
    os.environ['OPENCLAW_WORKSPACE'] = str(workspace_root)
    os.environ['OPENCLAW_TRADING_MODE'] = 'polymarket_only'
    sys.modules.pop('config.runtime', None)
    sys.modules['requests'] = FakeRequests
    spec = importlib.util.spec_from_file_location('data_integrity_mode_test', REPO_ROOT / 'scripts' / 'data-integrity-layer.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules['data_integrity_mode_test'] = module
    spec.loader.exec_module(module)
    return module


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='openclaw-di-mode-') as temp_dir:
        module = load_module(Path(temp_dir))
        layer = module.DataIntegrityLayer()
        result = layer.run_pre_scan_gate(include_polymarket=True)

        assert result['passed'] is True, result
        sources = {check['data']['source'] for check in result['checks'] if check.get('data', {}).get('source')}
        assert sources == {'polymarket'}, sources
        assert result['health'] in {'HEALTHY', 'DEGRADED'}, result['health']

        print('[OK] Data integrity gate respects polymarket_only mode')
