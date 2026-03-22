#!/usr/bin/env python3
"""Guard Polymarket against non-canonical helper fallbacks."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


if __name__ == '__main__':
    helper_path = REPO_ROOT / 'scripts' / 'polymarket-executor.py'
    assert not helper_path.exists(), helper_path

    active_paths = [
        REPO_ROOT / 'scripts' / 'trading-agency-phase1.py',
        REPO_ROOT / 'scripts' / 'phase1-paper-trader.py',
        REPO_ROOT / 'scripts' / 'execution-safety-layer.py',
        REPO_ROOT / 'README.md',
        REPO_ROOT / 'SYSTEM_STATUS.md',
        REPO_ROOT / 'PROOF_MATRIX.md',
    ]
    for path in active_paths:
        text = path.read_text()
        assert 'polymarket-executor.py' not in text, f'{path} still references helper path'

    print('[OK] Polymarket canonical path guard passed with no helper fallback surface')
