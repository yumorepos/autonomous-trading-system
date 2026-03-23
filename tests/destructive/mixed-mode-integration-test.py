#!/usr/bin/env python3
"""Offline isolated mixed-mode canonical state integrity test."""

import json
import os
import sys
import tempfile
import types
from datetime import datetime, timezone
from pathlib import Path
import importlib.util

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def fake_requests_module():
    def _fail(*args, **kwargs):
        raise RuntimeError('network call not expected in isolated mixed-mode test')
    return types.SimpleNamespace(post=_fail, get=_fail, Timeout=RuntimeError)



def load_trader(workspace_root: Path):
    os.environ['OPENCLAW_WORKSPACE'] = str(workspace_root)
    os.environ['OPENCLAW_TRADING_MODE'] = 'mixed'
    sys.modules.pop('config.runtime', None)
    sys.modules['requests'] = fake_requests_module()
    spec = importlib.util.spec_from_file_location('phase1_paper_trader_mixed', REPO_ROOT / 'scripts' / 'phase1-paper-trader.py')
    trader = importlib.util.module_from_spec(spec)
    sys.modules['phase1_paper_trader_mixed'] = trader
    spec.loader.exec_module(trader)
    return trader


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='openclaw-mixed-mode-') as temp_dir:
        workspace_root = Path(temp_dir)
        logs_dir = workspace_root / 'logs'
        signals_file = logs_dir / 'phase1-signals.jsonl'
        trader = load_trader(workspace_root)

        now = datetime.now(timezone.utc)
        signals = [
            {
                'timestamp': now.isoformat(),
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
                'timestamp': (now.replace(microsecond=1)).isoformat(),
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
        signals_file.parent.mkdir(parents=True, exist_ok=True)
        with open(signals_file, 'a') as handle:
            for signal in signals:
                handle.write(json.dumps(signal) + '\n')

        first_plan = trader.build_execution_plan()
        trader.persist_trade_records(first_plan['planned_trades'])
        second_plan = trader.build_execution_plan()
        trader.persist_trade_records(second_plan['planned_trades'])

        open_positions = trader.load_open_positions()
        exchanges = {position['exchange'] for position in open_positions}
        assert exchanges == {'Hyperliquid', 'Polymarket'}, f'Expected mixed open positions, got {exchanges}'
        assert len(open_positions) == 2, f'Expected 2 open positions, got {len(open_positions)}'
        print('[OK] Mixed mode keeps canonical state intact across exchanges')
