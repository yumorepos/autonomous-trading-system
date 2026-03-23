#!/usr/bin/env python3
"""Guard the active repo truth surface against overclaims."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

ACTIVE_FILES = {
    'README.md': REPO_ROOT / 'README.md',
    'PROOF_MATRIX.md': REPO_ROOT / 'PROOF_MATRIX.md',
    'SYSTEM_STATUS.md': REPO_ROOT / 'SYSTEM_STATUS.md',
    'scripts/trading-agency-phase1.py': REPO_ROOT / 'scripts' / 'trading-agency-phase1.py',
}


def read(path: Path) -> str:
    return path.read_text()


if __name__ == '__main__':
    readme = read(ACTIVE_FILES['README.md'])
    proof = read(ACTIVE_FILES['PROOF_MATRIX.md'])
    system_status = read(ACTIVE_FILES['SYSTEM_STATUS.md'])
    agency = read(ACTIVE_FILES['scripts/trading-agency-phase1.py'])

    assert 'canonical paper-trading path:** Hyperliquid' in readme, readme
    assert 'canonical paper-trading path:** Polymarket' in readme, readme
    assert 'not live-ready' not in readme.lower(), 'README should avoid ambiguous live-ready phrasing and state exact paper-only truth'
    assert 'real-money execution:** not supported' in readme, readme

    assert 'Proven at the paper-trading level' in proof, proof
    assert 'does not prove live readiness' in proof, proof
    assert 'deterministic single-entry selection, Hyperliquid preferred' in proof, proof
    assert 'advisory-only secondary-source health' in proof, proof

    assert 'canonical Hyperliquid and Polymarket paper paths' in system_status, system_status
    assert 'Polymarket experimental overall' in system_status, system_status
    assert 'live trading is not implemented' in system_status, system_status
    assert 'real-money execution' not in system_status.lower() or 'not supported' in readme.lower()

    assert agency.count('Truthful mode status: canonical paper-trading path') >= 2, agency
    assert 'experimental mixed-mode evaluation; not the canonical proof path' in agency, agency

    print('[OK] Active truth surfaces preserve canonical paper-trading wording for Hyperliquid and Polymarket')
