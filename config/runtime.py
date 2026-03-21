from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_WORKSPACE = REPO_ROOT / "workspace"
WORKSPACE_ROOT = Path(os.getenv("OPENCLAW_WORKSPACE", _DEFAULT_WORKSPACE)).expanduser().resolve()
LOGS_DIR = WORKSPACE_ROOT / "logs"
DATA_DIR = WORKSPACE_ROOT / "data"

SUPPORTED_TRADING_MODES = {"hyperliquid_only", "polymarket_only", "mixed"}
_DEFAULT_TRADING_MODE = "hyperliquid_only"


def get_trading_mode() -> str:
    raw_mode = os.getenv("OPENCLAW_TRADING_MODE") or os.getenv("OPENCLAW_SIGNAL_MODE") or _DEFAULT_TRADING_MODE
    normalized = str(raw_mode).strip().lower()
    return normalized if normalized in SUPPORTED_TRADING_MODES else _DEFAULT_TRADING_MODE


TRADING_MODE = get_trading_mode()


def mode_includes_hyperliquid(mode: str | None = None) -> bool:
    active_mode = mode or TRADING_MODE
    return active_mode in {"hyperliquid_only", "mixed"}


def mode_includes_polymarket(mode: str | None = None) -> bool:
    active_mode = mode or TRADING_MODE
    return active_mode in {"polymarket_only", "mixed"}


for path in (WORKSPACE_ROOT, LOGS_DIR, DATA_DIR):
    path.mkdir(parents=True, exist_ok=True)
