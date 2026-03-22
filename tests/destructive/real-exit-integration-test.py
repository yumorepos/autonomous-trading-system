#!/usr/bin/env python3
"""
DESTRUCTIVE TEST -- NEVER RUN AGAINST LIVE STATE
Real Exit Path Integration Test
Uses actual check_exit/build_execution_plan logic inside a temporary workspace only.
"""

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
        raise RuntimeError('network call not expected in isolated real-exit test')
    return types.SimpleNamespace(post=_fail, get=_fail, Timeout=RuntimeError)



def load_trader(workspace_root: Path):
    os.environ['OPENCLAW_WORKSPACE'] = str(workspace_root)
    os.environ['OPENCLAW_TRADING_MODE'] = 'hyperliquid_only'
    sys.modules.pop('config.runtime', None)
    sys.modules['requests'] = fake_requests_module()
    spec = importlib.util.spec_from_file_location(
        'phase1_paper_trader_real_exit',
        REPO_ROOT / 'scripts' / 'phase1-paper-trader.py'
    )
    trader = importlib.util.module_from_spec(spec)
    sys.modules['phase1_paper_trader_real_exit'] = trader
    spec.loader.exec_module(trader)
    return trader



def inject_signal(signals_file: Path, asset: str, direction: str, entry_price: float, ev_score: float):
    signal = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'source': 'Hyperliquid',
        'exchange': 'Hyperliquid',
        'signal_type': 'funding_arbitrage',
        'strategy': 'funding_arbitrage',
        'asset': asset,
        'symbol': asset,
        'direction': direction,
        'entry_price': entry_price,
        'ev_score': ev_score,
        'conviction': 'HIGH',
        'recommended_position_size_usd': 1.96,
        'paper_only': True,
        'experimental': False,
    }
    signals_file.parent.mkdir(parents=True, exist_ok=True)
    with open(signals_file, 'a') as handle:
        handle.write(json.dumps(signal) + '\n')


if __name__ == '__main__':
    print('=' * 80)
    print('REAL EXIT PATH INTEGRATION TEST')
    print('DESTRUCTIVE TEST -- NEVER RUN AGAINST LIVE STATE')
    print('=' * 80)
    print()

    with tempfile.TemporaryDirectory(prefix='openclaw-real-exit-') as temp_dir:
        workspace_root = Path(temp_dir)
        logs_dir = workspace_root / 'logs'
        signals_file = logs_dir / 'phase1-signals.jsonl'
        perf_file = logs_dir / 'phase1-performance.json'

        trader = load_trader(workspace_root)
        inject_signal(signals_file, 'BTC', 'LONG', 50000.0, 70)
        trader.main()

        open_positions = trader.load_open_positions()
        assert len(open_positions) == 1, 'Expected one open position after entry'
        position = open_positions[0]

        trader.get_position_current_price = lambda position: 57500.0 if position.get('symbol') == 'BTC' else 0
        should_exit, exit_reason = trader.check_exit(position)
        assert should_exit is True and exit_reason == 'take_profit', 'Expected take_profit exit trigger'

        plan = trader.build_execution_plan(allow_new_entries=False)
        assert len(plan['planned_closes']) == 1, 'Expected one planned close'
        assert plan['planned_closes'][0]['exchange'] == 'Hyperliquid'
        trader.persist_trade_records(plan['planned_closes'])
        perf = trader.calculate_performance()

        assert len(trader.load_open_positions()) == 0, 'Expected no open positions after persisting close'
        assert perf.get('total_trades') == 1, 'Expected one trade in performance file'
        with open(perf_file) as handle:
            perf_file_payload = json.load(handle)
        assert perf_file_payload.get('exchange_breakdown', {}).get('Hyperliquid', {}).get('total_trades') == 1

        print(f"[OK] Real exit path passed for {position['trade_id']}")
        print(f'Workspace: {workspace_root}')
