"""Path A effective-bar preservation across the D43 annualization fix.

Before the fix:
    |rate|/hr × 3 × 365  >=  TIER2_MIN_FUNDING (1.00)
After the fix (both the × 24 × 365 annualization AND the 8× threshold retune):
    |rate|/hr × 24 × 365 >=  TIER2_MIN_FUNDING (8.00)

These two conditions are mathematically identical:
    1.00 / (3 * 365)  = 1.00 / 1095  = 0.000913242…
    8.00 / (24 * 365) = 8.00 / 8760  = 0.000913242…

So every rate that would have passed the pre-D43 nominal-100% gate
passes the post-D43 true-800% gate, and vice versa. The 8× retune is
not a change in selection criteria — it's what keeps the live filter
at the same effective bar while the APY unit is corrected.

A drift in either constant (e.g. TIER2_MIN_FUNDING retuned to 7.0 or
9.0) would quietly widen or narrow the live filter, which is the class
of error this test pins.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.risk_params import TIER1_MIN_FUNDING, TIER2_MIN_FUNDING
from config.regime_thresholds import HIGH_FUNDING_MIN_MAX_APY


# Pre-D43 canonical values (what the fix preserves against).
_PRE_D43_TIER1_MIN = 1.00
_PRE_D43_TIER2_MIN = 1.00
_PRE_D43_HIGH_FUNDING_MIN = 1.00


def test_tier1_min_funding_is_8x_pre_d43():
    assert TIER1_MIN_FUNDING == pytest.approx(_PRE_D43_TIER1_MIN * 8)


def test_tier2_min_funding_is_8x_pre_d43():
    assert TIER2_MIN_FUNDING == pytest.approx(_PRE_D43_TIER2_MIN * 8)


def test_high_funding_min_max_apy_is_8x_pre_d43():
    assert HIGH_FUNDING_MIN_MAX_APY == pytest.approx(_PRE_D43_HIGH_FUNDING_MIN * 8)


def _passes_pre_fix(rate: float) -> bool:
    """Pre-D43 gate: bug-computed 8h-annualization ≥ 1.00 decimal."""
    return (abs(rate) * 3 * 365) >= _PRE_D43_TIER2_MIN


def _passes_post_fix(rate: float) -> bool:
    """Post-D43 gate: correct 24h-annualization ≥ 8.00 decimal."""
    return (abs(rate) * 24 * 365) >= TIER2_MIN_FUNDING


def test_path_a_invariant_on_sampled_rates():
    """For 100 sampled rates in [0, 0.05], the pre-fix and post-fix gates
    must return identical boolean outcomes on every sample.

    The sample range brackets the entire realistic HL per-hour funding
    distribution (peak observed memecoins land around 0.005–0.01/hr;
    0.05/hr is ~4400% APY — beyond anything seen in production).
    """
    rng = random.Random(2026_04_22)  # deterministic — session date seed
    mismatches: list[tuple[float, bool, bool]] = []
    for _ in range(100):
        rate = rng.uniform(0.0, 0.05)
        pre = _passes_pre_fix(rate)
        post = _passes_post_fix(rate)
        if pre != post:
            mismatches.append((rate, pre, post))

    assert not mismatches, (
        f"Path A effective-bar invariant violated on {len(mismatches)} "
        f"samples (showing first 5): {mismatches[:5]}. "
        "TIER2_MIN_FUNDING and the × 24 × 365 annualization must move "
        "together: any drift in one without the other silently re-tunes "
        "the live filter."
    )


def test_path_a_invariant_on_boundary_rates():
    """The exact boundary rate (|r| = 1/1095 ≈ 0.000913) must pass both
    gates by ≥; and rates just below must fail both. Property-based
    tests can miss exact boundary values — this is the deterministic
    complement."""
    boundary = 1.0 / (3 * 365)  # ≡ 8.0 / (24 * 365)
    # At boundary: both should pass (>=).
    assert _passes_pre_fix(boundary)
    assert _passes_post_fix(boundary)
    # Slightly below: both should fail.
    below = boundary * 0.9999
    assert not _passes_pre_fix(below)
    assert not _passes_post_fix(below)
    # Slightly above: both pass.
    above = boundary * 1.0001
    assert _passes_pre_fix(above)
    assert _passes_post_fix(above)


def test_tier1_boundary_also_preserved():
    """Independently verify Tier 1 (same math, different constant)."""
    boundary = _PRE_D43_TIER1_MIN / (3 * 365)
    assert (abs(boundary) * 3 * 365) >= _PRE_D43_TIER1_MIN
    assert (abs(boundary) * 24 * 365) >= TIER1_MIN_FUNDING


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
