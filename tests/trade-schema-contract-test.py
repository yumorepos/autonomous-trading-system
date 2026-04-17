#!/usr/bin/env python3
"""Canonical schema/state contract checks for runtime producers and readers."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="openclaw-schema-contract-") as temp_dir:
        workspace_root = Path(temp_dir)
        logs_dir = workspace_root / "logs"
        trade_log = logs_dir / "phase1-paper-trades.jsonl"
        position_state = logs_dir / "position-state.json"

        os.environ["OPENCLAW_WORKSPACE"] = str(workspace_root)
        os.environ["OPENCLAW_TRADING_MODE"] = "hyperliquid_only"
        sys.modules.pop("config.runtime", None)
        sys.modules["requests"] = types.SimpleNamespace(post=lambda *args, **kwargs: None, get=lambda *args, **kwargs: None, Timeout=RuntimeError)

        from models.position_state import apply_trade_to_position_state, get_open_positions
        from models.trade_schema import normalize_trade_record, validate_trade_record

        hyperliquid_open = {
            "trade_id": "hl-open-1",
            "exchange": "Hyperliquid",
            "strategy": "funding_arbitrage",
            "symbol": "BTC",
            "side": "LONG",
            "entry_price": 50000.0,
            "position_size": 0.001,
            "position_size_usd": 50.0,
            "status": "OPEN",
            "entry_timestamp": "2026-01-01T00:05:00+00:00",
        }
        normalized_hl = normalize_trade_record(hyperliquid_open)
        assert normalized_hl["exchange"] == "Hyperliquid"
        assert normalized_hl["strategy"] == "funding_arbitrage"
        assert normalized_hl["symbol"] == "BTC"
        assert validate_trade_record(normalized_hl, context="schema-contract.hyperliquid-open")

        apply_trade_to_position_state(position_state, hyperliquid_open)
        open_positions = get_open_positions(position_state)
        assert len(open_positions) == 1, open_positions
        assert open_positions[0]["exchange"] == "Hyperliquid"
        assert open_positions[0]["symbol"] == "BTC"

        records = [
            {
                "trade_id": "hl-closed-1",
                "exchange": "Hyperliquid",
                "strategy": "funding_arbitrage",
                "symbol": "BTC",
                "side": "LONG",
                "entry_price": 100.0,
                "exit_price": 110.0,
                "position_size": 1.0,
                "position_size_usd": 100.0,
                "realized_pnl_usd": 10.0,
                "realized_pnl_pct": 10.0,
                "status": "CLOSED",
                "exit_reason": "take_profit",
                "entry_timestamp": "2026-01-01T00:00:00+00:00",
                "exit_timestamp": "2026-01-01T01:00:00+00:00",
            },
        ]

        trade_log.parent.mkdir(parents=True, exist_ok=True)
        with open(trade_log, "w") as handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")

        dashboard_module = load_module("performance_dashboard_schema_contract", REPO_ROOT / "scripts" / "support" / "performance-dashboard.py")
        dashboard = dashboard_module.PerformanceDashboard()

        assert len(dashboard.hl_trades) == 1, dashboard.hl_trades
        assert dashboard.hl_trades[0]["exchange"] == "Hyperliquid"
        assert dashboard.hl_trades[0]["strategy"] == "funding_arbitrage"

        print("[OK] Canonical schema/state contracts hold for Hyperliquid across normalization, position state, and dashboard reads")
