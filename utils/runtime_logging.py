from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from models.exchange_metadata import paper_exchange_is_experimental

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKSPACE = REPO_ROOT / "workspace"


def current_workspace_root() -> Path:
    return Path(os.getenv("OPENCLAW_WORKSPACE", DEFAULT_WORKSPACE)).expanduser().resolve()


def current_trading_mode() -> str:
    raw_mode = os.getenv("OPENCLAW_TRADING_MODE") or os.getenv("OPENCLAW_SIGNAL_MODE") or "hyperliquid_only"
    normalized = str(raw_mode).strip().lower()
    return normalized if normalized in {"hyperliquid_only", "polymarket_only", "mixed"} else "hyperliquid_only"


def runtime_events_file() -> Path:
    return current_workspace_root() / "logs" / "runtime-events.jsonl"


def append_runtime_event(
    *,
    stage: str,
    message: str,
    exchange: str = "system",
    lifecycle_stage: str | None = None,
    status: str = "INFO",
    mode: str | None = None,
    metadata: dict[str, Any] | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    active_mode = mode or current_trading_mode()
    target_path = path or runtime_events_file()
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "exchange": exchange,
        "mode": active_mode,
        "stage": stage,
        "trade_lifecycle_stage": lifecycle_stage,
        "status": status,
        "message": message,
        "metadata": metadata or {},
        "paper_only": True,
        "experimental": paper_exchange_is_experimental(exchange),
    }
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with open(target_path, "a") as handle:
        handle.write(json.dumps(record) + "\n")
    return record
