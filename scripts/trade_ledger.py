#!/usr/bin/env python3
"""
Trade Ledger — Canonical trade logging with strict schema.

Every trade open and close writes to workspace/logs/trade-ledger.jsonl.
The edge analytics engine reads from this file only.

Usage:
    from scripts.trade_ledger import log_open, log_close, load_ledger
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.runtime import LOGS_DIR

LEDGER_FILE = LOGS_DIR / "trade-ledger.jsonl"

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

REQUIRED_OPEN_FIELDS = {
    "trade_id",          # unique identifier
    "event",             # "open"
    "timestamp_open",    # ISO 8601 UTC
    "exchange",          # "Hyperliquid" | "Polymarket"
    "asset",             # coin symbol or condition_id
    "direction",         # "long" | "short" | "yes" | "no"
    "strategy_tag",      # "funding_arb" | "momentum" | "mean_reversion" | etc
    "signal_score",      # numeric score from signal scanner
    "entry_price",       # float
    "position_size_usd", # float
    "entry_reason",      # structured: {"signal_type": ..., "funding_rate": ..., "volume_24h": ...}
    "market_conditions",  # {"volume_24h": ..., "funding_8h": ..., "mid_price": ...}
}

REQUIRED_CLOSE_FIELDS = {
    "trade_id",
    "event",             # "close"
    "timestamp_open",
    "timestamp_close",
    "exchange",
    "asset",
    "direction",
    "strategy_tag",
    "signal_score",
    "entry_price",
    "exit_price",
    "position_size_usd",
    "pnl_usd",
    "pnl_pct",
    "exit_reason",       # "tp" | "sl" | "timeout" | "manual" | "thesis_invalidated" | "circuit_breaker"
    "time_held_minutes",
    "max_drawdown_pct",  # max adverse move during hold (0 if not tracked)
    "funding_earned_usd", # net funding received (negative = paid)
    "entry_reason",
    "market_conditions",
}


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def log_open(
    trade_id: str,
    exchange: str,
    asset: str,
    direction: str,
    strategy_tag: str,
    signal_score: float,
    entry_price: float,
    position_size_usd: float,
    entry_reason: dict[str, Any],
    market_conditions: dict[str, Any],
) -> dict[str, Any]:
    """Log a trade open event. Returns the record."""
    record = {
        "trade_id": trade_id,
        "event": "open",
        "timestamp_open": datetime.now(timezone.utc).isoformat(),
        "exchange": exchange,
        "asset": asset,
        "direction": direction,
        "strategy_tag": strategy_tag,
        "signal_score": signal_score,
        "entry_price": entry_price,
        "position_size_usd": position_size_usd,
        "entry_reason": entry_reason,
        "market_conditions": market_conditions,
    }
    _append(record)
    return record


def log_close(
    trade_id: str,
    timestamp_open: str,
    exchange: str,
    asset: str,
    direction: str,
    strategy_tag: str,
    signal_score: float,
    entry_price: float,
    exit_price: float,
    position_size_usd: float,
    exit_reason: str,
    funding_earned_usd: float = 0.0,
    max_drawdown_pct: float = 0.0,
    entry_reason: dict[str, Any] | None = None,
    market_conditions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Log a trade close event with full P&L calculation."""
    now = datetime.now(timezone.utc)
    opened = datetime.fromisoformat(timestamp_open)
    if opened.tzinfo is None:
        opened = opened.replace(tzinfo=timezone.utc)
    held_min = (now - opened).total_seconds() / 60

    if direction in ("long", "yes"):
        pnl_pct = (exit_price - entry_price) / entry_price if entry_price > 0 else 0
    else:
        pnl_pct = (entry_price - exit_price) / entry_price if entry_price > 0 else 0
    pnl_usd = pnl_pct * position_size_usd + funding_earned_usd

    record = {
        "trade_id": trade_id,
        "event": "close",
        "timestamp_open": timestamp_open,
        "timestamp_close": now.isoformat(),
        "exchange": exchange,
        "asset": asset,
        "direction": direction,
        "strategy_tag": strategy_tag,
        "signal_score": signal_score,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "position_size_usd": position_size_usd,
        "pnl_usd": round(pnl_usd, 6),
        "pnl_pct": round(pnl_pct, 6),
        "exit_reason": exit_reason,
        "time_held_minutes": round(held_min, 1),
        "max_drawdown_pct": max_drawdown_pct,
        "funding_earned_usd": funding_earned_usd,
        "entry_reason": entry_reason or {},
        "market_conditions": market_conditions or {},
    }
    _append(record)
    return record


def _append(record: dict[str, Any]) -> None:
    LEDGER_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def load_ledger() -> list[dict[str, Any]]:
    """Load all ledger entries."""
    if not LEDGER_FILE.exists():
        return []
    entries = []
    with open(LEDGER_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return entries


def load_closed_trades() -> list[dict[str, Any]]:
    """Load only closed trade records."""
    return [e for e in load_ledger() if e.get("event") == "close"]


# ---------------------------------------------------------------------------
# Backfill historical trade (PROVE)
# ---------------------------------------------------------------------------

def backfill_prove():
    """Backfill the PROVE trade as trade #1."""
    # Check if already backfilled
    existing = load_ledger()
    if any(e.get("trade_id") == "hl-prove-20260326" for e in existing):
        return

    log_close(
        trade_id="hl-prove-20260326",
        timestamp_open="2026-03-26T01:13:54+00:00",
        exchange="Hyperliquid",
        asset="PROVE",
        direction="long",
        strategy_tag="funding_arb",
        signal_score=5.6,
        entry_price=0.29217,
        exit_price=0.28271,
        position_size_usd=14.90,
        exit_reason="thesis_invalidated",
        funding_earned_usd=-0.016,
        max_drawdown_pct=0.097,
        entry_reason={"signal_type": "funding_anomaly", "annualized_rate": -1.37, "volume_24h": 4112361},
        market_conditions={"funding_8h": -0.000514, "volume_24h": 4112361, "mid_price": 0.29217},
    )


if __name__ == "__main__":
    backfill_prove()
    trades = load_closed_trades()
    print(f"Closed trades: {len(trades)}")
    for t in trades:
        print(f"  {t['trade_id']}: {t['asset']} {t['direction']} | PnL: ${t['pnl_usd']:+.4f} ({t['pnl_pct']:+.1%}) | {t['exit_reason']}")
