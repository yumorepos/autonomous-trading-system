#!/usr/bin/env python3
"""Verify execution safety normalizes recent trades before duplicate-order checks."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
    with tempfile.TemporaryDirectory(prefix='openclaw-safety-schema-') as temp_dir:
        workspace_root = Path(temp_dir)
        logs_dir = workspace_root / 'logs'
        trades_file = logs_dir / 'phase1-paper-trades.jsonl'
        trades_file.parent.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)

        os.environ['OPENCLAW_WORKSPACE'] = str(workspace_root)
        os.environ['OPENCLAW_TRADING_MODE'] = 'mixed'
        sys.modules.pop('config.runtime', None)
        sys.modules['requests'] = types.SimpleNamespace(post=lambda *args, **kwargs: None, get=lambda *args, **kwargs: None, Timeout=RuntimeError)

        records = [
            {
                'trade_id': 'hl-open-1',
                'exchange': 'Hyperliquid',
                'strategy': 'funding_arbitrage',
                'symbol': 'BTC',
                'side': 'LONG',
                'entry_price': 50000.0,
                'position_size': 0.0000392,
                'position_size_usd': 1.96,
                'status': 'OPEN',
                'entry_timestamp': (now - timedelta(seconds=30)).isoformat(),
            },
            {
                'trade_id': 'pm-open-1',
                'exchange': 'Polymarket',
                'strategy': 'polymarket_spread',
                'symbol': 'pm-btc-up',
                'side': 'YES',
                'entry_price': 0.42,
                'position_size': 11.9,
                'position_size_usd': 5.0,
                'status': 'OPEN',
                'entry_timestamp': (now - timedelta(seconds=20)).isoformat(),
                'market_id': 'pm-btc-up',
                'market_question': 'Will BTC close above 60k?',
                'token_id': 'yes-token',
            },
        ]

        with open(trades_file, 'w') as handle:
            for record in records:
                handle.write(json.dumps(record) + '\n')

        module = load_module('execution_safety_schema_test', REPO_ROOT / 'scripts' / 'execution-safety-layer.py')
        safety = module.ExecutionSafetyLayer()
        assert len(safety.recent_trades) == 2, safety.recent_trades

        hl_result = safety.check_duplicate_order(
            module.TradeProposal(
                exchange='Hyperliquid',
                strategy='funding_arbitrage',
                asset='BTC',
                direction='LONG',
                entry_price=50000.0,
                position_size_usd=1.96,
                signal_timestamp=now.isoformat(),
                allocation_weight=0.02,
            )
        )
        assert hl_result.passed is False, hl_result

        pm_result = safety.check_duplicate_order(
            module.TradeProposal(
                exchange='Polymarket',
                strategy='polymarket_spread',
                asset='pm-btc-up',
                direction='YES',
                entry_price=0.42,
                position_size_usd=5.0,
                signal_timestamp=now.isoformat(),
                allocation_weight=0.02,
            )
        )
        assert pm_result.passed is False, pm_result

        no_dup_result = safety.check_duplicate_order(
            module.TradeProposal(
                exchange='Hyperliquid',
                strategy='funding_arbitrage',
                asset='BTC',
                direction='SHORT',
                entry_price=50000.0,
                position_size_usd=1.96,
                signal_timestamp=now.isoformat(),
                allocation_weight=0.02,
            )
        )
        assert no_dup_result.passed is True, no_dup_result

        print('[OK] Execution safety duplicate-order checks use normalized canonical trades and tolerate missing nested signal payloads')
