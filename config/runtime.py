from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_WORKSPACE = REPO_ROOT / "workspace"
WORKSPACE_ROOT = Path(os.getenv("OPENCLAW_WORKSPACE", _DEFAULT_WORKSPACE)).expanduser().resolve()
LOGS_DIR = WORKSPACE_ROOT / "logs"
DATA_DIR = WORKSPACE_ROOT / "data"

TRADING_MODE = "hyperliquid_only"


for path in (WORKSPACE_ROOT, LOGS_DIR, DATA_DIR):
    path.mkdir(parents=True, exist_ok=True)
