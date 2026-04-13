"""
LiveOrchestrator — Wires ATSConnector → SignalFilterPipeline → PaperTrader.

Consumes live regime transitions from the ATS engine, scores them through
the signal filter pipeline, and routes actionable signals to the paper trader.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from src.bridge.ats_connector import ATSConnector
from src.models import RegimeTransitionEvent, RegimeTier, ScoredSignal
from src.pipeline.signal_filter import SignalFilterPipeline
from src.simulator.paper_trader import PaperTrader

logger = logging.getLogger(__name__)


class LiveOrchestrator:
    """Orchestrates the live paper trading loop.

    1. ATSConnector yields regime transition events
    2. SignalFilterPipeline scores and gates them
    3. PaperTrader opens/closes simulated positions
    """

    def __init__(
        self,
        connector: ATSConnector,
        pipeline: SignalFilterPipeline,
        paper_trader: PaperTrader,
    ):
        self.connector = connector
        self.pipeline = pipeline
        self.paper_trader = paper_trader
        self._events_processed = 0
        self._signals_actionable = 0
        self._positions_opened = 0
        self._positions_closed = 0
        self._started_at: datetime | None = None

    async def handle_event(self, event: RegimeTransitionEvent) -> ScoredSignal:
        """Process a single regime transition event through the full chain."""
        self._events_processed += 1

        # Score through the pipeline
        signal = await self.pipeline.process(event)

        if signal.is_actionable:
            self._signals_actionable += 1

            # Open a new paper position
            position = self.paper_trader.open_position(signal)
            if position is not None:
                self._positions_opened += 1
                logger.info(
                    "Orchestrator: opened paper position %s for %s on %s",
                    position.position_id, event.asset, event.exchange,
                )
        else:
            # If regime dropped from HIGH_FUNDING, close existing positions
            if event.previous_regime == RegimeTier.HIGH_FUNDING:
                closed = self.paper_trader.close_positions_for_asset(
                    event.asset, event.exchange, reason="regime_exit",
                )
                self._positions_closed += len(closed)
                if closed:
                    logger.info(
                        "Orchestrator: closed %d position(s) for %s (regime exit)",
                        len(closed), event.asset,
                    )

        return signal

    async def run(self):
        """Main loop: watch for events and process them."""
        self._started_at = datetime.now(timezone.utc)

        # Seek to end of log to only process new events
        self.connector.seek_to_end()

        logger.info("LiveOrchestrator started — watching for regime transitions")

        async for event in self.connector.watch():
            try:
                await self.handle_event(event)
            except Exception as e:
                logger.error("Failed to handle event: %s", e, exc_info=True)

    def get_status(self) -> dict:
        """Return orchestrator status for the stats API."""
        paper_stats = self.paper_trader.get_stats()
        uptime_seconds = 0.0
        if self._started_at:
            uptime_seconds = (datetime.now(timezone.utc) - self._started_at).total_seconds()

        return {
            "orchestrator": {
                "started_at": self._started_at.isoformat() if self._started_at else None,
                "uptime_seconds": round(uptime_seconds, 0),
                "events_processed": self._events_processed,
                "signals_actionable": self._signals_actionable,
                "positions_opened": self._positions_opened,
                "positions_closed": self._positions_closed,
            },
            "paper_trading": paper_stats.model_dump(),
            "open_positions": self.paper_trader.get_open_positions_summary(),
        }
