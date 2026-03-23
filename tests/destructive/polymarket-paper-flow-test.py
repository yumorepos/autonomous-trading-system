#!/usr/bin/env python3
"""DESTRUCTIVE TEST -- isolated canonical Polymarket paper flow."""

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
        raise RuntimeError('network call not expected in isolated polymarket test')
    return types.SimpleNamespace(post=_fail, get=_fail, Timeout=RuntimeError)



def load_trader(workspace_root: Path):
    os.environ['OPENCLAW_WORKSPACE'] = str(workspace_root)
    os.environ['OPENCLAW_TRADING_MODE'] = 'polymarket_only'
    sys.modules.pop('config.runtime', None)
    sys.modules['requests'] = fake_requests_module()
    spec = importlib.util.spec_from_file_location('phase1_paper_trader_polymarket', REPO_ROOT / 'scripts' / 'phase1-paper-trader.py')
    trader = importlib.util.module_from_spec(spec)
    sys.modules['phase1_paper_trader_polymarket'] = trader
    spec.loader.exec_module(trader)
    return trader


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='openclaw-pm-flow-') as temp_dir:
        workspace_root = Path(temp_dir)
        logs_dir = workspace_root / 'logs'
        signals_file = logs_dir / 'phase1-signals.jsonl'
        trader = load_trader(workspace_root)

        signal = {
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
        signals_file.parent.mkdir(parents=True, exist_ok=True)
        with open(signals_file, 'a') as handle:
            handle.write(json.dumps(signal) + '\n')

        trader.main()
        open_positions = trader.load_open_positions()
        assert len(open_positions) == 1, 'Expected one Polymarket open position'
        assert open_positions[0]['exchange'] == 'Polymarket'
        assert open_positions[0]['market_id'] == 'pm-btc-up'
        assert open_positions[0]['experimental'] is True

        trader.get_position_current_price = lambda position: 0.48
        plan = trader.build_execution_plan(allow_new_entries=False)
        assert len(plan['planned_closes']) == 1, 'Expected one Polymarket planned close'
        trader.persist_trade_records(plan['planned_closes'])
        perf = trader.calculate_performance()

        assert len(trader.load_open_positions()) == 0, 'Expected Polymarket open state cleared after close'
        assert perf.get('exchange_breakdown', {}).get('Polymarket', {}).get('total_trades') == 1
        assert not (REPO_ROOT / 'scripts' / 'polymarket-executor.py').exists(), 'Legacy helper path should be removed'
        print('[OK] Polymarket paper flow passed')
