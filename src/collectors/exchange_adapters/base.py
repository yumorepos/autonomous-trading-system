"""
Abstract base class for exchange funding rate adapters.

All adapters must implement fetch_funding_history and fetch_current_rates.
Includes shared retry/timeout logic.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod

import aiohttp

from src.models import CurrentFundingRate, FundingRateRecord, TickerInfo
from src.utils.symbol_mapper import SymbolMapper

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BASE_TIMEOUT = 10  # seconds
BACKOFF_BASE = 1.0  # seconds


class ExchangeAdapter(ABC):
    """Abstract exchange adapter for funding rate data."""

    def __init__(self, name: str, base_url: str, funding_interval_hours: float,
                 symbol_mapper: SymbolMapper | None = None):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.funding_interval_hours = funding_interval_hours
        self.symbol_mapper = symbol_mapper or SymbolMapper()

    @abstractmethod
    async def fetch_funding_history(
        self, symbol: str, start_ms: int, end_ms: int
    ) -> list[FundingRateRecord]:
        """Fetch historical funding rates for a symbol within a time range."""
        ...

    @abstractmethod
    async def fetch_current_rates(self) -> list[CurrentFundingRate]:
        """Fetch current/next funding rates for all available symbols."""
        ...

    @abstractmethod
    async def fetch_ticker_info(self) -> list[TickerInfo]:
        """Fetch 24h volume and open interest for liquidity scoring."""
        ...

    def annualize_rate(self, rate: float) -> float:
        """Convert per-interval funding rate to annualized percentage.

        E.g. rate=0.0001 with 8h intervals -> 0.0001 * 3 * 365 * 100 = 10.95%
        """
        intervals_per_year = (365 * 24) / self.funding_interval_hours
        return abs(rate) * intervals_per_year * 100

    async def _request(
        self,
        session: aiohttp.ClientSession,
        method: str,
        url: str,
        **kwargs,
    ) -> dict | list:
        """HTTP request with retry logic and exponential backoff."""
        timeout = aiohttp.ClientTimeout(total=BASE_TIMEOUT)
        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES):
            try:
                async with session.request(
                    method, url, timeout=timeout, **kwargs
                ) as resp:
                    resp.raise_for_status()
                    return await resp.json()
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_error = e
                wait = BACKOFF_BASE * (2 ** attempt)
                logger.warning(
                    "%s request failed (attempt %d/%d): %s — retrying in %.1fs",
                    self.name, attempt + 1, MAX_RETRIES, e, wait,
                )
                await asyncio.sleep(wait)

        logger.error("%s request failed after %d retries: %s", self.name, MAX_RETRIES, last_error)
        raise last_error
