#!/usr/bin/env python3
"""Verify timeout monitoring uses Polymarket-specific paper thresholds."""

import importlib.util
import os
import sys
import tempfile
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def load_module(workspace_root: Path):
    os.environ['OPENCLAW_WORKSPACE'] = str(workspace_root)
    sys.modules.pop('config.runtime', None)
    sys.modules['requests'] = types.SimpleNamespace(post=lambda *args, **kwargs: None, get=lambda *args, **kwargs: None, Timeout=RuntimeError)
    spec = importlib.util.spec_from_file_location('timeout_monitor_threshold_test', REPO_ROOT / 'scripts' / 'timeout-monitor.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules['timeout_monitor_threshold_test'] = module
    spec.loader.exec_module(module)
    return module


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='openclaw-timeout-') as temp_dir:
        module = load_module(Path(temp_dir))
        monitor = module.TimeoutMonitor()
        probabilities = monitor.calculate_exit_probabilities_with_thresholds(
            pnl_pct=8.5,
            age_hours=1,
            pnl_trend={'trend': 'improving', 'volatility': 2.0},
            timeout_hours=24.0,
            take_profit_pct=8.0,
            stop_loss_pct=-8.0,
        )

        assert module.EXCHANGE_THRESHOLDS['Polymarket']['take_profit_pct'] == 8.0, module.EXCHANGE_THRESHOLDS
        assert module.EXCHANGE_THRESHOLDS['Hyperliquid']['take_profit_pct'] == 10.0, module.EXCHANGE_THRESHOLDS
        assert probabilities['most_likely'] == 'take_profit', probabilities
        print('[OK] Timeout monitor exposes consistent exchange-specific threshold support')
