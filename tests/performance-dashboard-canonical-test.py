#!/usr/bin/env python3
"""Verify the dashboard reads mixed-mode results from canonical trade history."""

import importlib.util
import json
import os
import sys
import tempfile
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='openclaw-dashboard-') as temp_dir:
        workspace_root = Path(temp_dir)
        os.environ['OPENCLAW_WORKSPACE'] = str(workspace_root)
        os.environ['OPENCLAW_TRADING_MODE'] = 'mixed'
        sys.modules.pop('config.runtime', None)
        sys.modules['requests'] = types.SimpleNamespace(post=lambda *args, **kwargs: None, get=lambda *args, **kwargs: None, Timeout=RuntimeError)

        trader = load_module('performance_dashboard_test_trader', REPO_ROOT / 'scripts' / 'phase1-paper-trader.py')
        trade_log = workspace_root / 'logs' / 'phase1-paper-trades.jsonl'
        trade_log.parent.mkdir(parents=True, exist_ok=True)

        records = [
            {
                'trade_id': 'hl-1',
                'symbol': 'BTC',
                'side': 'LONG',
                'entry_price': 100.0,
                'position_size': 1.0,
                'position_size_usd': 100.0,
                'status': 'OPEN',
                'entry_timestamp': '2026-01-01T00:00:00+00:00',
                'exchange': 'Hyperliquid',
            },
            {
                'trade_id': 'hl-1',
                'symbol': 'BTC',
                'side': 'LONG',
                'entry_price': 100.0,
                'exit_price': 110.0,
                'position_size': 1.0,
                'position_size_usd': 100.0,
                'realized_pnl_usd': 10.0,
                'realized_pnl_pct': 10.0,
                'status': 'CLOSED',
                'exit_reason': 'take_profit',
                'entry_timestamp': '2026-01-01T00:00:00+00:00',
                'exit_timestamp': '2026-01-01T01:00:00+00:00',
                'exchange': 'Hyperliquid',
            },
            {
                'trade_id': 'pm-1',
                'symbol': 'pm-btc-up',
                'side': 'YES',
                'entry_price': 0.4,
                'position_size': 10.0,
                'position_size_usd': 4.0,
                'status': 'OPEN',
                'entry_timestamp': '2026-01-01T00:00:00+00:00',
                'exchange': 'Polymarket',
                'market_id': 'pm-btc-up',
                'market_question': 'Will BTC close above 60k?',
            },
            {
                'trade_id': 'pm-1',
                'symbol': 'pm-btc-up',
                'side': 'YES',
                'entry_price': 0.4,
                'exit_price': 0.5,
                'position_size': 10.0,
                'position_size_usd': 4.0,
                'realized_pnl_usd': 1.0,
                'realized_pnl_pct': 25.0,
                'status': 'CLOSED',
                'exit_reason': 'take_profit',
                'entry_timestamp': '2026-01-01T00:00:00+00:00',
                'exit_timestamp': '2026-01-01T01:00:00+00:00',
                'exchange': 'Polymarket',
                'market_id': 'pm-btc-up',
                'market_question': 'Will BTC close above 60k?',
            },
        ]

        with open(trade_log, 'w') as handle:
            for record in records:
                handle.write(json.dumps(record) + '\n')
                trader.apply_trade_to_position_state(trader.POSITION_STATE_FILE, record)

        dashboard_module = load_module('performance_dashboard_test', REPO_ROOT / 'scripts' / 'support' / 'performance-dashboard.py')
        dashboard = dashboard_module.PerformanceDashboard()

        assert dashboard.calculate_stats(dashboard.hl_trades)['closed'] == 1
        assert dashboard.calculate_stats(dashboard.pm_trades)['closed'] == 1
        assert len(dashboard.open_positions) == 0

        print('[OK] Performance dashboard reads canonical mixed-mode trade history')
