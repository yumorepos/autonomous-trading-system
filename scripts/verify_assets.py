#!/usr/bin/env python3
"""
Asset verification: check which configured assets exist on which exchanges.

For each (asset, exchange) pair, fetches the most recent funding rate.
Outputs a table and summary statistics.

Usage:
    python3 scripts/verify_assets.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.config import load_config
from src.factory import build_adapters

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    cfg = load_config()
    adapters = build_adapters(cfg)
    assets = cfg["assets"]

    if not adapters:
        logger.error("No exchange adapters enabled")
        sys.exit(1)

    exchange_names = [a.name for a in adapters]

    # Fetch current rates from all exchanges
    logger.info("Fetching current funding rates from %d exchanges...", len(adapters))
    all_rates: dict[str, dict[str, float | None]] = {}  # {exchange: {asset: rate_or_None}}

    for adapter in adapters:
        try:
            rates = await adapter.fetch_current_rates()
            rate_map = {r.asset: r.funding_rate_annualized for r in rates}
            all_rates[adapter.name] = rate_map
            logger.info("%s: fetched %d symbols", adapter.name, len(rate_map))
        except Exception as e:
            logger.error("Failed to fetch from %s: %s", adapter.name, e)
            all_rates[adapter.name] = {}

    # Build results table
    print()
    print("=" * 80)
    print("  ASSET VERIFICATION — Exchange Coverage")
    print("=" * 80)

    # Header
    header = f"  {'Asset':<12}"
    for ex in exchange_names:
        header += f"| {ex:<18}"
    print(header)
    print("-" * 80)

    found_count = 0
    total_pairs = len(assets) * len(exchange_names)
    asset_exchange_count: dict[str, int] = {}
    missing_everywhere: list[str] = []

    for asset in assets:
        row = f"  {asset:<12}"
        exchanges_found = 0

        for ex_name in exchange_names:
            rates = all_rates.get(ex_name, {})
            rate = rates.get(asset)

            if rate is not None:
                found_count += 1
                exchanges_found += 1
                # Show native symbol if alias was resolved
                native = adapters[exchange_names.index(ex_name)].symbol_mapper.to_native(asset, ex_name)
                display_asset = f"(as {native})" if native != asset and native != f"{asset}USDT" else ""
                row += f"| {'✅':} {rate:>7.2f}% {display_asset:<6}"
            else:
                row += f"| {'❌ not listed':<18}"

        print(row)
        asset_exchange_count[asset] = exchanges_found
        if exchanges_found == 0:
            missing_everywhere.append(asset)

    print("-" * 80)
    print()

    # Summary
    cross_exchange = [a for a, c in asset_exchange_count.items() if c >= 2]
    single_exchange = [a for a, c in asset_exchange_count.items() if c == 1]

    print(f"  Total: {found_count}/{total_pairs} asset-exchange pairs verified")
    print(f"  Cross-exchange pairs (≥2 exchanges): {len(cross_exchange)} assets — {cross_exchange}")
    print(f"  Single-exchange assets: {len(single_exchange)} — {single_exchange}")

    if missing_everywhere:
        print(f"\n  ⚠️  MISSING EVERYWHERE: {missing_everywhere}")
        print("     These assets may be delisted or symbol mapping is wrong.")
        print("     Fix aliases in config.yaml or remove from assets list.")
    else:
        print(f"\n  ✓ All {len(assets)} assets found on at least one exchange")

    print()

    # Exit code
    if missing_everywhere:
        sys.exit(1)
    elif len(cross_exchange) < 2:
        logger.warning("Fewer than 2 assets on ≥2 exchanges — cross-spread will be limited")
        sys.exit(2)
    else:
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
