#!/usr/bin/env python3
"""Negative-path coverage for operator controls in canonical agency loop."""

from __future__ import annotations

from datetime import datetime, timezone
import tempfile
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.support.trading_agency_offline import load_json, run_agency_cycle, write_fixture, write_json


def write_operator_control(path: Path, payload: dict) -> None:
    write_json(path, payload)


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='openclaw-operator-controls-') as temp_dir:
        workspace_root = Path(temp_dir)
        fixture_path = workspace_root / 'offline-fixture.json'
        write_fixture(fixture_path)

        write_operator_control(
            workspace_root / 'operator_control.json',
            {
                'manual_mode': 'INVALID',
                'trading_override': 'INVALID',
                'recovery_override': 'INVALID',
                'notes': 'invalid values should be normalized with validation errors',
                'updated_at': datetime.now(timezone.utc).isoformat(),
            },
        )

        result = run_agency_cycle(workspace_root, fixture_path, 'hyperliquid_only')
        assert result.returncode == 0, result.stderr or result.stdout
        report = load_json(workspace_root / 'logs' / 'agency-phase1-report.json')
        operator = report['current_state']['action_taken']['operator_control']
        assert operator['manual_mode'] == 'OFF', operator
        assert operator['trading_override'] == 'ALLOW', operator
        assert operator['recovery_override'] == 'AUTO', operator
        assert operator['validation_errors'], operator

    with tempfile.TemporaryDirectory(prefix='openclaw-operator-halt-') as temp_dir:
        workspace_root = Path(temp_dir)
        fixture_path = workspace_root / 'offline-fixture.json'
        write_fixture(fixture_path)

        write_operator_control(
            workspace_root / 'operator_control.json',
            {
                'manual_mode': 'ON',
                'trading_override': 'HALT_NEW_TRADES',
                'recovery_override': 'AUTO',
                'notes': 'operator hold for manual review',
                'updated_at': datetime.now(timezone.utc).isoformat(),
            },
        )

        result = run_agency_cycle(workspace_root, fixture_path, 'hyperliquid_only')
        assert result.returncode == 0, result.stderr or result.stdout
        report = load_json(workspace_root / 'logs' / 'agency-phase1-report.json')
        runtime_summary = report['runtime_summary']
        assert runtime_summary['entry_outcome']['status'] in {'blocked', 'skipped', 'not_attempted'}, runtime_summary
        assert report['current_state']['action_taken']['action'] == 'HALT_NEW_TRADES', report['current_state']['action_taken']
        assert report['current_state']['action_taken']['allow_new_trades'] is False, report['current_state']['action_taken']

    print('[OK] Operator controls are normalized and HALT_NEW_TRADES override is enforced in canonical loop')
