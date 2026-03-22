#!/usr/bin/env python3
"""Operator-safe deterministic soak validation for the canonical Hyperliquid paper runtime."""

from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.support.trading_agency_offline import load_json, load_jsonl, run_agency_cycle, write_fixture


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cycles', type=int, default=12, help='Number of deterministic cycles to run (default: 12)')
    parser.add_argument('--workspace', type=Path, default=None, help='Optional workspace root for artifacts')
    return parser.parse_args()


def hyperliquid_fixture(mid_price: float) -> dict:
    return {
        'universe_size': 100,
        'signal_asset': 'BTC',
        'entry_price': 50_000.0,
        'funding': -0.0005,
        'dayNtlVlm': 2_000_000.0,
        'openInterest': 20.0,
        'all_mids': {'BTC': mid_price},
        'l2_books': {'BTC': {'bid': 49_990.0, 'ask': 50_010.0}},
    }


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


def run_soak(workspace_root: Path, cycles: int) -> dict:
    fixture_path = workspace_root / 'offline-fixture.json'
    logs_dir = workspace_root / 'logs'
    history = []
    expected_total_trades = 0

    for cycle_number in range(1, cycles + 1):
        mid_price = 50_000.0 if cycle_number % 2 == 1 else 55_001.0
        write_fixture(fixture_path, hyperliquid=hyperliquid_fixture(mid_price))
        result = run_agency_cycle(workspace_root, fixture_path, 'hyperliquid_only')
        if result.returncode != 0:
            raise RuntimeError(result.stderr or result.stdout)

        performance = load_json(logs_dir / 'phase1-performance.json')
        position_state = load_json(logs_dir / 'position-state.json')
        report = load_json(logs_dir / 'agency-phase1-report.json')
        cycle_summary = load_json(logs_dir / 'agency-cycle-summary.json')
        trades = load_jsonl(logs_dir / 'phase1-paper-trades.jsonl')
        open_positions = position_state['positions']

        if cycle_number % 2 == 0:
            expected_total_trades += 1

        assert performance['total_trades'] == expected_total_trades, performance
        assert len(open_positions) <= 1, open_positions
        assert len(open_positions.keys()) == len(set(open_positions.keys())), open_positions
        assert cycle_summary == report['runtime_summary'], (cycle_summary, report['runtime_summary'])
        history.append({
            'cycle': cycle_number,
            'mid_price': mid_price,
            'cycle_result': cycle_summary['cycle_result'],
            'entry_status': cycle_summary['entry_outcome']['status'],
            'exit_status': cycle_summary['exit_outcome']['status'],
            'closed_trades': performance['total_trades'],
            'open_positions': len(open_positions),
            'trade_log_records': len(trades),
        })
        age_trade_history(logs_dir / 'phase1-paper-trades.jsonl')

    final_performance = load_json(logs_dir / 'phase1-performance.json')
    summary = {
        'workspace': str(workspace_root),
        'cycles': cycles,
        'closed_trades': final_performance['total_trades'],
        'winners': final_performance.get('winners', 0),
        'final_open_positions': len(load_json(logs_dir / 'position-state.json')['positions']),
        'history': history,
    }
    output_path = workspace_root / 'HYPERLIQUID_OFFLINE_SOAK_SUMMARY.json'
    output_path.write_text(json.dumps(summary, indent=2))
    return summary


if __name__ == '__main__':
    args = parse_args()
    if args.workspace is not None:
        workspace_root = args.workspace.resolve()
        workspace_root.mkdir(parents=True, exist_ok=True)
        summary = run_soak(workspace_root, args.cycles)
    else:
        with tempfile.TemporaryDirectory(prefix='openclaw-hl-soak-') as temp_dir:
            workspace_root = Path(temp_dir)
            summary = run_soak(workspace_root, args.cycles)

    print('[OK] Hyperliquid offline soak validation complete')
    print(json.dumps(summary, indent=2))
