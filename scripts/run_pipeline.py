#!/usr/bin/env python3
"""
Main entry point: starts the signal filter pipeline and stats API server.

Usage:
    python3 scripts/run_pipeline.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import uvicorn

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.config import load_config
from src.factory import build_adapters
from src.collectors.regime_history import RegimeHistoryCollector
from src.scoring.duration_predictor import DurationPredictor
from src.scoring.liquidity_scorer import LiquidityScorer
from src.scoring.composite_scorer import CompositeSignalScorer
from src.pipeline.signal_filter import SignalFilterPipeline
from src.api.stats_server import app, set_pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def build_pipeline(cfg: dict) -> SignalFilterPipeline:
    """Construct the full pipeline with all dependencies."""
    adapters = build_adapters(cfg)

    if not adapters:
        raise RuntimeError("No exchange adapters enabled in config")

    collector = RegimeHistoryCollector(adapters)
    duration_predictor = DurationPredictor(collector)
    liquidity_scorer = LiquidityScorer(adapters)
    adapter_dict = {a.name: a for a in adapters}
    scorer = CompositeSignalScorer(duration_predictor, liquidity_scorer, adapter_dict)
    pipeline = SignalFilterPipeline(scorer)

    return pipeline


async def run():
    cfg = load_config()
    pipeline = build_pipeline(cfg)
    set_pipeline(pipeline)

    port = cfg["api"]["port"]
    logger.info("Starting signal filter pipeline + stats API on port %d", port)

    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(run())
