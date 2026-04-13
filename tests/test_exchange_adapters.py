"""Tests for exchange adapters — unit tests with mocked HTTP responses."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.collectors.exchange_adapters.binance import BinanceAdapter
from src.collectors.exchange_adapters.hyperliquid import HyperliquidAdapter
from src.collectors.exchange_adapters.bybit import BybitAdapter


class TestBinanceAdapter:

    def test_annualize_rate(self):
        adapter = BinanceAdapter()
        # 0.01% per 8h = 0.0001 * 3 * 365 * 100 = 10.95%
        apy = adapter.annualize_rate(0.0001)
        assert abs(apy - 10.95) < 0.1

    def test_symbol_conversion(self):
        adapter = BinanceAdapter()
        assert adapter._to_binance_symbol("BTC") == "BTCUSDT"
        assert adapter._to_binance_symbol("BLAST") == "BLASTUSDT"

    @pytest.mark.asyncio
    async def test_fetch_current_rates_parses_response(self):
        adapter = BinanceAdapter()
        mock_data = [
            {
                "symbol": "BTCUSDT",
                "lastFundingRate": "0.0001",
                "markPrice": "65000.0",
                "indexPrice": "64990.0",
                "nextFundingTime": 1712000000000,
            },
            {
                "symbol": "ETHUSDT",
                "lastFundingRate": "-0.0002",
                "markPrice": "3200.0",
                "indexPrice": "3199.0",
                "nextFundingTime": 1712000000000,
            },
        ]

        with patch.object(adapter, "_request", new_callable=AsyncMock, return_value=mock_data):
            rates = await adapter.fetch_current_rates()

        assert len(rates) == 2
        assert rates[0].asset == "BTC"
        assert rates[0].exchange == "binance"
        assert rates[0].funding_rate == 0.0001

    @pytest.mark.asyncio
    async def test_fetch_funding_history_paginates(self):
        adapter = BinanceAdapter()
        page1 = [
            {"symbol": "BTCUSDT", "fundingRate": "0.0001", "fundingTime": 1711900000000},
            {"symbol": "BTCUSDT", "fundingRate": "0.0002", "fundingTime": 1711928800000},
        ]

        with patch.object(adapter, "_request", new_callable=AsyncMock, side_effect=[page1, []]):
            records = await adapter.fetch_funding_history("BTC", 1711900000000, 1712000000000)

        assert len(records) == 2
        assert records[0].asset == "BTC"
        assert records[0].exchange == "binance"


class TestHyperliquidAdapter:

    def test_annualize_rate(self):
        adapter = HyperliquidAdapter()
        # 0.01% per 1h = 0.0001 * 24 * 365 * 100 = 87.6%
        apy = adapter.annualize_rate(0.0001)
        assert abs(apy - 87.6) < 0.1

    @pytest.mark.asyncio
    async def test_fetch_current_rates(self):
        adapter = HyperliquidAdapter()
        mock_data = [
            {"universe": [{"name": "BTC"}, {"name": "ETH"}]},
            [
                {"funding": "0.0001", "markPx": "65000"},
                {"funding": "-0.0003", "markPx": "3200"},
            ],
        ]

        with patch.object(adapter, "_request", new_callable=AsyncMock, return_value=mock_data):
            rates = await adapter.fetch_current_rates()

        assert len(rates) == 2
        assert rates[0].asset == "BTC"
        assert rates[0].exchange == "hyperliquid"

    @pytest.mark.asyncio
    async def test_fetch_ticker_info(self):
        adapter = HyperliquidAdapter()
        mock_data = [
            {"universe": [{"name": "BTC"}]},
            [{"funding": "0.0001", "markPx": "65000", "dayNtlVlm": "500000000", "openInterest": "1000"}],
        ]

        with patch.object(adapter, "_request", new_callable=AsyncMock, return_value=mock_data):
            tickers = await adapter.fetch_ticker_info()

        assert len(tickers) == 1
        assert tickers[0].volume_24h_usd == 500000000
        assert tickers[0].open_interest_usd == 65000000  # 1000 * 65000


class TestBybitAdapter:

    def test_annualize_rate(self):
        adapter = BybitAdapter()
        apy = adapter.annualize_rate(0.0001)
        assert abs(apy - 10.95) < 0.1

    @pytest.mark.asyncio
    async def test_fetch_current_rates(self):
        adapter = BybitAdapter()
        mock_data = {
            "result": {
                "list": [
                    {
                        "symbol": "BTCUSDT",
                        "fundingRate": "0.0001",
                        "markPrice": "65000",
                        "indexPrice": "64990",
                    },
                ]
            }
        }

        with patch.object(adapter, "_request", new_callable=AsyncMock, return_value=mock_data):
            rates = await adapter.fetch_current_rates()

        assert len(rates) == 1
        assert rates[0].asset == "BTC"
        assert rates[0].exchange == "bybit"

    @pytest.mark.asyncio
    async def test_fetch_funding_history(self):
        adapter = BybitAdapter()
        mock_data = {
            "result": {
                "list": [
                    {"symbol": "BTCUSDT", "fundingRate": "0.0001", "fundingRateTimestamp": "1711928800000"},
                    {"symbol": "BTCUSDT", "fundingRate": "0.0002", "fundingRateTimestamp": "1711900000000"},
                ]
            }
        }

        with patch.object(adapter, "_request", new_callable=AsyncMock, side_effect=[mock_data, {"result": {"list": []}}]):
            records = await adapter.fetch_funding_history("BTC", 1711900000000, 1712000000000)

        assert len(records) == 2
        # Should be sorted chronologically
        assert records[0].timestamp_utc <= records[1].timestamp_utc
