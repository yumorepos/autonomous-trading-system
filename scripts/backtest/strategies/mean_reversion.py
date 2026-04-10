"""
Mean reversion strategy for backtesting.

Entry logic:
- Compute z-score: z = (close - SMA_24h) / rolling_std_24h
- Long when z < -threshold (price crashed below mean)
- Short when z > +threshold (price spiked above mean)
- Volume filter: only trade assets with 24h volume > min_volume
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import TYPE_CHECKING

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.risk_params import (
    BACKTEST_INITIAL_CAPITAL,
    calculate_position_size,
)

if TYPE_CHECKING:
    from scripts.backtest.engine import MarketState


class MeanReversionStrategy:
    """
    Callable strategy: strategy(market_state) -> signal dict or None.

    Requires market_data reference to compute lookback SMA/std.
    """

    def __init__(
        self,
        market_data: dict[str, dict[int, dict]] | None = None,
        z_threshold: float = 2.0,
        lookback: int = 24,
        min_volume: float = 200_000,
        capital: float = BACKTEST_INITIAL_CAPITAL,
    ):
        self.market_data = market_data or {}
        self.z_threshold = z_threshold
        self.lookback = lookback
        self.min_volume = min_volume
        self.capital = capital
        # Pre-sort timestamps per asset for fast lookback
        self._sorted_ts: dict[str, list[int]] = {}
        for asset, candles in self.market_data.items():
            self._sorted_ts[asset] = sorted(candles.keys())

    def _get_lookback_closes(self, asset: str, current_ts: int) -> list[float]:
        """Get the last `lookback` close prices up to and including current_ts."""
        sorted_ts = self._sorted_ts.get(asset, [])
        if not sorted_ts:
            return []

        # Binary search for current_ts position
        lo, hi = 0, len(sorted_ts)
        while lo < hi:
            mid = (lo + hi) // 2
            if sorted_ts[mid] <= current_ts:
                lo = mid + 1
            else:
                hi = mid
        # lo is now the index after current_ts
        end_idx = lo
        start_idx = max(0, end_idx - self.lookback)

        closes = []
        candles = self.market_data[asset]
        for i in range(start_idx, end_idx):
            ts = sorted_ts[i]
            closes.append(candles[ts]["close"])
        return closes

    def __call__(self, state: MarketState) -> dict | None:
        """Evaluate all assets and return the best mean-reversion signal or None."""
        candidates = []

        for asset in state.prices:
            candle = state.prices[asset]
            close = candle.get("close")
            if not close:
                continue

            # Volume filter
            volume = state.volumes_24h.get(asset, 0)
            if volume < self.min_volume:
                continue

            # Get lookback closes
            closes = self._get_lookback_closes(asset, state.timestamp)
            if len(closes) < self.lookback:
                continue

            # Compute SMA and std
            sma = sum(closes) / len(closes)
            variance = sum((c - sma) ** 2 for c in closes) / len(closes)
            std = math.sqrt(variance) if variance > 0 else 0.0

            if std == 0:
                continue

            z_score = (close - sma) / std

            if abs(z_score) < self.z_threshold:
                continue

            # Direction
            direction = "long" if z_score < 0 else "short"

            size = calculate_position_size(self.capital, 2)

            candidates.append({
                "asset": asset,
                "direction": direction,
                "entry_price": close,
                "position_size_usd": size,
                "score": abs(z_score),
                "z_score": z_score,
                "tier": 2,
                "signal_type": "mean_reversion",
            })

        if not candidates:
            return None

        # Return highest abs(z_score)
        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates[0]
