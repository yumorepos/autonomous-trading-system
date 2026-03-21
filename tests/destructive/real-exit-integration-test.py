#!/usr/bin/env python3
"""
DESTRUCTIVE TEST — NEVER RUN AGAINST LIVE STATE
Real Exit Path Integration Test
Uses actual check_exit() logic inside a temporary workspace only.
"""

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import importlib.util

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def load_trader(workspace_root: Path):
    os.environ['OPENCLAW_WORKSPACE'] = str(workspace_root)
    sys.modules.pop('config.runtime', None)
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
        'signal_type': 'funding_arbitrage',
        'asset': asset,
        'direction': direction,
        'entry_price': entry_price,
        'ev_score': ev_score,
        'conviction': 'HIGH',
    }
    signals_file.parent.mkdir(parents=True, exist_ok=True)
    with open(signals_file, 'a') as handle:
        handle.write(json.dumps(signal) + '\n')


def get_state(trades_file: Path, state_file: Path):
    if not trades_file.exists():
        return {'open': [], 'closed': [], 'all': []}

    with open(trades_file) as handle:
        all_trades = [json.loads(line) for line in handle if line.strip()]

    with open(state_file) as handle:
        state = json.load(handle)

    open_trades = [t for t in all_trades if state.get(t.get('position_id')) == 'OPEN']
    closed_trades = [t for t in all_trades if state.get(t.get('position_id')) == 'CLOSED']
    return {'open': open_trades, 'closed': closed_trades, 'all': all_trades}


if __name__ == '__main__':
    print('=' * 80)
    print('REAL EXIT PATH INTEGRATION TEST')
    print('DESTRUCTIVE TEST — NEVER RUN AGAINST LIVE STATE')
    print('=' * 80)
    print()

    with tempfile.TemporaryDirectory(prefix='openclaw-real-exit-') as temp_dir:
        workspace_root = Path(temp_dir)
        logs_dir = workspace_root / 'logs'
        signals_file = logs_dir / 'phase1-signals.jsonl'
        trades_file = logs_dir / 'phase1-paper-trades.jsonl'
        state_file = logs_dir / 'position-state.json'
        perf_file = logs_dir / 'phase1-performance.json'

        trader = load_trader(workspace_root)
        inject_signal(signals_file, 'BTC', 'LONG', 50000.0, 70)
        trader.main()

        state = get_state(trades_file, state_file)
        assert len(state['open']) == 1, 'Expected one open position after entry'
        position = state['open'][0]

        def mock_get_current_price(asset: str):
            return 57500.0 if asset == 'BTC' else 0

        trader.get_current_price = mock_get_current_price
        trader.main()

        state_after = get_state(trades_file, state_file)
        assert len(state_after['closed']) == 1, 'Expected closed position after mocked exit'
        with open(perf_file) as handle:
            perf = json.load(handle)
        assert perf.get('total_trades') == 1, 'Expected one trade in performance file'

        print(f"✅ Real exit path passed for {position['position_id']}")
        print(f'Workspace: {workspace_root}')
