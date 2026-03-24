#!/usr/bin/env python3
"""Verify canonical paper-account state is rebuilt from append-only closed trades."""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='openclaw-paper-account-') as temp_dir:
        workspace_root = Path(temp_dir)
        logs_dir = workspace_root / 'logs'
        logs_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)

        trades = [
            {
                'trade_id': 'win-1',
                'exchange': 'Hyperliquid',
                'strategy': 'funding_arbitrage',
                'symbol': 'BTC',
                'side': 'LONG',
                'entry_price': 50000.0,
                'position_size': 0.0000392,
                'position_size_usd': 1.96,
                'status': 'CLOSED',
                'entry_timestamp': (now - timedelta(minutes=10)).isoformat(),
                'exit_timestamp': (now - timedelta(minutes=9)).isoformat(),
                'exit_price': 50100.0,
                'exit_reason': 'take_profit',
                'realized_pnl_usd': 1.0,
                'realized_pnl_pct': 5.0,
            },
            {
                'trade_id': 'loss-1',
                'exchange': 'Hyperliquid',
                'strategy': 'funding_arbitrage',
                'symbol': 'ETH',
                'side': 'SHORT',
                'entry_price': 3000.0,
                'position_size': 0.00065,
                'position_size_usd': 1.95,
                'status': 'CLOSED',
                'entry_timestamp': (now - timedelta(minutes=8)).isoformat(),
                'exit_timestamp': (now - timedelta(minutes=7)).isoformat(),
                'exit_price': 3015.0,
                'exit_reason': 'stop_loss',
                'realized_pnl_usd': -0.4,
                'realized_pnl_pct': -2.0,
            },
        ]

        with open(logs_dir / 'phase1-paper-trades.jsonl', 'w') as handle:
            for trade in trades:
                handle.write(json.dumps(trade) + '\n')

        os.environ['OPENCLAW_WORKSPACE'] = str(workspace_root)
        module = load_module('paper_account_test_module', REPO_ROOT / 'models' / 'paper_account.py')
        state = module.synchronize_paper_account_state(logs_dir / 'paper-account.json', logs_dir / 'phase1-paper-trades.jsonl')

        assert state['starting_balance_usd'] == 97.8, state
        assert state['balance_usd'] == 98.4, state
        assert state['peak_balance_usd'] == 98.8, state
        assert state['realized_pnl_usd'] == 0.6, state
        assert state['closed_trades_count'] == 2, state

    print('[OK] Paper-account state is synchronized from canonical append-only trade history')
