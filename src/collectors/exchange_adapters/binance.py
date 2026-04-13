"""
Binance USDT-M Futures adapter for funding rate data.

Endpoints:
  - Historical: GET /fapi/v1/fundingRate
  - Current:    GET /fapi/v1/premiumIndex
  - Ticker:     GET /fapi/v1/ticker/24hr
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import aiohttp

from src.models import CurrentFundingRate, FundingRateRecord, TickerInfo
from src.utils.symbol_mapper import SymbolMapper
from .base import ExchangeAdapter

logger = logging.getLogger(__name__)

# Binance returns max 1000 records per request
_MAX_LIMIT = 1000


class BinanceAdapter(ExchangeAdapter):

    def __init__(self, base_url: str = "https://fapi.binance.com", funding_interval_hours: float = 8,
                 symbol_mapper: SymbolMapper | None = None):
        super().__init__("binance", base_url, funding_interval_hours, symbol_mapper)

    def _to_binance_symbol(self, asset: str) -> str:
        """Convert canonical asset to Binance native symbol."""
        return self.symbol_mapper.to_native(asset, "binance")

    def _to_canonical(self, raw_symbol: str) -> str:
        """Convert Binance native symbol to canonical."""
        return self.symbol_mapper.to_canonical(raw_symbol, "binance")

    async def fetch_funding_history(
        self, symbol: str, start_ms: int, end_ms: int
    ) -> list[FundingRateRecord]:
        binance_symbol = self._to_binance_symbol(symbol)
        records: list[FundingRateRecord] = []

        async with aiohttp.ClientSession() as session:
            current_start = start_ms
            while current_start < end_ms:
                params = {
                    "symbol": binance_symbol,
                    "startTime": current_start,
                    "endTime": end_ms,
                    "limit": _MAX_LIMIT,
                }
                try:
                    data = await self._request(
                        session, "GET",
                        f"{self.base_url}/fapi/v1/fundingRate",
                        params=params,
                    )
                except Exception:
                    logger.error("Failed to fetch Binance funding history for %s", symbol)
                    break

                if not data:
                    break

                for item in data:
                    rate = float(item["fundingRate"])
                    ts = datetime.fromtimestamp(item["fundingTime"] / 1000, tz=timezone.utc)
                    records.append(FundingRateRecord(
                        asset=symbol,
                        exchange="binance",
                        timestamp_utc=ts,
                        funding_rate=rate,
                        funding_rate_annualized=self.annualize_rate(rate),
                        funding_interval_hours=self.funding_interval_hours,
                    ))

                # Move past the last returned timestamp
                last_ts = data[-1]["fundingTime"]
                if last_ts + 1 >= end_ms:
                    break
                current_start = last_ts + 1

        logger.info("Binance: fetched %d funding records for %s", len(records), symbol)
        return records

    async def fetch_current_rates(self) -> list[CurrentFundingRate]:
        async with aiohttp.ClientSession() as session:
            try:
                data = await self._request(
                    session, "GET",
                    f"{self.base_url}/fapi/v1/premiumIndex",
                )
            except Exception:
                logger.error("Failed to fetch Binance current rates")
                return []

        results = []
        for item in data:
            symbol_raw = item.get("symbol", "")
            if not symbol_raw.endswith("USDT"):
                continue

            asset = self._to_canonical(symbol_raw)
            rate = float(item.get("lastFundingRate", 0))
            next_ts = item.get("nextFundingTime")
            next_time = (
                datetime.fromtimestamp(next_ts / 1000, tz=timezone.utc)
                if next_ts else None
            )

            results.append(CurrentFundingRate(
                asset=asset,
                exchange="binance",
                funding_rate=rate,
                funding_rate_annualized=self.annualize_rate(rate),
                next_funding_time_utc=next_time,
                mark_price=float(item.get("markPrice", 0)) or None,
                index_price=float(item.get("indexPrice", 0)) or None,
            ))

        return results

    async def fetch_ticker_info(self) -> list[TickerInfo]:
        async with aiohttp.ClientSession() as session:
            try:
                data = await self._request(
                    session, "GET",
                    f"{self.base_url}/fapi/v1/ticker/24hr",
                )
            except Exception:
                logger.error("Failed to fetch Binance ticker info")
                return []

        results = []
        for item in data:
            symbol_raw = item.get("symbol", "")
            if not symbol_raw.endswith("USDT"):
                continue

            asset = self._to_canonical(symbol_raw)
            results.append(TickerInfo(
                asset=asset,
                exchange="binance",
                volume_24h_usd=float(item.get("quoteVolume", 0)),
                open_interest_usd=0.0,  # Not in 24hr ticker; fetched separately if needed
            ))

        return results
