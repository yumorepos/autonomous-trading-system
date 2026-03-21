#!/usr/bin/env python3
"""
DESTRUCTIVE TEST -- NEVER RUN AGAINST LIVE STATE
Full Lifecycle Integration Test
Tests: Entry -> State -> Exit -> Performance -> Validator
Runs only inside a temporary workspace.
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
        'signal_type': 'funding_arbitrage',
        'asset': asset,
        'direction': direction,
        'entry_price': entry_price,
        'ev_score': ev_score,
        'conviction': 'HIGH' if ev_score > 80 else 'MEDIUM',
    }
    signals_file.parent.mkdir(parents=True, exist_ok=True)
    with open(signals_file, 'a') as handle:
        handle.write(json.dumps(signal) + '\n')
    return signal


def get_state(trades_file: Path, state_file: Path):
    if not trades_file.exists():
        return {'open': [], 'closed': [], 'all': []}

    all_trades = []
    with open(trades_file) as handle:
        for line in handle:
            if line.strip():
                all_trades.append(json.loads(line))

    state = {}
    if state_file.exists():
        with open(state_file) as handle:
            state = json.load(handle)

    open_trades = [t for t in all_trades if state.get(t.get('position_id')) == 'OPEN']
    closed_trades = [t for t in all_trades if state.get(t.get('position_id')) == 'CLOSED']
    return {'open': open_trades, 'closed': closed_trades, 'all': all_trades}


def simulate_exit(position: dict, trades_file: Path, state_file: Path, exit_price: float, reason: str):
    entry_price = position['entry_price']
    position_size = position['position_size']
    direction = position['direction']

    if direction == 'LONG':
        pnl_usd = (exit_price - entry_price) * position_size
        pnl_pct = ((exit_price - entry_price) / entry_price) * 100
    else:
        pnl_usd = (entry_price - exit_price) * position_size
        pnl_pct = ((entry_price - exit_price) / entry_price) * 100

    closed = {
        **position,
        'status': 'CLOSED',
        'exit_price': exit_price,
        'exit_time': datetime.now(timezone.utc).isoformat(),
        'exit_reason': reason,
        'realized_pnl_usd': pnl_usd,
        'realized_pnl_pct': pnl_pct,
    }
    with open(trades_file, 'a') as handle:
        handle.write(json.dumps(closed) + '\n')

    with open(state_file) as handle:
        state = json.load(handle)
    state[position['position_id']] = 'CLOSED'
    with open(state_file, 'w') as handle:
        json.dump(state, handle, indent=2)


if __name__ == '__main__':
    print('=' * 80)
    print('FULL LIFECYCLE INTEGRATION TEST')
    print('DESTRUCTIVE TEST -- NEVER RUN AGAINST LIVE STATE')
    print('=' * 80)
    print()

    with tempfile.TemporaryDirectory(prefix='openclaw-full-lifecycle-') as temp_dir:
        workspace_root = Path(temp_dir)
        logs_dir = workspace_root / 'logs'
        signals_file = logs_dir / 'phase1-signals.jsonl'
        trades_file = logs_dir / 'phase1-paper-trades.jsonl'
        state_file = logs_dir / 'position-state.json'
        perf_file = logs_dir / 'phase1-performance.json'

        trader = load_trader(workspace_root)

        inject_signal(signals_file, 'BTC', 'LONG', 50000.0, 70)
        trader.main()

        state_after_entry = get_state(trades_file, state_file)
        assert len(state_after_entry['open']) == 1, 'Expected one open position after entry'
        position = state_after_entry['open'][0]
        print(f"[OK] Entry opened: {position['position_id']}")

        simulate_exit(position, trades_file, state_file, 55000.0, 'take_profit')
        trader.main()

        final_state = get_state(trades_file, state_file)
        assert len(final_state['closed']) >= 1, 'Expected at least one closed position'
        assert perf_file.exists(), 'Expected performance file after trader rerun'
        with open(perf_file) as handle:
            perf = json.load(handle)
        assert perf.get('total_trades') == 1, 'Expected one closed trade in performance'

        print('[OK] Full lifecycle passed in isolated temp workspace')
        print(f'Workspace: {workspace_root}')
