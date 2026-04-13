"""
Canonical symbol mapping layer.

All internal logic uses a canonical symbol (e.g., "BLAST", "IMX", "YZY").
Each exchange adapter translates to/from its native format.

The mapper handles:
    1. Stripping quote currency suffixes (USDT, USD, PERP, -PERP, -USDT)
    2. Known aliases (0G <-> OG, etc.)
    3. Case normalization (all canonical symbols are UPPERCASE)

Usage:
    mapper = SymbolMapper.from_config(config)
    canonical = mapper.to_canonical("BLASTUSDT", exchange="binance")  # -> "BLAST"
    native = mapper.to_native("BLAST", exchange="binance")  # -> "BLASTUSDT"
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Suffixes to strip, ordered longest-first to avoid partial matches
SUFFIXES = ["-PERP", "-USDT", "-USD", "USDT", "USD", "PERP"]

# Exchange-specific native format rules
_EXCHANGE_SUFFIX: dict[str, str] = {
    "binance": "USDT",
    "bybit": "USDT",
    "hyperliquid": "",  # Hyperliquid uses bare symbols
}


class SymbolMapper:
    """Bidirectional symbol mapping between canonical and exchange-native formats."""

    def __init__(
        self,
        aliases: dict[str, list[str]] | None = None,
        exchange_overrides: dict[str, dict[str, str]] | None = None,
    ):
        # canonical -> set of known variants (all uppercase)
        self._aliases: dict[str, set[str]] = {}
        # reverse: variant -> canonical
        self._reverse: dict[str, str] = {}
        # exchange-specific overrides: (canonical, exchange) -> native symbol
        self._native_overrides: dict[tuple[str, str], str] = {}

        if aliases:
            for canonical, variants in aliases.items():
                canonical = canonical.upper()
                variant_set = {v.upper() for v in variants}
                self._aliases[canonical] = variant_set
                for v in variant_set:
                    self._reverse[v] = canonical

        if exchange_overrides:
            for exchange, mapping in exchange_overrides.items():
                for canonical, native in mapping.items():
                    self._native_overrides[(canonical.upper(), exchange)] = native

    @classmethod
    def from_config(cls, config: dict) -> SymbolMapper:
        """Load aliases and exchange overrides from config."""
        aliases = config.get("symbol_aliases", {})
        exchange_overrides = config.get("symbol_exchange_overrides", {})
        return cls(aliases=aliases, exchange_overrides=exchange_overrides)

    def to_canonical(self, raw_symbol: str, exchange: str = "") -> str:
        """Convert exchange-native symbol to canonical form.

        Steps:
            1. Uppercase
            2. Strip known suffixes
            3. Resolve aliases to canonical
        """
        sym = raw_symbol.upper().strip()

        # Strip suffixes (longest first)
        for suffix in SUFFIXES:
            if sym.endswith(suffix):
                sym = sym[: -len(suffix)]
                break

        # Resolve alias to canonical
        if sym in self._reverse:
            resolved = self._reverse[sym]
            logger.debug("Resolved alias %s -> %s (exchange=%s)", raw_symbol, resolved, exchange)
            return resolved

        return sym

    def to_native(self, canonical: str, exchange: str) -> str:
        """Convert canonical symbol to exchange-native format.

        Steps:
            1. Check for explicit override
            2. Check if exchange needs an alias (reverse lookup)
            3. Append exchange suffix
        """
        canonical = canonical.upper()

        # Check explicit overrides first
        override = self._native_overrides.get((canonical, exchange))
        if override is not None:
            return override

        # For Hyperliquid: if the canonical has a known alias, use the first alias
        # (Hyperliquid uses bare symbols, often the variant form like "OG" for "0G")
        base = canonical
        if exchange == "hyperliquid" and canonical in self._aliases:
            # Use the first alias variant for Hyperliquid
            variants = self._aliases[canonical]
            if variants:
                base = sorted(variants)[0]  # deterministic: alphabetically first

        suffix = _EXCHANGE_SUFFIX.get(exchange, "")
        return f"{base}{suffix}"

    def get_canonical_symbols(self, config_assets: list[str]) -> list[str]:
        """Normalize a list of asset names to canonical form."""
        return [self.to_canonical(a) for a in config_assets]
