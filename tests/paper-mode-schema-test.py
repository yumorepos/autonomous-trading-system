#!/usr/bin/env python3
"""Schema and scanner-mode validation for Hyperliquid paper mode."""

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



def load_scanner(workspace_root: Path):
    os.environ['OPENCLAW_WORKSPACE'] = str(workspace_root)
    os.environ['OPENCLAW_TRADING_MODE'] = 'hyperliquid_only'
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

        assert len(hl) == 1, 'Expected one Hyperliquid signal'

        hl_signal = hl[0]
        assert hl_signal['exchange'] == 'Hyperliquid'
        assert hl_signal['signal_type'] == 'funding_arbitrage'
        assert hl_signal['direction'] in {'LONG', 'SHORT'}
        assert hl_signal['entry_price'] > 0
        assert hl_signal['experimental'] is False

        print('[OK] Scanner schema validation passed for Hyperliquid')
