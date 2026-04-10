"""
RISK PARAMETERS — SINGLE SOURCE OF TRUTH

Every risk threshold, position sizing parameter, and circuit breaker limit
lives HERE. All other modules import from this file. No hardcoded thresholds
anywhere else in the codebase.

To change a parameter: edit this file, restart the engine.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Exit Thresholds
# ---------------------------------------------------------------------------

STOP_LOSS_ROE = -0.07            # -7% ROE (force-mode exit, unblockable)
TAKE_PROFIT_ROE = 0.10           # +10% ROE
TRAILING_STOP_ACTIVATE = 0.02    # Activate trailing at +2% ROE
TRAILING_STOP_DISTANCE = 0.02    # Trail 2% behind peak ROE
TIMEOUT_HOURS = 8                # Max hold time (hours)

# ---------------------------------------------------------------------------
# Position Sizing
# ---------------------------------------------------------------------------

RISK_PER_TRADE_PCT = 0.05        # Risk 5% of capital per trade
MIN_POSITION_USD = 10.0          # Hyperliquid minimum effective size
MAX_EXPOSURE_PER_TRADE = 20.0    # Per-trade max (USD)
MAX_CONCURRENT = 5               # Max simultaneous positions
MAX_EXPOSURE_PCT = 0.50          # 50% of capital max deployed
LEVERAGE = 3                     # Default leverage on HL

# Tier multipliers (Tier 1 gets more capital than Tier 2)
TIER_MULTIPLIERS = {1: 1.5, 2: 1.0}

# ---------------------------------------------------------------------------
# Scanner Thresholds
# ---------------------------------------------------------------------------

TIER1_MIN_FUNDING = 1.00         # 100% annualized
TIER1_MIN_PREMIUM = -0.01        # -1%
TIER1_MIN_VOLUME = 1_000_000     # $1M daily volume

TIER2_MIN_FUNDING = 0.75         # 75% annualized
TIER2_MIN_PREMIUM = -0.005       # -0.5%
TIER2_MIN_VOLUME = 500_000       # $500K daily volume

# ---------------------------------------------------------------------------
# Circuit Breakers
# ---------------------------------------------------------------------------

CIRCUIT_BREAKER_LOSSES = 3       # Halt after N consecutive losses
DRAWDOWN_PCT = 0.15              # 15% drawdown from peak = full stop
MAX_SLIPPAGE = 0.03              # 3% max slippage

# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------

LOOP_INTERVAL_SEC = 1.0          # Main loop tick (seconds)
SCAN_INTERVAL_SEC = 120          # Scanner rate limit (seconds) — was 300
EXECUTION_COOLDOWN_SEC = 120     # Min gap between same-coin exits

# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------

BACKTEST_INITIAL_CAPITAL = 1000.0

# ---------------------------------------------------------------------------
# Sizing Function
# ---------------------------------------------------------------------------

def calculate_position_size(account_balance: float, tier: int) -> float:
    """Calculate position size in USD based on current capital and signal tier.

    Scales with account balance so positions grow as capital compounds.
    Respects min/max bounds and per-position exposure limits.
    """
    base = account_balance * RISK_PER_TRADE_PCT
    multiplier = TIER_MULTIPLIERS.get(tier, 1.0)
    size = base * multiplier

    # Clamp to bounds
    size = max(size, MIN_POSITION_USD)
    size = min(size, MAX_EXPOSURE_PER_TRADE)
    size = min(size, account_balance * MAX_EXPOSURE_PCT / MAX_CONCURRENT)

    return round(size, 2)
