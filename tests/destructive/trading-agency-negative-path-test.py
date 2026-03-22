#!/usr/bin/env python3
"""Offline negative-path proofs for the canonical trading agency entrypoint."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.support.trading_agency_offline import (
    append_jsonl,
    load_json,
    load_jsonl,
    run_agency_cycle,
    write_fixture,
)


def signal(*, timestamp: str, price: float = 50_000.0, size_usd: float = 1.96, **overrides) -> dict:
    payload = {
        'timestamp': timestamp,
        'source': 'Hyperliquid',
        'exchange': 'Hyperliquid',
        'signal_type': 'funding_arbitrage',
        'strategy': 'funding_arbitrage',
        'asset': 'BTC',
        'symbol': 'BTC',
        'direction': 'LONG',
        'entry_price': price,
        'ev_score': 8.0,
        'conviction': 'MEDIUM',
        'recommended_position_size_usd': size_usd,
        'paper_only': True,
        'experimental': False,
    }
    payload.update(overrides)
    return payload


def open_trade(*, trade_id: str, timestamp: str, asset: str = 'BTC', direction: str = 'LONG') -> dict:
    trade_signal = signal(timestamp=timestamp, price=50_000.0, asset=asset, symbol=asset, direction=direction)
    return {
        'trade_id': trade_id,
        'position_id': trade_id,
        'timestamp': timestamp,
        'entry_timestamp': timestamp,
        'entry_time': timestamp,
        'signal': trade_signal,
        'exchange': 'Hyperliquid',
        'strategy': 'funding_arbitrage',
        'symbol': asset,
        'asset': asset,
        'side': direction,
        'direction': direction,
        'entry_price': 50_000.0,
        'position_size': 0.0000392,
        'position_size_usd': 1.96,
        'status': 'OPEN',
        'paper_only': True,
    }


def closed_loss(*, trade_id: str, entry_time: str, exit_time: str, loss_usd: float) -> dict:
    record = open_trade(trade_id=trade_id, timestamp=entry_time)
    record.update({
        'status': 'CLOSED',
        'exit_timestamp': exit_time,
        'exit_time': exit_time,
        'exit_price': 49_000.0,
        'exit_reason': 'stop_loss',
        'realized_pnl_usd': -abs(loss_usd),
        'realized_pnl_pct': -10.0,
    })
    return record


def write_position_state(path: Path, trades: list[dict]) -> None:
    positions = {}
    for trade in trades:
        positions[trade['trade_id']] = {
            'trade_id': trade['trade_id'],
            'position_id': trade['trade_id'],
            'exchange': 'Hyperliquid',
            'strategy': 'funding_arbitrage',
            'symbol': trade['symbol'],
            'side': trade['side'],
            'direction': trade['side'],
            'entry_price': trade['entry_price'],
            'position_size': trade['position_size'],
            'position_size_usd': trade['position_size_usd'],
            'status': 'OPEN',
            'entry_timestamp': trade['entry_timestamp'],
            'entry_time': trade['entry_time'],
            'paper_only': True,
            'signal': trade['signal'],
        }
    payload = {
        'schema_version': '2.0',
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'positions': positions,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def assert_no_new_trade(workspace_root: Path, *, reason_fragment: str, safety_status: str, expected_transition: str | None = None) -> None:
    logs_dir = workspace_root / 'logs'
    trades = load_jsonl(logs_dir / 'phase1-paper-trades.jsonl')
    report = load_json(logs_dir / 'agency-phase1-report.json')
    assert report['execution_results']['safety_validation'] == safety_status, report
    assert reason_fragment in report['execution_reasons']['safety_validation'], report['execution_reasons']['safety_validation']
    if expected_transition is not None:
        safety_state = load_json(logs_dir / 'execution-safety-state.json')
        assert safety_state['runtime_enforcement']['last_transition'] == expected_transition, safety_state
    # No authoritative state update for new trades in negative-path scenarios.
    open_positions = (load_json(logs_dir / 'position-state.json')['positions'] if (logs_dir / 'position-state.json').exists() else {})
    if safety_status != 'FAIL':
        assert len(open_positions) <= 3, open_positions
    if expected_transition == 'BLOCKED_TRADE':
        blocked_actions = load_jsonl(logs_dir / 'blocked-actions.jsonl')
        assert blocked_actions, 'blocked-actions.jsonl should record the safety rejection'
        assert reason_fragment in blocked_actions[-1]['reason'], blocked_actions[-1]
    assert report['execution_results']['authoritative_state_update'] == 'SKIPPED', report
    # Negative-path tests should not append a fresh OPEN trade record beyond any seeded fixtures.
    assert all(record.get('status') != 'OPEN' or record.get('trade_id', '').startswith('seed-') for record in trades), trades


def case_stale_signal() -> None:
    with tempfile.TemporaryDirectory(prefix='openclaw-negative-stale-') as temp_dir:
        workspace_root = Path(temp_dir)
        logs_dir = workspace_root / 'logs'
        fixture_path = workspace_root / 'offline-fixture.json'
        write_fixture(fixture_path)
        append_jsonl(
            logs_dir / 'phase1-signals.jsonl',
            [signal(timestamp=(datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat())],
        )
        result = run_agency_cycle(workspace_root, fixture_path, 'hyperliquid_only')
        assert result.returncode == 0, result.stderr or result.stdout
        assert_no_new_trade(
            workspace_root,
            reason_fragment='Signal age',
            safety_status='FAIL',
            expected_transition='BLOCKED_TRADE',
        )


def case_duplicate_entry() -> None:
    with tempfile.TemporaryDirectory(prefix='openclaw-negative-duplicate-') as temp_dir:
        workspace_root = Path(temp_dir)
        logs_dir = workspace_root / 'logs'
        fixture_path = workspace_root / 'offline-fixture.json'
        write_fixture(fixture_path)
        now = datetime.now(timezone.utc)
        seeded_open = open_trade(trade_id='seed-open-duplicate', timestamp=(now - timedelta(seconds=15)).isoformat())
        append_jsonl(logs_dir / 'phase1-paper-trades.jsonl', [seeded_open])
        append_jsonl(logs_dir / 'phase1-signals.jsonl', [signal(timestamp=now.isoformat())])
        result = run_agency_cycle(workspace_root, fixture_path, 'hyperliquid_only')
        assert result.returncode == 0, result.stderr or result.stdout
        assert_no_new_trade(
            workspace_root,
            reason_fragment='duplicate open orders',
            safety_status='FAIL',
            expected_transition='BLOCKED_TRADE',
        )


def case_circuit_breaker_halt() -> None:
    with tempfile.TemporaryDirectory(prefix='openclaw-negative-breaker-') as temp_dir:
        workspace_root = Path(temp_dir)
        logs_dir = workspace_root / 'logs'
        fixture_path = workspace_root / 'offline-fixture.json'
        write_fixture(fixture_path)
        now = datetime.now(timezone.utc)
        losses = []
        for index in range(5):
            entry_time = (now - timedelta(minutes=25 - index)).isoformat()
            exit_time = (now - timedelta(minutes=20 - index)).isoformat()
            losses.append(closed_loss(trade_id=f'seed-loss-{index}', entry_time=entry_time, exit_time=exit_time, loss_usd=1.0))
        append_jsonl(logs_dir / 'phase1-paper-trades.jsonl', losses)
        append_jsonl(logs_dir / 'phase1-signals.jsonl', [signal(timestamp=now.isoformat())])
        result = run_agency_cycle(workspace_root, fixture_path, 'hyperliquid_only')
        assert result.returncode == 0, result.stderr or result.stdout
        assert_no_new_trade(
            workspace_root,
            reason_fragment='consecutive losses',
            safety_status='FAIL',
            expected_transition='BLOCKED_TRADE',
        )
        safety_state = load_json(logs_dir / 'execution-safety-state.json')
        assert safety_state['status'] == 'HALT', safety_state


def case_invalid_signal() -> None:
    with tempfile.TemporaryDirectory(prefix='openclaw-negative-invalid-') as temp_dir:
        workspace_root = Path(temp_dir)
        logs_dir = workspace_root / 'logs'
        fixture_path = workspace_root / 'offline-fixture.json'
        write_fixture(fixture_path)
        bad_signal = signal(
            timestamp=datetime.now(timezone.utc).isoformat(),
            signal_type='wrong_signal_type',
        )
        bad_signal.pop('asset')
        bad_signal.pop('symbol')
        append_jsonl(logs_dir / 'phase1-signals.jsonl', [bad_signal])
        result = run_agency_cycle(workspace_root, fixture_path, 'hyperliquid_only')
        assert result.returncode == 0, result.stderr or result.stdout
        report = load_json(logs_dir / 'agency-phase1-report.json')
        events = load_jsonl(logs_dir / 'runtime-events.jsonl')
        assert report['execution_results']['safety_validation'] == 'SKIPPED', report
        assert report['execution_results']['authoritative_state_update'] == 'SKIPPED', report
        assert not (logs_dir / 'blocked-actions.jsonl').exists(), 'Malformed signal should be rejected before blocked-actions logging'
        assert any(
            event.get('stage') == 'paper_trader'
            and event.get('trade_lifecycle_stage') == 'validation_skipped'
            and 'Non-canonical paper-trading signal skipped' in event.get('message', '')
            and 'wrong_signal_type' in event.get('message', '')
            for event in events
        ), events
        trades = load_jsonl(logs_dir / 'phase1-paper-trades.jsonl')
        assert trades == [], trades


def case_position_limit() -> None:
    with tempfile.TemporaryDirectory(prefix='openclaw-negative-capacity-') as temp_dir:
        workspace_root = Path(temp_dir)
        logs_dir = workspace_root / 'logs'
        fixture_path = workspace_root / 'offline-fixture.json'
        write_fixture(fixture_path)
        now = datetime.now(timezone.utc)
        open_positions = [
            open_trade(trade_id=f'seed-open-{index}', timestamp=(now - timedelta(minutes=index + 1)).isoformat(), asset=f'ASSET{index}')
            for index in range(3)
        ]
        append_jsonl(logs_dir / 'phase1-paper-trades.jsonl', open_positions)
        write_position_state(logs_dir / 'position-state.json', open_positions)
        append_jsonl(logs_dir / 'phase1-signals.jsonl', [signal(timestamp=now.isoformat(), asset='BTC', symbol='BTC')])
        result = run_agency_cycle(workspace_root, fixture_path, 'hyperliquid_only')
        assert result.returncode == 0, result.stderr or result.stdout
        report = load_json(logs_dir / 'agency-phase1-report.json')
        trades = load_jsonl(logs_dir / 'phase1-paper-trades.jsonl')
        position_state = load_json(logs_dir / 'position-state.json')
        assert report['execution_results']['safety_validation'] == 'SKIPPED', report
        assert 'At capacity (3/3)' in report['execution_reasons']['safety_validation'], report['execution_reasons']['safety_validation']
        assert report['execution_results']['authoritative_state_update'] == 'SKIPPED', report
        assert len(trades) == 3, trades
        assert len(position_state['positions']) == 3, position_state


if __name__ == '__main__':
    case_stale_signal()
    case_duplicate_entry()
    case_circuit_breaker_halt()
    case_invalid_signal()
    case_position_limit()
    print('[OK] Trading agency negative-path reliability proofs passed offline')
