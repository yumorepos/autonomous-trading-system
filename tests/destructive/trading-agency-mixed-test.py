#!/usr/bin/env python3
"""Offline truth-enforcement proof for mixed mode at the agency entrypoint."""

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
    with tempfile.TemporaryDirectory(prefix='openclaw-agency-mixed-') as temp_dir:
        workspace_root = Path(temp_dir)
        logs_dir = workspace_root / 'logs'
        fixture_path = workspace_root / 'offline-fixture.json'

        write_fixture(
            fixture_path,
            hyperliquid=default_hyperliquid_fixture(opportunity=True, mid_price=50_000.0),
            polymarket=default_polymarket_fixture(opportunity=True, yes_price=0.42),
        )
        result = run_agency_cycle(workspace_root, fixture_path, 'mixed')
        assert result.returncode == 0, result.stderr or result.stdout

        trades = load_jsonl(logs_dir / 'phase1-paper-trades.jsonl')
        report = load_json(logs_dir / 'agency-phase1-report.json')
        signals = load_jsonl(logs_dir / 'phase1-signals.jsonl')
        positions = list(load_json(logs_dir / 'position-state.json')['positions'].values())

        assert len(signals) >= 2, signals
        exchanges_seen = {signal['exchange'] for signal in signals}
        assert {'Hyperliquid', 'Polymarket'}.issubset(exchanges_seen), exchanges_seen

        assert len(trades) == 1, trades
        assert len(positions) == 1, positions
        assert trades[0]['exchange'] == 'Hyperliquid', trades
        assert positions[0]['exchange'] == 'Hyperliquid', positions
        assert 'current deterministic mixed-mode priority winner' in report['execution_reasons']['safety_validation'], report
        assert report['execution_results']['trader'] == 'SUCCESS', report
        assert report['execution_results']['authoritative_state_update'] == 'SUCCESS', report
        assert report['current_state']['open_positions'] == 1, report
        assert 'experimental mixed-mode evaluation; not the canonical proof path' in result.stdout, result.stdout

        print('[OK] Mixed-mode agency proof confirms the current limitation: one canonical entry per cycle, not dual-entry side-by-side execution')
        print(f'[OK] Signals observed: {sorted(exchanges_seen)} | persisted trades: {len(trades)}')
