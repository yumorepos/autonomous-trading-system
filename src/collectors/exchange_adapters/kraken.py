"""
Kraken Futures adapter for funding rate data.

This is a synchronous adapter built for the cross-exchange spread scanner.
It intentionally does NOT extend ExchangeAdapter (async base) — the scanner
uses requests/sync to keep it simple and independent of the live trading
async plumbing.

Public tickers endpoint (no auth):
  GET https://futures.kraken.com/derivatives/api/v3/tickers

Kraken USD-margined perps are prefixed "PF_" (e.g. PF_SOLUSD, PF_XBTUSD).
Funding on Kraken perps pays every 4 HOURS.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

TICKERS_URL = "https://futures.kraken.com/derivatives/api/v3/tickers"
REQUEST_TIMEOUT = 10  # seconds
MIN_REQUEST_INTERVAL = 0.2  # crude rate limit (5 req/s max)
FUNDING_INTERVAL_HOURS = 4

# Kraken uses "XBT" for Bitcoin — normalize to BTC like our other adapters.
_BASE_ALIASES = {"XBT": "BTC"}


class KrakenAdapter:
    """Sync Kraken perpetuals adapter for spread scanning."""

    name = "Kraken"
    funding_interval_hours = FUNDING_INTERVAL_HOURS

    def __init__(self, tickers_url: str = TICKERS_URL):
        self._tickers_url = tickers_url
        self._last_request_ts: float = 0.0
        self._cached_tickers: Optional[list[dict]] = None
        self._cache_ts: float = 0.0
        self._cache_ttl: float = 5.0  # seconds — share one fetch across methods

    # ------------------------------------------------------------------ utils

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_ts
        if elapsed < MIN_REQUEST_INTERVAL:
            time.sleep(MIN_REQUEST_INTERVAL - elapsed)
        self._last_request_ts = time.monotonic()

    @staticmethod
    def _parse_base_asset(symbol: str) -> Optional[str]:
        """Parse 'PF_SOLUSD' -> 'SOL'. Returns None for non-PF symbols."""
        if not symbol or not symbol.upper().startswith("PF_"):
            return None
        body = symbol[3:].upper()
        if not body.endswith("USD"):
            return None
        base = body[:-3]
        if not base:
            return None
        return _BASE_ALIASES.get(base, base)

    def _fetch_tickers(self) -> list[dict]:
        """Fetch tickers list with short-lived cache."""
        now = time.monotonic()
        if self._cached_tickers is not None and (now - self._cache_ts) < self._cache_ttl:
            return self._cached_tickers

        self._throttle()
        try:
            resp = requests.get(self._tickers_url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            payload = resp.json()
        except (requests.RequestException, ValueError) as e:
            logger.error("Kraken tickers fetch failed: %s", e)
            return []

        tickers = payload.get("tickers") or []
        if not isinstance(tickers, list):
            logger.error("Kraken tickers payload malformed: %r", type(tickers))
            return []

        self._cached_tickers = tickers
        self._cache_ts = now
        return tickers

    # --------------------------------------------------------------- public API

    def get_funding_rates(self) -> dict[str, float]:
        """
        Return current 4h funding rates keyed by canonical base asset.
        Rates are RELATIVE (fraction of notional), e.g. 0.000125 = 0.0125% / 4h.

        NOTE: Kraken's `fundingRate` field is ABSOLUTE (USD per contract per
        funding period), not a percentage. We divide by markPrice to get the
        relative rate, matching how HL / Binance / Bybit expose their rates.
        """
        out: dict[str, float] = {}
        for t in self._fetch_tickers():
            symbol = t.get("symbol") or ""
            base = self._parse_base_asset(symbol)
            if base is None:
                continue
            rate = t.get("fundingRate")
            mark = t.get("markPrice")
            if rate is None or mark is None:
                continue
            try:
                rate_f = float(rate)
                mark_f = float(mark)
            except (TypeError, ValueError):
                logger.warning("Kraken: bad fundingRate/markPrice for %s: %r/%r",
                               symbol, rate, mark)
                continue
            if mark_f <= 0:
                continue
            out[base] = rate_f / mark_f
        return out

    def get_volumes(self) -> dict[str, float]:
        """
        Return 24h USD volume keyed by canonical base asset.
        Computed as vol24h * markPrice.
        """
        out: dict[str, float] = {}
        for t in self._fetch_tickers():
            symbol = t.get("symbol") or ""
            base = self._parse_base_asset(symbol)
            if base is None:
                continue
            try:
                vol = float(t.get("vol24h") or 0)
                mark = float(t.get("markPrice") or 0)
            except (TypeError, ValueError):
                continue
            if vol <= 0 or mark <= 0:
                continue
            out[base] = vol * mark
        return out

    @staticmethod
    def normalize_rate_to_8h(rate_4h: float) -> float:
        """Kraken funds every 4h — multiply by 2 for 8h equivalent."""
        return rate_4h * 2
