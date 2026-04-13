"""
Factory functions for constructing pipeline components from config.
"""

from __future__ import annotations

from src.config import get_config
from src.utils.symbol_mapper import SymbolMapper
from src.collectors.exchange_adapters import BinanceAdapter, HyperliquidAdapter, BybitAdapter
from src.collectors.exchange_adapters.base import ExchangeAdapter


def build_symbol_mapper(cfg: dict | None = None) -> SymbolMapper:
    """Create a SymbolMapper from config."""
    cfg = cfg or get_config()
    return SymbolMapper.from_config(cfg)


def build_adapters(cfg: dict | None = None, symbol_mapper: SymbolMapper | None = None) -> list[ExchangeAdapter]:
    """Create exchange adapters from config with shared SymbolMapper."""
    cfg = cfg or get_config()
    mapper = symbol_mapper or build_symbol_mapper(cfg)

    adapters: list[ExchangeAdapter] = []
    for name, ecfg in cfg["exchanges"].items():
        if not ecfg.get("enabled", False):
            continue
        if name == "binance":
            adapters.append(BinanceAdapter(ecfg["base_url"], ecfg["funding_interval_hours"], mapper))
        elif name == "hyperliquid":
            adapters.append(HyperliquidAdapter(ecfg["base_url"], ecfg["funding_interval_hours"], mapper))
        elif name == "bybit":
            adapters.append(BybitAdapter(ecfg["base_url"], ecfg["funding_interval_hours"], mapper))
    return adapters
