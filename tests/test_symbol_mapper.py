"""Tests for SymbolMapper — canonical symbol normalization."""

from __future__ import annotations

import pytest

from src.utils.symbol_mapper import SymbolMapper


@pytest.fixture
def mapper():
    """Create a SymbolMapper with test aliases."""
    return SymbolMapper(
        aliases={
            "0G": ["OG", "ZEROG"],
            "STABLE": ["STBL"],
        },
        exchange_overrides={
            "hyperliquid": {"0G": "OG"},
        },
    )


@pytest.fixture
def mapper_from_config():
    """Create a SymbolMapper from config-style dict."""
    config = {
        "symbol_aliases": {
            "0G": ["OG", "ZEROG"],
            "STABLE": ["STBL"],
        },
        "symbol_exchange_overrides": {
            "hyperliquid": {"0G": "OG"},
        },
    }
    return SymbolMapper.from_config(config)


class TestToCanonical:

    def test_binance_strip_usdt(self, mapper):
        assert mapper.to_canonical("BLASTUSDT", "binance") == "BLAST"

    def test_hyperliquid_bare_symbol(self, mapper):
        assert mapper.to_canonical("BLAST", "hyperliquid") == "BLAST"

    def test_bybit_strip_usdt(self, mapper):
        assert mapper.to_canonical("BLASTUSDT", "bybit") == "BLAST"

    def test_hyphenated_suffix(self, mapper):
        assert mapper.to_canonical("BLAST-USDT", "bybit") == "BLAST"

    def test_alias_resolution_og_to_0g(self, mapper):
        assert mapper.to_canonical("OG", "hyperliquid") == "0G"

    def test_alias_resolution_zerog(self, mapper):
        assert mapper.to_canonical("ZEROG", "hyperliquid") == "0G"

    def test_binance_0g_with_suffix(self, mapper):
        # "0GUSDT" -> strip USDT -> "0G" (already canonical, no alias needed)
        assert mapper.to_canonical("0GUSDT", "binance") == "0G"

    def test_stbl_alias(self, mapper):
        assert mapper.to_canonical("STBL", "hyperliquid") == "STABLE"

    def test_case_insensitive(self, mapper):
        assert mapper.to_canonical("blastusdt", "binance") == "BLAST"
        assert mapper.to_canonical("og", "hyperliquid") == "0G"

    def test_perp_suffix(self, mapper):
        assert mapper.to_canonical("BLAST-PERP", "some_exchange") == "BLAST"
        assert mapper.to_canonical("BLASTPERP", "some_exchange") == "BLAST"

    def test_unknown_symbol_passthrough(self, mapper):
        assert mapper.to_canonical("NEWCOIN", "binance") == "NEWCOIN"
        assert mapper.to_canonical("NEWCOINUSDT", "binance") == "NEWCOIN"


class TestToNative:

    def test_binance_appends_usdt(self, mapper):
        assert mapper.to_native("BLAST", "binance") == "BLASTUSDT"

    def test_hyperliquid_bare(self, mapper):
        assert mapper.to_native("BLAST", "hyperliquid") == "BLAST"

    def test_bybit_appends_usdt(self, mapper):
        assert mapper.to_native("BLAST", "bybit") == "BLASTUSDT"

    def test_0g_to_hyperliquid_uses_override(self, mapper):
        # Explicit override: 0G -> OG on Hyperliquid
        assert mapper.to_native("0G", "hyperliquid") == "OG"

    def test_0g_to_binance(self, mapper):
        assert mapper.to_native("0G", "binance") == "0GUSDT"

    def test_0g_to_bybit(self, mapper):
        assert mapper.to_native("0G", "bybit") == "0GUSDT"


class TestRoundTrip:

    @pytest.mark.parametrize("canonical,exchange", [
        ("BLAST", "binance"),
        ("BLAST", "hyperliquid"),
        ("BLAST", "bybit"),
        ("IMX", "binance"),
        ("IMX", "hyperliquid"),
        ("JTO", "binance"),
        ("0G", "binance"),
        ("0G", "hyperliquid"),
        ("0G", "bybit"),
    ])
    def test_round_trip(self, mapper, canonical, exchange):
        """to_canonical(to_native(sym, ex), ex) == sym for all configured pairs."""
        native = mapper.to_native(canonical, exchange)
        recovered = mapper.to_canonical(native, exchange)
        assert recovered == canonical, f"Round-trip failed: {canonical} -> {native} -> {recovered}"


class TestFromConfig:

    def test_from_config_matches_direct(self, mapper, mapper_from_config):
        """Config-loaded mapper should behave same as directly constructed."""
        test_cases = [
            ("BLASTUSDT", "binance"),
            ("OG", "hyperliquid"),
            ("0GUSDT", "binance"),
            ("STBL", "hyperliquid"),
        ]
        for raw, exchange in test_cases:
            assert (
                mapper.to_canonical(raw, exchange)
                == mapper_from_config.to_canonical(raw, exchange)
            ), f"Mismatch for to_canonical({raw!r}, {exchange!r})"

    def test_from_config_empty(self):
        mapper = SymbolMapper.from_config({})
        assert mapper.to_canonical("BTCUSDT", "binance") == "BTC"
        assert mapper.to_native("BTC", "binance") == "BTCUSDT"
