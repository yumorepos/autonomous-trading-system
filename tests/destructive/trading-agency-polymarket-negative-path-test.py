#!/usr/bin/env python3
"""Offline negative-path proofs for the canonical Polymarket agency runtime."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.support.trading_agency_offline import (
    append_jsonl,
    default_hyperliquid_fixture,
    default_polymarket_fixture,
    load_json,
    load_jsonl,
    run_agency_cycle,
    write_fixture,
)


def polymarket_signal(*, timestamp: str, market_id: str = 'pm-btc-up', token_id: str = 'pm-btc-up-YES', side: str = 'YES') -> dict:
    return {
        'timestamp': timestamp,
        'source': 'Polymarket',
        'exchange': 'Polymarket',
        'signal_type': 'polymarket_binary_market',
        'strategy': 'polymarket_spread',
        'asset': market_id,
        'symbol': market_id,
        'market_id': market_id,
        'market_question': 'Will BTC close above 60k?',
        'side': side,
        'direction': side,
        'token_id': token_id,
        'entry_price': 0.42,
        'ev_score': 12.0,
        'conviction': 'HIGH',
        'recommended_position_size_usd': 5.0,
        'paper_only': True,
        'experimental': True,
    }


def polymarket_open_trade(*, trade_id: str, timestamp: str, market_id: str = 'pm-btc-up', token_id: str = 'pm-btc-up-YES', side: str = 'YES') -> dict:
    signal = polymarket_signal(timestamp=timestamp, market_id=market_id, token_id=token_id, side=side)
    return {
        'trade_id': trade_id,
        'position_id': trade_id,
        'timestamp': timestamp,
        'entry_timestamp': timestamp,
        'entry_time': timestamp,
        'signal': signal,
        'exchange': 'Polymarket',
        'strategy': 'polymarket_spread',
        'symbol': market_id,
        'asset': market_id,
        'market_id': market_id,
        'market_question': signal['market_question'],
        'token_id': token_id,
        'side': side,
        'direction': side,
        'entry_price': 0.42,
        'position_size': 11.9047619,
        'position_size_usd': 5.0,
        'status': 'OPEN',
        'paper_only': True,
        'experimental': True,
    }


def assert_no_new_polymarket_trade(workspace_root: Path) -> None:
    trades = load_jsonl(workspace_root / 'logs' / 'phase1-paper-trades.jsonl')
    assert all(record.get('trade_id', '').startswith('seed-') for record in trades), trades


def case_stale_polymarket_signal() -> None:
    with tempfile.TemporaryDirectory(prefix='openclaw-pm-negative-stale-') as temp_dir:
        workspace_root = Path(temp_dir)
        logs_dir = workspace_root / 'logs'
        fixture_path = workspace_root / 'offline-fixture.json'
        write_fixture(
            fixture_path,
            hyperliquid=default_hyperliquid_fixture(opportunity=False),
        )
        append_jsonl(
            logs_dir / 'phase1-signals.jsonl',
            [polymarket_signal(timestamp=(datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat())],
        )

        result = run_agency_cycle(workspace_root, fixture_path, 'polymarket_only')
        assert result.returncode == 0, result.stderr or result.stdout

        report = load_json(logs_dir / 'agency-phase1-report.json')
        blocked = load_jsonl(logs_dir / 'blocked-actions.jsonl')
        assert report['execution_results']['signal_scanner'] == 'SUCCESS', report
        assert report['execution_results']['safety_validation'] == 'FAIL', report
        assert 'Signal age' in report['execution_reasons']['safety_validation'], report['execution_reasons']['safety_validation']
        assert report['runtime_summary']['cycle_result'] == 'ENTRY_BLOCKED', report['runtime_summary']
        assert blocked[-1]['proposal']['exchange'] == 'Polymarket', blocked[-1]
        assert 'Signal age' in blocked[-1]['reason'], blocked[-1]
        assert_no_new_polymarket_trade(workspace_root)


def case_duplicate_polymarket_entry() -> None:
    with tempfile.TemporaryDirectory(prefix='openclaw-pm-negative-duplicate-') as temp_dir:
        workspace_root = Path(temp_dir)
        logs_dir = workspace_root / 'logs'
        fixture_path = workspace_root / 'offline-fixture.json'
        write_fixture(
            fixture_path,
            hyperliquid=default_hyperliquid_fixture(opportunity=False),
            polymarket=default_polymarket_fixture(opportunity=True),
        )
        now = datetime.now(timezone.utc)
        append_jsonl(
            logs_dir / 'phase1-paper-trades.jsonl',
            [polymarket_open_trade(trade_id='seed-pm-open-duplicate', timestamp=(now - timedelta(seconds=15)).isoformat())],
        )

        result = run_agency_cycle(workspace_root, fixture_path, 'polymarket_only')
        assert result.returncode == 0, result.stderr or result.stdout

        report = load_json(logs_dir / 'agency-phase1-report.json')
        blocked = load_jsonl(logs_dir / 'blocked-actions.jsonl')
        assert report['execution_results']['signal_scanner'] == 'SUCCESS', report
        assert report['execution_results']['safety_validation'] == 'FAIL', report
        assert 'duplicate open orders' in report['execution_reasons']['safety_validation'], report['execution_reasons']['safety_validation']
        assert blocked[-1]['proposal']['exchange'] == 'Polymarket', blocked[-1]
        assert 'duplicate open orders' in blocked[-1]['reason'], blocked[-1]
        assert_no_new_polymarket_trade(workspace_root)


def assert_scanner_rejects_invalid_polymarket_fixture(polymarket_fixture: dict, *, workspace_prefix: str) -> None:
    with tempfile.TemporaryDirectory(prefix=workspace_prefix) as temp_dir:
        workspace_root = Path(temp_dir)
        logs_dir = workspace_root / 'logs'
        fixture_path = workspace_root / 'offline-fixture.json'
        write_fixture(
            fixture_path,
            hyperliquid=default_hyperliquid_fixture(opportunity=False),
            polymarket=polymarket_fixture,
        )

        result = run_agency_cycle(workspace_root, fixture_path, 'polymarket_only')
        assert result.returncode == 0, result.stderr or result.stdout

        report = load_json(logs_dir / 'agency-phase1-report.json')
        runtime_events = load_jsonl(logs_dir / 'runtime-events.jsonl')
        signals = load_jsonl(logs_dir / 'phase1-signals.jsonl')
        trades = load_jsonl(logs_dir / 'phase1-paper-trades.jsonl')
        assert report['execution_results']['safety_validation'] == 'SKIPPED', report
        assert report['execution_results']['trader'] == 'SKIPPED', report
        assert report['execution_results']['authoritative_state_update'] == 'SKIPPED', report
        assert report['current_state']['latest_signals_count'] == 0, report['current_state']
        assert signals == [], signals
        assert trades == [], trades

        if report['execution_results']['signal_scanner'] == 'SUCCESS':
            assert report['runtime_summary']['cycle_result'] == 'NO_ACTION', report['runtime_summary']
            assert any(
                event.get('stage') == 'signal_scanner'
                and event.get('exchange') == 'Polymarket'
                and event.get('message') == 'Polymarket scan completed with 0 paper-trading signal(s)'
                for event in runtime_events
            ), runtime_events
        else:
            assert report['execution_results']['signal_scanner'] == 'SKIPPED', report
            assert report['execution_results']['data_integrity'] == 'FAIL', report
            assert report['execution_reasons']['signal_scanner'] == 'Blocked by data integrity failure', report['execution_reasons']
            assert report['runtime_summary']['cycle_result'] == 'FAILED', report['runtime_summary']


def case_missing_token_metadata() -> None:
    assert_scanner_rejects_invalid_polymarket_fixture(
        {
            'markets': [
                {
                    'conditionId': 'pm-bad-token-meta-1',
                    'question': 'Broken token metadata example 1?',
                    'liquidity': 25000,
                    'tokens': [
                        {'outcome': None, 'token_id': None, 'bestBid': 0.41, 'bestAsk': 0.42, 'price': 0.42},
                        {'outcome': '', 'token_id': None, 'bestBid': 0.58, 'bestAsk': 0.59, 'price': 0.59},
                    ],
                },
                {
                    'conditionId': 'pm-bad-token-meta-2',
                    'question': 'Broken token metadata example 2?',
                    'liquidity': 24000,
                    'tokens': [
                        {'outcome': None, 'token_id': None, 'bestBid': 0.40, 'bestAsk': 0.41, 'price': 0.41},
                        {'outcome': 'maybe', 'token_id': None, 'bestBid': 0.59, 'bestAsk': 0.60, 'price': 0.60},
                    ],
                },
                {
                    'conditionId': 'pm-bad-token-meta-3',
                    'question': 'Broken token metadata example 3?',
                    'liquidity': 23000,
                    'tokens': [
                        {'outcome': 'UP', 'token_id': None, 'bestBid': 0.39, 'bestAsk': 0.40, 'price': 0.40},
                        {'outcome': 'DOWN', 'token_id': None, 'bestBid': 0.60, 'bestAsk': 0.61, 'price': 0.61},
                    ],
                },
            ]
        },
        workspace_prefix='openclaw-pm-negative-token-meta-',
    )


def case_invalid_market_payload() -> None:
    assert_scanner_rejects_invalid_polymarket_fixture(
        {
            'markets': [
                {
                    'conditionId': 'pm-one-sided-market',
                    'question': 'One sided payload should be ignored?',
                    'liquidity': 25000,
                    'tokens': [
                        {'outcome': 'YES', 'token_id': 'yes-only', 'bestBid': 0.41, 'bestAsk': 0.42, 'price': 0.42},
                    ],
                },
                {
                    'conditionId': 'pm-zero-price-market',
                    'question': 'Zero-price payload should be ignored?',
                    'liquidity': 25000,
                    'tokens': [
                        {'outcome': 'YES', 'token_id': 'yes-zero', 'bestBid': 0.0, 'bestAsk': 0.0, 'price': 0.0},
                        {'outcome': 'NO', 'token_id': 'no-zero', 'bestBid': 0.0, 'bestAsk': 0.0, 'price': 0.0},
                    ],
                },
                {
                    'conditionId': 'pm-bad-spread-market',
                    'question': 'Negative spread payload should be ignored?',
                    'liquidity': 25000,
                    'tokens': [
                        {'outcome': 'YES', 'token_id': 'yes-bad', 'bestBid': -1.0, 'bestAsk': -1.0, 'price': -1.0},
                        {'outcome': 'NO', 'token_id': 'no-bad', 'bestBid': -1.0, 'bestAsk': -1.0, 'price': -1.0},
                    ],
                },
            ]
        },
        workspace_prefix='openclaw-pm-negative-market-payload-',
    )


if __name__ == '__main__':
    case_stale_polymarket_signal()
    case_duplicate_polymarket_entry()
    case_missing_token_metadata()
    case_invalid_market_payload()
    print('[OK] Polymarket negative-path proofs passed offline')
