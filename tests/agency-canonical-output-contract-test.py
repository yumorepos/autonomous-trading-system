#!/usr/bin/env python3
"""Guard authoritative vs advisory file classification in agency runtime summaries."""

from __future__ import annotations

import tempfile
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.support.trading_agency_offline import (
    default_hyperliquid_fixture,
    default_polymarket_fixture,
    load_json,
    run_agency_cycle,
    write_fixture,
)


AUTHORITATIVE_KINDS = {'signal_history', 'trade_history', 'open_position_state', 'performance_summary'}
ADVISORY_KINDS = {'safety_state', 'timeout_history', 'timeout_report', 'agency_cycle_summary', 'agency_cycle_summary_markdown'}


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='openclaw-agency-contract-') as temp_dir:
        workspace_root = Path(temp_dir)
        logs_dir = workspace_root / 'logs'
        fixture_path = workspace_root / 'offline-fixture.json'

        write_fixture(
            fixture_path,
            hyperliquid=default_hyperliquid_fixture(opportunity=True, mid_price=50_000.0),
            polymarket=default_polymarket_fixture(opportunity=False),
        )
        result = run_agency_cycle(workspace_root, fixture_path, 'hyperliquid_only')
        assert result.returncode == 0, result.stderr or result.stdout

        summary = load_json(logs_dir / 'agency-cycle-summary.json')
        authoritative = summary.get('authoritative_files_written', [])
        advisory = summary.get('advisory_files_written', [])

        authoritative_kinds = {item['kind'] for item in authoritative}
        advisory_kinds = {item['kind'] for item in advisory}

        assert authoritative_kinds.issubset(AUTHORITATIVE_KINDS), authoritative
        assert 'safety_state' not in authoritative_kinds, authoritative
        assert 'agency_report' not in authoritative_kinds, authoritative
        assert {'signal_history', 'trade_history', 'open_position_state', 'performance_summary'}.issubset(authoritative_kinds), authoritative

        assert 'safety_state' in advisory_kinds, advisory
        assert 'agency_cycle_summary' in advisory_kinds, advisory
        assert 'agency_cycle_summary_markdown' in advisory_kinds, advisory
        assert advisory_kinds.issubset(ADVISORY_KINDS), advisory

        print('[OK] Agency runtime summary keeps authoritative trade/state outputs separate from advisory artifacts')
