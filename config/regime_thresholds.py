"""
REGIME THRESHOLDS — Dynamic scanner thresholds based on market regime.

The regime detector classifies the market into one of 4 regimes.
Each regime adjusts ENTRY thresholds only — exit params (SL, TP, timeout)
are backtest-validated and NEVER change.

Imported by tiered_scanner.py and regime_detector.py.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Regime Classification Thresholds
# ---------------------------------------------------------------------------

# What percentage of assets must have >100% APY funding to trigger EXTREME
EXTREME_PCT_ABOVE_100 = 0.10        # 10% of assets

# Minimum max funding APY (as decimal, 1.50 = 150%) for HIGH_FUNDING
HIGH_FUNDING_MIN_MAX_APY = 1.50     # At least one asset at 150%+ APY

# Minimum max funding APY for MODERATE
MODERATE_MIN_MAX_APY = 0.75         # At least one asset at 75%+ APY

# Below MODERATE → LOW_FUNDING (current state, wait patiently)

# ---------------------------------------------------------------------------
# Hysteresis: EXIT thresholds (to downgrade from a regime)
# ---------------------------------------------------------------------------
# To ENTER a regime (upgrade) we use the thresholds above.
# To EXIT a regime (downgrade) the metric must drop further, creating a
# dead zone that prevents oscillation around a boundary.

REGIME_EXIT_THRESHOLDS: dict[str, dict] = {
    "EXTREME":      {"pct_above_100": 0.05},       # must drop to 5%, not just below 10%
    "HIGH_FUNDING": {"max_funding_apy": 1.20},      # must drop to 120%, not just below 150%
    "MODERATE":     {"max_funding_apy": 0.60},       # must drop to 60%, not just below 75%
    "LOW_FUNDING":  {},                              # can't downgrade further
}


# ---------------------------------------------------------------------------
# Scanner Thresholds Per Regime
# ---------------------------------------------------------------------------
# Only ENTRY thresholds change. Exit params are fixed (backtest-validated).

REGIME_THRESHOLDS: dict[str, dict] = {
    "EXTREME": {
        "tier1_min_funding": 0.75,      # Lower bar — lots of opportunities
        "tier2_min_funding": 0.50,      # Accept more signals
        "max_concurrent": 3,            # Allow more positions
    },
    "HIGH_FUNDING": {
        "tier1_min_funding": 1.00,      # Current default
        "tier2_min_funding": 0.75,      # Slightly below current
        "max_concurrent": 2,            # Current default
    },
    "MODERATE": {
        "tier1_min_funding": 1.50,      # Higher bar — be more selective
        "tier2_min_funding": 1.00,      # Only strong signals
        "max_concurrent": 1,            # Conservative
    },
    "LOW_FUNDING": {
        "tier1_min_funding": 2.00,      # Very high bar — only extremes
        "tier2_min_funding": 1.50,      # Reject almost everything
        "max_concurrent": 1,            # Minimal exposure
    },
}

# Fallback regime if state file is missing or stale (>4 hours)
DEFAULT_REGIME = "HIGH_FUNDING"

# How long before regime state is considered stale (seconds)
REGIME_STALE_SECONDS = 4 * 3600      # 4 hours


def get_regime_thresholds(regime: str) -> dict:
    """Get scanner thresholds for a given regime.

    Falls back to HIGH_FUNDING defaults if regime is unknown.
    """
    return REGIME_THRESHOLDS.get(regime, REGIME_THRESHOLDS[DEFAULT_REGIME])
