#!/usr/bin/env python3
"""Offline recovery proofs for malformed/drifted canonical state at the agency entrypoint."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.support.trading_agency_offline import (
    append_jsonl,
    default_hyperliquid_fixture,
    load_json,
    load_jsonl,
    run_agency_cycle,
    write_fixture,
)
from utils.json_utils import safe_read_jsonl


def hyperliquid_open_trade(*, trade_id: str, timestamp: str, entry_price: float = 50_000.0) -> dict:
    position_size_usd = 1.96
    position_size = position_size_usd / entry_price
    signal = {
        'timestamp': timestamp,
        'source': 'Hyperliquid',
        'exchange': 'Hyperliquid',
        'signal_type': 'funding_arbitrage',
        'strategy': 'funding_arbitrage',
        'asset': 'BTC',
        'symbol': 'BTC',
        'direction': 'LONG',
        'entry_price': entry_price,
        'ev_score': 12.0,
        'conviction': 'MEDIUM',
        'recommended_position_size_usd': position_size_usd,
        'paper_only': True,
        'experimental': False,
    }
    return {
        'trade_id': trade_id,
        'position_id': trade_id,
        'timestamp': timestamp,
        'entry_timestamp': timestamp,
        'entry_time': timestamp,
        'signal': signal,
        'exchange': 'Hyperliquid',
        'strategy': 'funding_arbitrage',
        'symbol': 'BTC',
        'asset': 'BTC',
        'side': 'LONG',
        'direction': 'LONG',
        'entry_price': entry_price,
        'position_size': position_size,
        'position_size_usd': position_size_usd,
        'status': 'OPEN',
        'stop_loss_pct': -10.0,
        'take_profit_pct': 10.0,
        'timeout_hours': 24.0,
        'paper_only': True,
        'experimental': False,
    }


def assert_state_recovered(runtime_events: list[dict]) -> None:
    assert any(
        event.get('stage') == 'position_state'
        and event.get('trade_lifecycle_stage') == 'state_recovered'
        and event.get('message') == 'Canonical position state synchronized from append-only trade history'
        for event in runtime_events
    ), runtime_events


def case_duplicate_entry_blocked_after_state_repair() -> None:
    with tempfile.TemporaryDirectory(prefix='openclaw-state-recovery-duplicate-') as temp_dir:
        workspace_root = Path(temp_dir)
        logs_dir = workspace_root / 'logs'
        fixture_path = workspace_root / 'offline-fixture.json'
        write_fixture(
            fixture_path,
            hyperliquid=default_hyperliquid_fixture(opportunity=True, mid_price=50_000.0),
        )

        opened_at = datetime.now(timezone.utc).isoformat()
        seed_trade = hyperliquid_open_trade(trade_id='seed-open-btc', timestamp=opened_at)
        append_jsonl(logs_dir / 'phase1-paper-trades.jsonl', [seed_trade])
        (logs_dir / 'position-state.json').parent.mkdir(parents=True, exist_ok=True)
        (logs_dir / 'position-state.json').write_text('{"broken": ')

        result = run_agency_cycle(workspace_root, fixture_path, 'hyperliquid_only')
        assert result.returncode == 0, result.stderr or result.stdout

        trades = load_jsonl(logs_dir / 'phase1-paper-trades.jsonl')
        assert len(trades) == 1, trades
        assert trades[0]['trade_id'] == 'seed-open-btc', trades

        position_state = load_json(logs_dir / 'position-state.json')
        assert list(position_state['positions']) == ['seed-open-btc'], position_state

        report = load_json(logs_dir / 'agency-phase1-report.json')
        assert report['runtime_summary']['cycle_result'] == 'ENTRY_BLOCKED', report['runtime_summary']
        assert report['execution_results']['safety_validation'] == 'FAIL', report
        assert report['current_state']['open_positions'] == 1, report['current_state']

        runtime_events = load_jsonl(logs_dir / 'runtime-events.jsonl')
        assert_state_recovered(runtime_events)


def case_exit_recovered_from_malformed_state_and_history_noise() -> None:
    with tempfile.TemporaryDirectory(prefix='openclaw-state-recovery-exit-') as temp_dir:
        workspace_root = Path(temp_dir)
        logs_dir = workspace_root / 'logs'
        fixture_path = workspace_root / 'offline-fixture.json'
        write_fixture(
            fixture_path,
            hyperliquid=default_hyperliquid_fixture(opportunity=False, mid_price=55_001.0),
        )

        opened_at = datetime.now(timezone.utc).isoformat()
        seed_trade = hyperliquid_open_trade(trade_id='seed-open-exit', timestamp=opened_at)
        append_jsonl(logs_dir / 'phase1-paper-trades.jsonl', [seed_trade])
        with open(logs_dir / 'phase1-paper-trades.jsonl', 'a') as handle:
            handle.write('{"malformed":\n')
        (logs_dir / 'position-state.json').write_text('{"broken": ')

        result = run_agency_cycle(workspace_root, fixture_path, 'hyperliquid_only')
        assert result.returncode == 0, result.stderr or result.stdout

        trades = safe_read_jsonl(logs_dir / 'phase1-paper-trades.jsonl')
        assert [trade['status'] for trade in trades] == ['OPEN', 'CLOSED'], trades
        closed_trade = trades[-1]
        assert closed_trade['trade_id'] == 'seed-open-exit', closed_trade
        assert closed_trade['exit_reason'] == 'take_profit', closed_trade
        assert closed_trade['exit_price'] == 55_001.0, closed_trade

        position_state = load_json(logs_dir / 'position-state.json')
        assert position_state['positions'] == {}, position_state

        report = load_json(logs_dir / 'agency-phase1-report.json')
        assert report['runtime_summary']['cycle_result'] == 'EXIT_EXECUTED', report['runtime_summary']
        assert report['current_state']['open_positions'] == 0, report['current_state']

        runtime_events = load_jsonl(logs_dir / 'runtime-events.jsonl')
        assert_state_recovered(runtime_events)


if __name__ == '__main__':
    case_duplicate_entry_blocked_after_state_repair()
    case_exit_recovered_from_malformed_state_and_history_noise()
    print('[OK] Canonical agency state recovery proofs passed for duplicate prevention and exit replay')
