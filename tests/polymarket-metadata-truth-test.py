#!/usr/bin/env python3
"""Guard Polymarket experimental metadata semantics across runtime producers."""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import types
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def fake_requests_module():
    def _fail(*args, **kwargs):
        raise RuntimeError('network call not expected in metadata truth test')
    return types.SimpleNamespace(post=_fail, get=_fail, Timeout=RuntimeError)


def load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='openclaw-polymarket-metadata-') as temp_dir:
        workspace_root = Path(temp_dir)
        os.environ['OPENCLAW_WORKSPACE'] = str(workspace_root)
        os.environ['OPENCLAW_TRADING_MODE'] = 'polymarket_only'
        sys.modules.pop('config.runtime', None)
        sys.modules['requests'] = fake_requests_module()

        from models.exchange_metadata import paper_exchange_is_experimental, paper_exchange_status
        from utils.runtime_logging import append_runtime_event

        scanner = load_module('phase1_signal_scanner_metadata_test', REPO_ROOT / 'scripts' / 'phase1-signal-scanner.py')
        trader = load_module('phase1_paper_trader_metadata_test', REPO_ROOT / 'scripts' / 'phase1-paper-trader.py')

        assert paper_exchange_status('Polymarket') == 'canonical'
        assert paper_exchange_is_experimental('Polymarket') is True
        assert paper_exchange_is_experimental('Hyperliquid') is False

        polymarket_signal = {
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
            'best_bid': 0.41,
            'best_ask': 0.42,
            'liquidity_usd': 20000,
            'ev_score': 9.5,
            'conviction': 'MEDIUM',
            'recommended_position_size_usd': 5.0,
            'paper_only': True,
            'experimental': True,
        }

        trade = trader.PaperTrader(polymarket_signal).execute()
        assert trade is not None
        assert trade['experimental'] is True, trade

        event = append_runtime_event(
            stage='metadata_test',
            exchange='Polymarket',
            lifecycle_stage='assertion',
            message='metadata consistency check',
        )
        assert event['experimental'] is True, event

        hl_signal = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'source': 'Hyperliquid',
            'exchange': 'Hyperliquid',
            'signal_type': 'funding_arbitrage',
            'strategy': 'funding_arbitrage',
            'asset': 'BTC',
            'symbol': 'BTC',
            'direction': 'LONG',
            'entry_price': 50000.0,
            'ev_score': 9.0,
            'conviction': 'MEDIUM',
            'recommended_position_size_usd': 1.96,
            'paper_only': True,
            'experimental': False,
        }
        hl_trade = trader.PaperTrader(hl_signal).execute()
        assert hl_trade is not None
        assert hl_trade['experimental'] is False, hl_trade

        assert scanner.CANONICAL_POSITION_SIZES['Polymarket'] == 5.00
        print('[OK] Polymarket metadata truth is aligned across exchange metadata, scanner inputs, trader outputs, and runtime events')
