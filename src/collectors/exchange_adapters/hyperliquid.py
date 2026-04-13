"""
Hyperliquid adapter for funding rate data.

Endpoints (all POST to https://api.hyperliquid.xyz/info):
  - Current: {"type": "metaAndAssetCtxs"}
  - Historical: {"type": "fundingHistory", "coin": "<COIN>", "startTime": <ms>}
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import aiohttp

from src.models import CurrentFundingRate, FundingRateRecord, TickerInfo
from src.utils.symbol_mapper import SymbolMapper
from .base import ExchangeAdapter

logger = logging.getLogger(__name__)

_HISTORY_PAGE_SIZE = 500


class HyperliquidAdapter(ExchangeAdapter):

    def __init__(self, base_url: str = "https://api.hyperliquid.xyz", funding_interval_hours: float = 1,
                 symbol_mapper: SymbolMapper | None = None):
        super().__init__("hyperliquid", base_url, funding_interval_hours, symbol_mapper)
        self._info_url = f"{self.base_url}/info"

    def _to_native(self, canonical: str) -> str:
        return self.symbol_mapper.to_native(canonical, "hyperliquid")

    def _to_canonical(self, raw_symbol: str) -> str:
        return self.symbol_mapper.to_canonical(raw_symbol, "hyperliquid")

    async def fetch_funding_history(
        self, symbol: str, start_ms: int, end_ms: int
    ) -> list[FundingRateRecord]:
        native_symbol = self._to_native(symbol)
        records: list[FundingRateRecord] = []

        async with aiohttp.ClientSession() as session:
            current_start = start_ms
            while current_start < end_ms:
                payload = {
                    "type": "fundingHistory",
                    "coin": native_symbol,
                    "startTime": current_start,
                }
                try:
                    data = await self._request(
                        session, "POST", self._info_url,
                        json=payload,
                    )
                except Exception:
                    logger.error("Failed to fetch Hyperliquid funding history for %s", symbol)
                    break

                if not data:
                    break

                for item in data:
                    rate = float(item["fundingRate"])
                    ts_str = item["time"]
                    # Hyperliquid returns ISO format or ms timestamp
                    if isinstance(ts_str, (int, float)):
                        ts = datetime.fromtimestamp(ts_str / 1000, tz=timezone.utc)
                    else:
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))

                    if ts.timestamp() * 1000 > end_ms:
                        break

                    records.append(FundingRateRecord(
                        asset=symbol,
                        exchange="hyperliquid",
                        timestamp_utc=ts,
                        funding_rate=rate,
                        funding_rate_annualized=self.annualize_rate(rate),
                        funding_interval_hours=self.funding_interval_hours,
                    ))

                # Paginate forward
                if len(data) < _HISTORY_PAGE_SIZE:
                    break

                last_item = data[-1]
                last_ts = last_item["time"]
                if isinstance(last_ts, (int, float)):
                    current_start = int(last_ts) + 1
                else:
                    last_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
                    current_start = int(last_dt.timestamp() * 1000) + 1

        logger.info("Hyperliquid: fetched %d funding records for %s", len(records), symbol)
        return records

    async def fetch_current_rates(self) -> list[CurrentFundingRate]:
        async with aiohttp.ClientSession() as session:
            try:
                data = await self._request(
                    session, "POST", self._info_url,
                    json={"type": "metaAndAssetCtxs"},
                )
            except Exception:
                logger.error("Failed to fetch Hyperliquid current rates")
                return []

        if not data or len(data) < 2:
            return []

        meta = data[0]
        asset_ctxs = data[1]

        results = []
        for universe_entry, ctx in zip(meta["universe"], asset_ctxs):
            asset = self._to_canonical(universe_entry["name"])
            rate = float(ctx.get("funding", 0) or 0)
            mark = float(ctx.get("markPx", 0) or 0)

            results.append(CurrentFundingRate(
                asset=asset,
                exchange="hyperliquid",
                funding_rate=rate,
                funding_rate_annualized=self.annualize_rate(rate),
                next_funding_time_utc=None,
                mark_price=mark or None,
                index_price=None,
            ))

        return results

    async def fetch_ticker_info(self) -> list[TickerInfo]:
        async with aiohttp.ClientSession() as session:
            try:
                data = await self._request(
                    session, "POST", self._info_url,
                    json={"type": "metaAndAssetCtxs"},
                )
            except Exception:
                logger.error("Failed to fetch Hyperliquid ticker info")
                return []

        if not data or len(data) < 2:
            return []

        meta = data[0]
        asset_ctxs = data[1]

        results = []
        for universe_entry, ctx in zip(meta["universe"], asset_ctxs):
            asset = self._to_canonical(universe_entry["name"])
            day_ntl_vlm = float(ctx.get("dayNtlVlm", 0) or 0)
            open_interest = float(ctx.get("openInterest", 0) or 0)
            mark_px = float(ctx.get("markPx", 0) or 0)

            # Open interest is in coins, convert to USD
            oi_usd = open_interest * mark_px if mark_px > 0 else 0.0

            results.append(TickerInfo(
                asset=asset,
                exchange="hyperliquid",
                volume_24h_usd=day_ntl_vlm,
                open_interest_usd=oi_usd,
            ))

        return results
