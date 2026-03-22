#!/usr/bin/env python3
"""Deterministic multi-cycle validation for the canonical Hyperliquid paper runtime."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.support.trading_agency_offline import load_json, load_jsonl, run_agency_cycle, write_fixture

EXPECTED_POSITION_KEYS = {
    'trade_id',
    'position_id',
    'exchange',
    'strategy',
    'symbol',
    'side',
    'direction',
    'entry_price',
    'position_size',
    'position_size_usd',
    'status',
    'entry_timestamp',
    'entry_time',
    'paper_only',
    'signal',
}


def assert_runtime_summary(report: dict, *, expected_result: str, expected_entry: str, expected_exit: str) -> None:
    runtime_summary = report['runtime_summary']
    assert runtime_summary['cycle_result'] == expected_result, runtime_summary
    assert runtime_summary['entry_outcome']['status'] == expected_entry, runtime_summary
    assert runtime_summary['exit_outcome']['status'] == expected_exit, runtime_summary
    assert runtime_summary['authoritative_files_written'], runtime_summary


def age_trade_history(path: Path) -> None:
    records = load_jsonl(path)
    if not records:
        return
    aged_records = []
    base_time = datetime.now(timezone.utc) - timedelta(minutes=10)
    for index, record in enumerate(records):
        aged = dict(record)
        entry_time = (base_time - timedelta(minutes=len(records) - index)).isoformat()
        if aged.get('entry_timestamp'):
            aged['entry_timestamp'] = entry_time
        if aged.get('entry_time'):
            aged['entry_time'] = entry_time
        if aged.get('timestamp'):
            aged['timestamp'] = entry_time
        signal = dict(aged.get('signal') or {})
        if signal.get('timestamp'):
            signal['timestamp'] = entry_time
            aged['signal'] = signal
        if aged.get('exit_timestamp'):
            exit_time = (datetime.fromisoformat(entry_time) + timedelta(minutes=1)).isoformat()
            aged['exit_timestamp'] = exit_time
            aged['exit_time'] = exit_time
        aged_records.append(aged)
    path.write_text(''.join(json.dumps(record) + '\n' for record in aged_records))


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='openclaw-repeat-cycle-') as temp_dir:
        workspace_root = Path(temp_dir)
        logs_dir = workspace_root / 'logs'
        fixture_path = workspace_root / 'offline-fixture.json'

        cycle_prices = [50_000.0, 55_001.0, 50_000.0, 55_001.0, 50_000.0, 55_001.0]
        expected_closed_trades = 0
        expected_open_positions = 0
        position_schema_keys: set[str] | None = None
        performance_totals: list[int] = []

        for cycle_number, mid_price in enumerate(cycle_prices, start=1):
            write_fixture(
                fixture_path,
                hyperliquid={
                    'universe_size': 100,
                    'signal_asset': 'BTC',
                    'entry_price': 50_000.0,
                    'funding': -0.0005,
                    'dayNtlVlm': 2_000_000.0,
                    'openInterest': 20.0,
                    'all_mids': {'BTC': mid_price},
                    'l2_books': {'BTC': {'bid': 49_990.0, 'ask': 50_010.0}},
                },
            )
            result = run_agency_cycle(workspace_root, fixture_path, 'hyperliquid_only')
            assert result.returncode == 0, result.stderr or result.stdout

            trades = load_jsonl(logs_dir / 'phase1-paper-trades.jsonl')
            position_state = load_json(logs_dir / 'position-state.json')
            performance = load_json(logs_dir / 'phase1-performance.json')
            report = load_json(logs_dir / 'agency-phase1-report.json')
            cycle_summary = load_json(logs_dir / 'agency-cycle-summary.json')
            summary_markdown = (workspace_root / 'AGENCY_CYCLE_SUMMARY.md').read_text()

            open_positions = position_state['positions']
            open_ids = list(open_positions.keys())
            assert len(open_ids) == len(set(open_ids)), open_positions
            assert len(open_positions) <= 1, open_positions

            if cycle_number % 2 == 1:
                expected_open_positions = 1
                assert len(trades) == cycle_number, trades
                assert trades[-1]['status'] == 'OPEN', trades[-1]
                assert performance['total_trades'] == expected_closed_trades, performance
                assert_runtime_summary(report, expected_result='ENTRY_EXECUTED', expected_entry='executed', expected_exit='no_open_positions')
            else:
                expected_closed_trades += 1
                expected_open_positions = 0
                assert len(trades) == cycle_number, trades
                assert trades[-1]['status'] == 'CLOSED', trades[-1]
                assert trades[-1]['exit_reason'] == 'take_profit', trades[-1]
                assert performance['total_trades'] == expected_closed_trades, performance
                assert_runtime_summary(report, expected_result='EXIT_EXECUTED', expected_entry='skipped', expected_exit='executed')

            assert len(open_positions) == expected_open_positions, position_state
            assert cycle_summary == report['runtime_summary'], (cycle_summary, report['runtime_summary'])
            assert '# Agency Cycle Summary' in summary_markdown, summary_markdown
            assert 'Authoritative Files Written' in summary_markdown, summary_markdown

            if open_positions:
                current_position = next(iter(open_positions.values()))
                current_keys = set(current_position.keys())
                assert EXPECTED_POSITION_KEYS.issubset(current_keys), current_position
                if position_schema_keys is None:
                    position_schema_keys = current_keys
                else:
                    assert current_keys == position_schema_keys, (position_schema_keys, current_keys)

            performance_totals.append(performance['total_trades'])
            age_trade_history(logs_dir / 'phase1-paper-trades.jsonl')

        assert performance_totals == [0, 1, 1, 2, 2, 3], performance_totals
        trades = load_jsonl(logs_dir / 'phase1-paper-trades.jsonl')
        assert len(trades) == 6, trades
        assert sum(1 for trade in trades if trade['status'] == 'OPEN') == 3, trades
        assert sum(1 for trade in trades if trade['status'] == 'CLOSED') == 3, trades
        final_performance = load_json(logs_dir / 'phase1-performance.json')
        assert final_performance['winners'] == 3, final_performance
        assert final_performance['exchange_breakdown']['Hyperliquid']['total_trades'] == 3, final_performance

        print('[OK] Deterministic Hyperliquid repeat-cycle validation passed')
        print(f'[OK] Workspace artifact root: {workspace_root}')
