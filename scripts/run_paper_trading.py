#!/usr/bin/env python3
"""
Entry point: starts the paper trading simulator with live ATS connector.

Wires ATSConnector → SignalFilterPipeline → PaperTrader, serves stats API.

Usage:
    python3 scripts/run_paper_trading.py
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
from src.bridge.ats_connector import ATSConnector
from src.simulator.paper_trader import PaperTrader
from src.pipeline.live_orchestrator import LiveOrchestrator
from src.api.stats_server import app, set_pipeline, set_orchestrator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def build_components(cfg: dict) -> tuple[ATSConnector, SignalFilterPipeline, PaperTrader]:
    """Construct all components from config."""
    # Signal filter pipeline
    adapters = build_adapters(cfg)
    if not adapters:
        raise RuntimeError("No exchange adapters enabled in config")

    collector = RegimeHistoryCollector(adapters)
    duration_predictor = DurationPredictor(collector)
    liquidity_scorer = LiquidityScorer(adapters)
    adapter_dict = {a.name: a for a in adapters}
    scorer = CompositeSignalScorer(duration_predictor, liquidity_scorer, adapter_dict)
    pipeline = SignalFilterPipeline(scorer)

    # ATS Connector
    conn_cfg = cfg.get("connector", {})
    connector = ATSConnector(
        jsonl_path=conn_cfg.get("jsonl_path", "workspace/logs/trading_engine.jsonl"),
        state_path=conn_cfg.get("state_path", "workspace/regime_state.json"),
        poll_interval=conn_cfg.get("poll_interval", 2.0),
        default_exchange=conn_cfg.get("default_exchange", "hyperliquid"),
    )

    # Paper Trader
    sim_cfg = cfg.get("simulator", {})
    paper_trader = PaperTrader(
        notional_per_trade=sim_cfg.get("notional_per_trade", 1000.0),
        max_open_positions=sim_cfg.get("max_open_positions", 5),
        entry_fee_bps=sim_cfg.get("entry_fee_bps", 4.0),
        exit_fee_bps=sim_cfg.get("exit_fee_bps", 4.0),
        slippage_bps=sim_cfg.get("slippage_bps", 2.0),
        log_path=sim_cfg.get("log_path", "data/paper_trades.jsonl"),
    )

    return connector, pipeline, paper_trader


async def run():
    cfg = load_config()
    connector, pipeline, paper_trader = build_components(cfg)

    orchestrator = LiveOrchestrator(connector, pipeline, paper_trader)

    # Register with stats API
    set_pipeline(pipeline)
    set_orchestrator(orchestrator)

    port = cfg["api"]["port"]
    logger.info("Starting paper trading orchestrator + stats API on port %d", port)
    logger.info("Connector: watching %s", connector.jsonl_path)
    logger.info("Paper trader: $%.0f/trade, max %d positions",
                paper_trader.notional_per_trade, paper_trader.max_open_positions)

    # Run API server and orchestrator concurrently
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)

    async with asyncio.TaskGroup() as tg:
        tg.create_task(server.serve())
        tg.create_task(orchestrator.run())


if __name__ == "__main__":
    asyncio.run(run())
