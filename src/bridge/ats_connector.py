"""
ATSConnector — Bridges live regime transitions from the existing ATS engine.

Monitors workspace/logs/trading_engine.jsonl for regime_updated events
and workspace/regime_state.json for enriched state (top_assets).

Pattern B: JSONL file log tailing with regime_state.json supplement.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Callable

from src.models import RegimeTransitionEvent, RegimeTier

logger = logging.getLogger(__name__)

# Map engine regime strings to our RegimeTier enum
_REGIME_MAP = {
    "LOW_FUNDING": RegimeTier.LOW_FUNDING,
    "MODERATE": RegimeTier.MODERATE,
    "HIGH_FUNDING": RegimeTier.HIGH_FUNDING,
}


class ATSConnector:
    """Tail the ATS engine JSONL log for regime transition events.

    Yields RegimeTransitionEvent objects as they appear in the log.
    Enriches events with top_asset data from regime_state.json.
    """

    def __init__(
        self,
        jsonl_path: str | Path = "workspace/logs/trading_engine.jsonl",
        state_path: str | Path = "workspace/regime_state.json",
        poll_interval: float = 2.0,
        default_exchange: str = "hyperliquid",
    ):
        self.jsonl_path = Path(jsonl_path)
        self.state_path = Path(state_path)
        self.poll_interval = poll_interval
        self.default_exchange = default_exchange
        self._file_position: int = 0
        self._running = False
        self._callbacks: list[Callable] = []

    def on_event(self, callback: Callable[[RegimeTransitionEvent], None]):
        """Register a callback for regime transition events."""
        self._callbacks.append(callback)

    def _read_regime_state(self) -> dict | None:
        """Read the current regime_state.json for enrichment."""
        try:
            if self.state_path.exists():
                return json.loads(self.state_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to read regime_state.json: %s", e)
        return None

    def _extract_top_asset(self, state: dict | None) -> tuple[str, str]:
        """Extract the top asset and its exchange from regime state.

        Returns (asset, exchange) tuple. Falls back to defaults.
        """
        if state and state.get("top_assets"):
            top = state["top_assets"][0]
            asset = top.get("asset", "UNKNOWN")
            exchange = top.get("exchange", self.default_exchange)
            return asset, exchange
        return "UNKNOWN", self.default_exchange

    def parse_event(self, line: str) -> RegimeTransitionEvent | None:
        """Parse a JSONL line into a RegimeTransitionEvent if applicable."""
        try:
            data = json.loads(line.strip())
        except (json.JSONDecodeError, ValueError):
            return None

        if data.get("event") != "regime_updated":
            return None

        new_regime_str = data.get("new_regime", "")
        prev_regime_str = data.get("previous_regime", "")

        new_regime = _REGIME_MAP.get(new_regime_str)
        prev_regime = _REGIME_MAP.get(prev_regime_str)

        if new_regime is None or prev_regime is None:
            logger.warning("Unknown regime value: %s -> %s", prev_regime_str, new_regime_str)
            return None

        # max_funding_apy is stored as decimal (1.50 = 150%)
        max_funding_decimal = data.get("max_funding_apy", 0.0)
        max_apy_annualized = max_funding_decimal * 100  # Convert to percentage

        # Enrich with top_asset from regime_state.json
        state = self._read_regime_state()
        asset, exchange = self._extract_top_asset(state)

        # Parse timestamp
        ts_str = data.get("timestamp")
        if ts_str:
            try:
                ts = datetime.fromisoformat(ts_str)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                ts = datetime.now(timezone.utc)
        else:
            ts = datetime.now(timezone.utc)

        return RegimeTransitionEvent(
            asset=asset,
            exchange=exchange,
            new_regime=new_regime,
            previous_regime=prev_regime,
            max_apy_annualized=max_apy_annualized,
            timestamp_utc=ts,
        )

    def read_new_lines(self) -> list[str]:
        """Read new lines from the JSONL file since last position."""
        if not self.jsonl_path.exists():
            return []

        try:
            file_size = self.jsonl_path.stat().st_size
        except OSError:
            return []

        # Handle file truncation (log rotation)
        if file_size < self._file_position:
            logger.info("JSONL file truncated (rotation?), resetting position")
            self._file_position = 0

        if file_size == self._file_position:
            return []

        lines = []
        with open(self.jsonl_path, "r") as f:
            f.seek(self._file_position)
            for line in f:
                stripped = line.strip()
                if stripped:
                    lines.append(stripped)
            self._file_position = f.tell()

        return lines

    def seek_to_end(self):
        """Move file position to end of file (skip existing events)."""
        if self.jsonl_path.exists():
            self._file_position = self.jsonl_path.stat().st_size
        else:
            self._file_position = 0

    def poll_once(self) -> list[RegimeTransitionEvent]:
        """Poll for new events. Returns list of parsed events."""
        lines = self.read_new_lines()
        events = []
        for line in lines:
            event = self.parse_event(line)
            if event is not None:
                events.append(event)
                for cb in self._callbacks:
                    try:
                        cb(event)
                    except Exception as e:
                        logger.error("Callback error: %s", e)
        return events

    async def watch(self) -> AsyncIterator[RegimeTransitionEvent]:
        """Async generator that yields regime transition events as they appear."""
        self._running = True
        logger.info(
            "Watching %s for regime transitions (poll every %.1fs)",
            self.jsonl_path, self.poll_interval,
        )

        while self._running:
            events = self.poll_once()
            for event in events:
                yield event

            await asyncio.sleep(self.poll_interval)

    def stop(self):
        """Stop the watch loop."""
        self._running = False
