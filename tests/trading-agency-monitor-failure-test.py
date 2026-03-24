#!/usr/bin/env python3
"""Prove canonical monitor-stage failure handling is truthful."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
import sys

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
    module = load_module('trading_agency_monitor_failure_test', REPO_ROOT / 'scripts' / 'trading-agency-phase1.py')

    timeout_result = module.subprocess.TimeoutExpired(cmd=['python3', 'scripts/timeout-monitor.py'], timeout=90)

    def raise_timeout(*args, **kwargs):
        raise timeout_result

    original_run = module.subprocess.run
    module.subprocess.run = raise_timeout
    try:
        timed_out = module.run_timeout_monitor()
    finally:
        module.subprocess.run = original_run

    assert timed_out['status'] == module.StageStatus.FAIL.value, timed_out
    assert 'exceeded 90s runtime budget' in timed_out['reason'], timed_out

    def forced_failure():
        return {
            'script': 'timeout-monitor.py',
            'status': module.StageStatus.FAIL.value,
            'reason': 'intentional monitor failure for offline proof',
            'summary': {'history_records_before': 0, 'history_records_after': 0, 'history_records_added': 0},
            'stdout': '',
            'stderr': 'forced failure',
            'command': ['python3', 'scripts/timeout-monitor.py'],
        }

    original_timeout_monitor = module.run_timeout_monitor
    module.run_timeout_monitor = forced_failure
    try:
        monitor_stage = module.evaluate_monitor_scripts()
    finally:
        module.run_timeout_monitor = original_timeout_monitor

    assert monitor_stage.status == module.StageStatus.FAIL.value, monitor_stage
    assert 'Failures' in monitor_stage.reason, monitor_stage.reason
    assert 'timeout-monitor.py' in monitor_stage.reason, monitor_stage.reason
    assert 'exit-monitor.py' in monitor_stage.reason, monitor_stage.reason

    print('[OK] Monitor-stage failures/timeouts are explicit and do not imply canonical state persistence')
