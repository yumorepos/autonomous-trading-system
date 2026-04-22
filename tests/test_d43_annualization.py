"""D43 — Hyperliquid `funding` field is per-hour, not per-8h.

Annualizing it correctly requires × 24 × 365 = × 8760, not × 3 × 365.
These tests pin the fix at the four canonical sites so a future edit
can't silently revert to the 8h assumption (a bug that would understate
APY by a factor of 8 and let through signals worth only ~100% true APY
against a nominal 100% threshold).

Canonical sites:
    scripts/regime_detector.py:165
    scripts/trading_engine.py:804
    scripts/backtest/strategies/funding_arb.py:60
    scripts/tiered_scanner.py:78
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _make_api_response(assets: list[dict]) -> list:
    """Shape of HL metaAndAssetCtxs response used by regime_detector."""
    universe = [{"name": a["name"]} for a in assets]
    ctxs = [{"funding": a["funding"]} for a in assets]
    return [{"universe": universe}, ctxs]


def test_regime_detector_annualizes_hourly_correctly():
    """regime_detector.detect_regime_from_api_response must treat
    ``ctx['funding']`` as per-hour: APY = |funding| × 24 × 365.

    Input: funding=-0.001/hr → true APY = 8.76 (876%).
    Under the old × 3 × 365 bug: APY would be 1.095 (109.5%),
    off by a factor of 8.
    """
    from scripts.regime_detector import detect_regime_from_api_response

    resp = _make_api_response([{"name": "SYN", "funding": -0.001}])
    result = detect_regime_from_api_response(resp)

    expected_apy = 0.001 * 24 * 365  # 8.76
    assert result["max_funding_apy"] == pytest.approx(expected_apy, rel=1e-9)
    # Bug-direction guard: must exceed the old 8h value by ~8×.
    assert result["max_funding_apy"] > 0.001 * 3 * 365 * 2


def test_funding_arb_strategy_annualizes_hourly_correctly():
    """FundingArbStrategy fires at |rate| × 24 × 365, not × 3 × 365.

    Rate = 0.001/hr → APY 8.76. Threshold 7.0 must fire;
    under the old × 3 × 365 bug, APY would be 1.095 < 7.0 → silently
    rejected, which is the D43-era production behavior we're fixing.
    """
    from scripts.backtest.engine import MarketState
    from scripts.backtest.strategies.funding_arb import FundingArbStrategy

    state = MarketState(
        timestamp=0,
        prices={"SYN": {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 100.0}},
        funding_rates={"SYN": 0.001},   # per-hour positive rate → short-side opportunity
        volumes_24h={"SYN": 10_000_000.0},
    )

    # Threshold just below the post-fix APY (8.76): fix → fire, bug → reject.
    strategy = FundingArbStrategy(min_funding_apy=7.0, min_volume=0.0)
    signal = strategy(state)
    assert signal is not None, (
        "Strategy must fire at 876% APY under the × 24 × 365 fix; "
        "receiving None here means the site reverted to × 3 × 365."
    )

    # And confirm it rejects above the true APY — sanity check on the math.
    strategy_strict = FundingArbStrategy(min_funding_apy=9.0, min_volume=0.0)
    assert strategy_strict(state) is None


def _line_has_correct_annualization(source: str, substring: str) -> bool:
    """True iff ``substring`` appears in a line that uses × 24 × 365
    and does not use × 3 × 365."""
    for line in source.splitlines():
        if substring in line and "24 * 365" in line and "3 * 365" not in line:
            return True
    return False


def test_trading_engine_annualizes_hourly_correctly():
    """Live scanner in trading_engine must annualize HL funding with
    × 24 × 365. This site is reached every scanner tick (SCAN_INTERVAL_SEC)
    and feeds classify_signal → execution; a regression here silently
    undersizes the live threshold by 8×.

    Source-inspection test: unit-testing the full scanner would require
    mocking urllib, the regime state file, and the HL client. We pin the
    specific arithmetic instead.
    """
    import scripts.trading_engine as te

    source = inspect.getsource(te)
    assert _line_has_correct_annualization(source, "funding_annual = abs(funding)"), (
        "trading_engine.py must annualize `abs(funding)` with × 24 × 365 "
        "(D43 fix). If you refactored this site into a helper, update the "
        "test to target the helper instead."
    )


def test_tiered_scanner_annualizes_hourly_correctly():
    """tiered_scanner.scan_tiered must annualize HL funding with × 24 × 365.

    This is the secondary scanner path (imported by trading_engine.py:802);
    missing the fix here would reintroduce a split-brain across the two
    scanner sites.
    """
    import scripts.tiered_scanner as ts

    source = inspect.getsource(ts)
    assert _line_has_correct_annualization(source, "funding_annual = abs(funding)"), (
        "tiered_scanner.py must annualize `abs(funding)` with × 24 × 365 "
        "(D43 fix)."
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
