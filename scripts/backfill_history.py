#!/usr/bin/env python3
"""
One-shot backfill: fetch 30 days of funding rate history and build regime transitions.

Usage:
    python3 scripts/backfill_history.py
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
from src.collectors.regime_history import RegimeHistoryCollector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    cfg = load_config()
    adapters = build_adapters(cfg)

    if not adapters:
        logger.error("No exchange adapters enabled in config")
        sys.exit(1)

    logger.info("Starting backfill with %d adapters: %s", len(adapters), [a.name for a in adapters])
    logger.info("Assets: %s", cfg["assets"])
    logger.info("Backfill period: %d days", cfg["history"]["backfill_days"])

    collector = RegimeHistoryCollector(adapters)
    await collector.backfill()

    total = collector.get_transition_count()
    logger.info("Backfill complete. Total regime transitions: %d", total)

    if total < 500:
        logger.warning(
            "Only %d transitions found (target: ≥500). "
            "This may be normal for low-activity assets — consider adding more assets or longer backfill period.",
            total,
        )
    else:
        logger.info("✓ Validation passed: %d transitions ≥ 500 target", total)


if __name__ == "__main__":
    asyncio.run(main())
