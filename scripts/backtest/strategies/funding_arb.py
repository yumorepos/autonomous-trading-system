"""
Funding arbitrage strategy for backtesting.

Replicates the live trading engine's entry logic:
- Entry when abs(rate) * 24 * 365 > TIER2_MIN_FUNDING AND volume_24h > TIER2_MIN_VOLUME
- Short when funding highly positive (earn funding)
- Long when funding highly negative (earn funding)

D43: The input ``state.funding_rates[asset]`` is per-hour (Hyperliquid
``ctx['funding']``), not per-8h. The legacy name ``rate_8h`` in the code
is a misnomer preserved for diff hygiene.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.risk_params import (
    TIER1_MIN_FUNDING,
    TIER1_MIN_VOLUME,
    TIER2_MIN_FUNDING,
    TIER2_MIN_VOLUME,
    calculate_position_size,
    BACKTEST_INITIAL_CAPITAL,
)

if TYPE_CHECKING:
    from scripts.backtest.engine import MarketState


class FundingArbStrategy:
    """
    Callable strategy: strategy(market_state) -> signal dict or None.

    Scans all assets for funding rate opportunities each hour.
    Returns the highest-scoring signal (if any).
    """

    def __init__(
        self,
        min_funding_apy: float = TIER2_MIN_FUNDING,
        min_volume: float = TIER2_MIN_VOLUME,
        capital: float = BACKTEST_INITIAL_CAPITAL,
    ):
        self.min_funding_apy = min_funding_apy
        self.min_volume = min_volume
        self.capital = capital

    def __call__(self, state: MarketState) -> dict | None:
        """Evaluate all assets and return the best signal or None."""
        candidates = []

        for asset, rate_8h in state.funding_rates.items():
            if asset not in state.prices:
                continue

            # Annualized rate — D43: live HL `funding` is per-hour, not per-8h.
            # Backtest variable is named rate_8h for legacy reasons but carries
            # the same per-hour semantic as live ctx['funding']; use × 24 × 365.
            funding_annual = abs(rate_8h) * 24 * 365

            # Volume check
            volume = state.volumes_24h.get(asset, 0)

            if funding_annual < self.min_funding_apy:
                continue
            if volume < self.min_volume:
                continue

            # Direction: short when funding positive (shorts earn),
            #            long when funding negative (longs earn)
            direction = "short" if rate_8h > 0 else "long"

            # Tiered sizing
            if funding_annual >= TIER1_MIN_FUNDING and volume >= TIER1_MIN_VOLUME:
                tier = 1
                score = funding_annual * 2  # Higher weight for tier 1
            else:
                tier = 2
                score = funding_annual

            size = calculate_position_size(self.capital, tier)

            candidates.append({
                "asset": asset,
                "direction": direction,
                "position_size_usd": size,
                "score": score,
                "funding_8h": rate_8h,
                "annualized_rate": funding_annual,
                "volume_24h": volume,
                "signal_type": "funding_arbitrage",
            })

        if not candidates:
            return None

        # Return highest scoring
        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates[0]
