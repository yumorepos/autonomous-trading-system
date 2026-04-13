"""
LiquidityScorer — Scores asset tradability based on volume and open interest.

Produces normalized scores [0.0, 1.0] per asset per exchange.
Caches results for 5 minutes.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time

from src.collectors.exchange_adapters.base import ExchangeAdapter
from src.models import TickerInfo

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 300  # 5 minutes
_MIN_TRADEABLE_SCORE = 0.15


class LiquidityScorer:
    """Scores asset liquidity from 24h volume and open interest."""

    def __init__(self, adapters: list[ExchangeAdapter]):
        self.adapters = {a.name: a for a in adapters}
        self._cache: dict[str, list[TickerInfo]] = {}
        self._cache_time: dict[str, float] = {}

    async def refresh(self):
        """Fetch fresh ticker data from all exchanges."""
        tasks = {
            name: adapter.fetch_ticker_info()
            for name, adapter in self.adapters.items()
        }
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        now = time.time()
        for name, result in zip(tasks.keys(), results):
            if isinstance(result, Exception):
                logger.warning("Failed to fetch ticker from %s: %s", name, result)
                continue
            self._cache[name] = result
            self._cache_time[name] = now

    def _is_cache_fresh(self, exchange: str) -> bool:
        return (
            exchange in self._cache_time
            and (time.time() - self._cache_time[exchange]) < _CACHE_TTL_SECONDS
        )

    async def _ensure_fresh(self):
        """Refresh cache if stale for any exchange."""
        stale = [name for name in self.adapters if not self._is_cache_fresh(name)]
        if stale:
            await self.refresh()

    def _get_all_tickers(self) -> list[TickerInfo]:
        """Get all cached ticker data across exchanges."""
        all_tickers = []
        for tickers in self._cache.values():
            all_tickers.extend(tickers)
        return all_tickers

    async def score(self, asset: str, exchange: str | None = None) -> float:
        """Get liquidity score for an asset (optionally on a specific exchange).

        Returns normalized score [0.0, 1.0]:
            1.0 = top-tier liquidity (BTC/ETH level)
            0.0 = untradeable

        Formula:
            raw = 0.6 * log_normalize(volume) + 0.4 * log_normalize(open_interest)
        """
        await self._ensure_fresh()

        all_tickers = self._get_all_tickers()
        if not all_tickers:
            return 0.0

        # Find max values for normalization
        max_volume = max((t.volume_24h_usd for t in all_tickers), default=1.0)
        max_oi = max((t.open_interest_usd for t in all_tickers), default=1.0)

        # Find the asset's ticker
        candidates = [
            t for t in all_tickers
            if t.asset == asset and (exchange is None or t.exchange == exchange)
        ]

        if not candidates:
            return 0.0

        # Use the best ticker across exchanges if no specific exchange
        best = max(candidates, key=lambda t: t.volume_24h_usd + t.open_interest_usd)

        score = (
            0.6 * self._log_normalize(best.volume_24h_usd, max_volume)
            + 0.4 * self._log_normalize(best.open_interest_usd, max_oi)
        )

        return round(min(max(score, 0.0), 1.0), 4)

    @staticmethod
    def _log_normalize(value: float, max_observed: float) -> float:
        """Log-normalize a value relative to the max observed.

        log_normalize(x) = log10(x + 1) / log10(max_observed + 1)
        """
        if max_observed <= 0:
            return 0.0
        return math.log10(value + 1) / math.log10(max_observed + 1)

    async def score_all(self) -> dict[tuple[str, str], float]:
        """Score all assets across all exchanges. Returns {(asset, exchange): score}."""
        await self._ensure_fresh()

        all_tickers = self._get_all_tickers()
        if not all_tickers:
            return {}

        max_volume = max((t.volume_24h_usd for t in all_tickers), default=1.0)
        max_oi = max((t.open_interest_usd for t in all_tickers), default=1.0)

        scores = {}
        for t in all_tickers:
            s = (
                0.6 * self._log_normalize(t.volume_24h_usd, max_volume)
                + 0.4 * self._log_normalize(t.open_interest_usd, max_oi)
            )
            scores[(t.asset, t.exchange)] = round(min(max(s, 0.0), 1.0), 4)

        return scores

    @staticmethod
    def is_tradeable(score: float) -> bool:
        """Check if an asset meets the minimum liquidity threshold."""
        return score >= _MIN_TRADEABLE_SCORE

    @staticmethod
    def grade(score: float) -> str:
        """Convert score to letter grade for display."""
        if score >= 0.7:
            return "A"
        elif score >= 0.4:
            return "B"
        elif score >= 0.15:
            return "C"
        else:
            return "F"
