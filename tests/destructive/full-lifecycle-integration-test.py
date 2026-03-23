#!/usr/bin/env python3
"""
OFFLINE ISOLATED WORKSPACE TEST
Full Lifecycle Paper-Flow Test
Verifies canonical Hyperliquid entry -> canonical state -> actual close -> performance
inside an isolated temporary workspace with mocked market data.
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
        raise RuntimeError('network call not expected in isolated lifecycle test')
    return types.SimpleNamespace(post=_fail, get=_fail, Timeout=RuntimeError)



def load_trader(workspace_root: Path):
    os.environ['OPENCLAW_WORKSPACE'] = str(workspace_root)
    os.environ['OPENCLAW_TRADING_MODE'] = 'hyperliquid_only'
    sys.modules.pop('config.runtime', None)
    sys.modules['requests'] = fake_requests_module()
    spec = importlib.util.spec_from_file_location(
        'phase1_paper_trader',
        REPO_ROOT / 'scripts' / 'phase1-paper-trader.py'
    )
    trader = importlib.util.module_from_spec(spec)
    sys.modules['phase1_paper_trader'] = trader
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
        'conviction': 'HIGH' if ev_score > 80 else 'MEDIUM',
        'recommended_position_size_usd': 1.96,
        'paper_only': True,
        'experimental': False,
    }
    signals_file.parent.mkdir(parents=True, exist_ok=True)
    with open(signals_file, 'a') as handle:
        handle.write(json.dumps(signal) + '\n')
    return signal



def load_trade_log(trades_file: Path):
    if not trades_file.exists():
        return []
    with open(trades_file) as handle:
        return [json.loads(line) for line in handle if line.strip()]


if __name__ == '__main__':
    print('=' * 80)
    print('FULL LIFECYCLE PAPER-FLOW TEST')
    print('OFFLINE ISOLATED WORKSPACE -- DOES NOT TOUCH LIVE STATE')
    print('=' * 80)
    print()

    with tempfile.TemporaryDirectory(prefix='openclaw-full-lifecycle-') as temp_dir:
        workspace_root = Path(temp_dir)
        logs_dir = workspace_root / 'logs'
        signals_file = logs_dir / 'phase1-signals.jsonl'
        trades_file = logs_dir / 'phase1-paper-trades.jsonl'
        perf_file = logs_dir / 'phase1-performance.json'

        trader = load_trader(workspace_root)

        inject_signal(signals_file, 'BTC', 'LONG', 50000.0, 70)
        trader.main()

        open_positions = trader.load_open_positions()
        assert len(open_positions) == 1, 'Expected one canonical open position after entry'
        position = open_positions[0]
        assert position['status'] == 'OPEN'
        assert position['exchange'] == 'Hyperliquid'
        print(f"[OK] Entry opened: {position['trade_id']}")

        trader.get_position_current_price = lambda position: 55000.0 if position.get('symbol') == 'BTC' else 0
        trader.main()

        open_after = trader.load_open_positions()
        assert len(open_after) == 0, 'Expected canonical open positions cleared after exit'

        trade_log = load_trade_log(trades_file)
        statuses = [record['status'] for record in trade_log]
        assert statuses == ['OPEN', 'CLOSED'], f'Expected OPEN then CLOSED trade records, got {statuses}'
        assert perf_file.exists(), 'Expected performance file after close'
        with open(perf_file) as handle:
            perf = json.load(handle)
        assert perf.get('total_trades') == 1, 'Expected one closed trade in performance'
        assert perf.get('exchange_breakdown', {}).get('Hyperliquid', {}).get('total_trades') == 1

        print('[OK] Full lifecycle passed in isolated temp workspace')
        print(f'Workspace: {workspace_root}')
