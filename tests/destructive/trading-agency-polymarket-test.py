#!/usr/bin/env python3
"""Offline end-to-end proof for the experimental Polymarket agency runtime."""

from __future__ import annotations

import tempfile
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.support.trading_agency_offline import (
    default_hyperliquid_fixture,
    default_polymarket_fixture,
    load_json,
    load_jsonl,
    run_agency_cycle,
    write_fixture,
)


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='openclaw-agency-pm-') as temp_dir:
        workspace_root = Path(temp_dir)
        logs_dir = workspace_root / 'logs'
        fixture_path = workspace_root / 'offline-fixture.json'

        write_fixture(
            fixture_path,
            hyperliquid=default_hyperliquid_fixture(opportunity=False),
            polymarket=default_polymarket_fixture(opportunity=True, yes_price=0.42),
        )
        cycle_one = run_agency_cycle(workspace_root, fixture_path, 'polymarket_only')
        assert cycle_one.returncode == 0, cycle_one.stderr or cycle_one.stdout

        trades_path = logs_dir / 'phase1-paper-trades.jsonl'
        positions_path = logs_dir / 'position-state.json'
        performance_path = logs_dir / 'phase1-performance.json'
        report_path = logs_dir / 'agency-phase1-report.json'
        safety_path = logs_dir / 'execution-safety-state.json'

        trades_after_entry = load_jsonl(trades_path)
        assert len(trades_after_entry) == 1, trades_after_entry
        entry_trade = trades_after_entry[0]
        assert entry_trade['status'] == 'OPEN', entry_trade
        assert entry_trade['exchange'] == 'Polymarket', entry_trade
        assert entry_trade['strategy'] == 'polymarket_spread', entry_trade
        assert entry_trade['market_id'] == 'pm-btc-up', entry_trade
        assert entry_trade['market_question'] == 'Will BTC close above 60k?', entry_trade
        assert entry_trade['token_id'] == 'pm-btc-up-YES', entry_trade
        assert entry_trade['side'] == 'YES', entry_trade
        assert entry_trade['paper_only'] is True, entry_trade
        assert entry_trade['experimental'] is True, entry_trade

        position_state = load_json(positions_path)
        open_positions = list(position_state['positions'].values())
        assert len(open_positions) == 1, open_positions
        open_position = open_positions[0]
        assert open_position['exchange'] == 'Polymarket', open_position
        assert open_position['market_id'] == 'pm-btc-up', open_position
        assert open_position['market_question'] == 'Will BTC close above 60k?', open_position
        assert open_position['token_id'] == 'pm-btc-up-YES', open_position
        assert open_position['status'] == 'OPEN', open_position

        performance_after_entry = load_json(performance_path)
        assert performance_after_entry['total_trades'] == 0, performance_after_entry

        agency_report_entry = load_json(report_path)
        assert agency_report_entry['execution_results']['bootstrap'] == 'SUCCESS', agency_report_entry
        assert agency_report_entry['execution_results']['data_integrity'] == 'SUCCESS', agency_report_entry
        assert agency_report_entry['execution_results']['signal_scanner'] == 'SUCCESS', agency_report_entry
        assert agency_report_entry['execution_results']['safety_validation'] == 'SUCCESS', agency_report_entry
        assert agency_report_entry['execution_results']['trader'] == 'SUCCESS', agency_report_entry
        assert agency_report_entry['execution_results']['authoritative_state_update'] == 'SUCCESS', agency_report_entry
        assert agency_report_entry['current_state']['open_positions'] == 1, agency_report_entry

        safety_state_after_entry = load_json(safety_path)
        assert safety_state_after_entry['runtime_enforcement']['last_transition'] == 'TRADE_OUTCOME_RECORDED', safety_state_after_entry
        assert safety_state_after_entry['runtime_enforcement']['last_persisted_trade_count'] == 1, safety_state_after_entry

        write_fixture(
            fixture_path,
            hyperliquid=default_hyperliquid_fixture(opportunity=False),
            polymarket=default_polymarket_fixture(opportunity=True, yes_price=0.48),
        )
        cycle_two = run_agency_cycle(workspace_root, fixture_path, 'polymarket_only')
        assert cycle_two.returncode == 0, cycle_two.stderr or cycle_two.stdout

        trades_after_exit = load_jsonl(trades_path)
        assert [record['status'] for record in trades_after_exit] == ['OPEN', 'CLOSED'], trades_after_exit
        closed_trade = trades_after_exit[-1]
        assert closed_trade['trade_id'] == entry_trade['trade_id'], closed_trade
        assert closed_trade['exchange'] == 'Polymarket', closed_trade
        assert closed_trade['market_id'] == 'pm-btc-up', closed_trade
        assert closed_trade['token_id'] == 'pm-btc-up-YES', closed_trade
        assert closed_trade['exit_reason'] == 'take_profit', closed_trade
        assert closed_trade['exit_price'] == 0.48, closed_trade
        assert closed_trade['realized_pnl_usd'] > 0, closed_trade

        position_state_after_exit = load_json(positions_path)
        assert position_state_after_exit['positions'] == {}, position_state_after_exit

        performance_after_exit = load_json(performance_path)
        assert performance_after_exit['total_trades'] == 1, performance_after_exit
        assert performance_after_exit['winners'] == 1, performance_after_exit
        assert performance_after_exit['exchange_breakdown']['Polymarket']['total_trades'] == 1, performance_after_exit
        assert performance_after_exit['exchange_breakdown']['Polymarket']['total_pnl_usd'] == closed_trade['realized_pnl_usd'], performance_after_exit

        agency_report_exit = load_json(report_path)
        assert agency_report_exit['execution_results']['safety_validation'] == 'SKIPPED', agency_report_exit
        assert agency_report_exit['execution_results']['trader'] == 'SUCCESS', agency_report_exit
        assert agency_report_exit['execution_results']['authoritative_state_update'] == 'SUCCESS', agency_report_exit
        assert agency_report_exit['performance_summary']['total_trades'] == 1, agency_report_exit
        assert agency_report_exit['current_state']['open_positions'] == 0, agency_report_exit

        assert 'Truthful mode status: experimental paper-trading path' in cycle_one.stdout, cycle_one.stdout
        print('[OK] Experimental Polymarket agency path proven offline with canonical persistence compatibility')
        print(f'[OK] Workspace artifact root: {workspace_root}')
