"""
Bybit V5 adapter for funding rate data.

Endpoints:
  - Historical: GET /v5/market/funding/history
  - Current:    GET /v5/market/tickers?category=linear
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import aiohttp

from src.models import CurrentFundingRate, FundingRateRecord, TickerInfo
from src.utils.symbol_mapper import SymbolMapper
from .base import ExchangeAdapter

logger = logging.getLogger(__name__)

_MAX_LIMIT = 200  # Bybit v5 max per page


class BybitAdapter(ExchangeAdapter):

    def __init__(self, base_url: str = "https://api.bybit.com", funding_interval_hours: float = 8,
                 symbol_mapper: SymbolMapper | None = None):
        super().__init__("bybit", base_url, funding_interval_hours, symbol_mapper)

    def _to_bybit_symbol(self, asset: str) -> str:
        return self.symbol_mapper.to_native(asset, "bybit")

    def _to_canonical(self, raw_symbol: str) -> str:
        return self.symbol_mapper.to_canonical(raw_symbol, "bybit")

    async def fetch_funding_history(
        self, symbol: str, start_ms: int, end_ms: int
    ) -> list[FundingRateRecord]:
        bybit_symbol = self._to_bybit_symbol(symbol)
        records: list[FundingRateRecord] = []

        async with aiohttp.ClientSession() as session:
            current_end = end_ms
            while True:
                params = {
                    "category": "linear",
                    "symbol": bybit_symbol,
                    "startTime": str(start_ms),
                    "endTime": str(current_end),
                    "limit": str(_MAX_LIMIT),
                }
                try:
                    data = await self._request(
                        session, "GET",
                        f"{self.base_url}/v5/market/funding/history",
                        params=params,
                    )
                except Exception:
                    logger.error("Failed to fetch Bybit funding history for %s", symbol)
                    break

                result_list = data.get("result", {}).get("list", [])
                if not result_list:
                    break

                for item in result_list:
                    rate = float(item["fundingRate"])
                    ts_ms = int(item["fundingRateTimestamp"])
                    ts = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)

                    records.append(FundingRateRecord(
                        asset=symbol,
                        exchange="bybit",
                        timestamp_utc=ts,
                        funding_rate=rate,
                        funding_rate_annualized=self.annualize_rate(rate),
                        funding_interval_hours=self.funding_interval_hours,
                    ))

                # Bybit returns newest first — paginate backwards
                if len(result_list) < _MAX_LIMIT:
                    break

                oldest_ts = min(int(item["fundingRateTimestamp"]) for item in result_list)
                if oldest_ts <= start_ms:
                    break
                current_end = oldest_ts - 1

        # Sort chronologically
        records.sort(key=lambda r: r.timestamp_utc)
        logger.info("Bybit: fetched %d funding records for %s", len(records), symbol)
        return records

    async def fetch_current_rates(self) -> list[CurrentFundingRate]:
        async with aiohttp.ClientSession() as session:
            try:
                data = await self._request(
                    session, "GET",
                    f"{self.base_url}/v5/market/tickers",
                    params={"category": "linear"},
                )
            except Exception:
                logger.error("Failed to fetch Bybit current rates")
                return []

        result_list = data.get("result", {}).get("list", [])
        results = []

        for item in result_list:
            symbol_raw = item.get("symbol", "")
            if not symbol_raw.endswith("USDT"):
                continue

            asset = self._to_canonical(symbol_raw)
            rate = float(item.get("fundingRate", 0))

            results.append(CurrentFundingRate(
                asset=asset,
                exchange="bybit",
                funding_rate=rate,
                funding_rate_annualized=self.annualize_rate(rate),
                next_funding_time_utc=None,
                mark_price=float(item.get("markPrice", 0)) or None,
                index_price=float(item.get("indexPrice", 0)) or None,
            ))

        return results

    async def fetch_ticker_info(self) -> list[TickerInfo]:
        async with aiohttp.ClientSession() as session:
            try:
                data = await self._request(
                    session, "GET",
                    f"{self.base_url}/v5/market/tickers",
                    params={"category": "linear"},
                )
            except Exception:
                logger.error("Failed to fetch Bybit ticker info")
                return []

        result_list = data.get("result", {}).get("list", [])
        results = []

        for item in result_list:
            symbol_raw = item.get("symbol", "")
            if not symbol_raw.endswith("USDT"):
                continue

            asset = self._to_canonical(symbol_raw)
            volume = float(item.get("turnover24h", 0))
            oi_value = float(item.get("openInterestValue", 0) if item.get("openInterestValue") else 0)

            results.append(TickerInfo(
                asset=asset,
                exchange="bybit",
                volume_24h_usd=volume,
                open_interest_usd=oi_value,
            ))

        return results
