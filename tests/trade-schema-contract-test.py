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
        os.environ["OPENCLAW_TRADING_MODE"] = "mixed"
        sys.modules.pop("config.runtime", None)
        sys.modules["requests"] = types.SimpleNamespace(post=lambda *args, **kwargs: None, get=lambda *args, **kwargs: None, Timeout=RuntimeError)

        from models.position_state import apply_trade_to_position_state, get_open_positions
        from models.trade_schema import normalize_trade_record, validate_trade_record

        polymarket_open = {
            "trade_id": "pm-1",
            "exchange": "Polymarket",
            "strategy": "polymarket_spread",
            "symbol": "pm-btc-up",
            "side": "YES",
            "entry_price": 0.42,
            "position_size": 10.0,
            "position_size_usd": 4.2,
            "status": "OPEN",
            "entry_timestamp": "2026-01-01T00:00:00+00:00",
            "market_id": "pm-btc-up",
            "market_question": "Will BTC close above 60k?",
            "token_id": "yes-token",
            "signal": {
                "exchange": "Hyperliquid",
                "strategy": "wrong_strategy",
            },
        }
        normalized_pm = normalize_trade_record(polymarket_open)
        assert normalized_pm["exchange"] == "Polymarket"
        assert normalized_pm["strategy"] == "polymarket_spread"
        assert normalized_pm["market_id"] == "pm-btc-up"
        assert normalized_pm["market_question"] == "Will BTC close above 60k?"
        assert normalized_pm["token_id"] == "yes-token"
        assert validate_trade_record(normalized_pm, context="schema-contract.polymarket-open")

        apply_trade_to_position_state(position_state, polymarket_open)
        open_positions = get_open_positions(position_state)
        assert len(open_positions) == 1, open_positions
        assert open_positions[0]["exchange"] == "Polymarket"
        assert open_positions[0]["strategy"] == "polymarket_spread"
        assert open_positions[0]["market_id"] == "pm-btc-up"
        assert open_positions[0]["market_question"] == "Will BTC close above 60k?"
        assert open_positions[0]["token_id"] == "yes-token"

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
                "signal": {
                    "exchange": "Polymarket",
                    "strategy": "bad_fallback",
                },
            },
            {
                "trade_id": "pm-closed-1",
                "exchange": "Polymarket",
                "strategy": "polymarket_spread",
                "symbol": "pm-btc-up",
                "side": "YES",
                "entry_price": 0.4,
                "exit_price": 0.5,
                "position_size": 10.0,
                "position_size_usd": 4.0,
                "realized_pnl_usd": 1.0,
                "realized_pnl_pct": 25.0,
                "status": "CLOSED",
                "exit_reason": "take_profit",
                "entry_timestamp": "2026-01-01T00:00:00+00:00",
                "exit_timestamp": "2026-01-01T01:00:00+00:00",
                "market_id": "pm-btc-up",
                "market_question": "Will BTC close above 60k?",
                "token_id": "yes-token",
                "signal": {
                    "exchange": "Hyperliquid",
                    "strategy": "bad_fallback",
                },
            },
        ]

        trade_log.parent.mkdir(parents=True, exist_ok=True)
        with open(trade_log, "w") as handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")

        dashboard_module = load_module("performance_dashboard_schema_contract", REPO_ROOT / "scripts" / "performance-dashboard.py")
        dashboard = dashboard_module.PerformanceDashboard()

        assert len(dashboard.hl_trades) == 1, dashboard.hl_trades
        assert dashboard.hl_trades[0]["exchange"] == "Hyperliquid"
        assert dashboard.hl_trades[0]["strategy"] == "funding_arbitrage"
        assert len(dashboard.pm_trades) == 1, dashboard.pm_trades
        assert dashboard.pm_trades[0]["exchange"] == "Polymarket"
        assert dashboard.pm_trades[0]["market_id"] == "pm-btc-up"
        assert dashboard.pm_trades[0]["market_question"] == "Will BTC close above 60k?"
        assert dashboard.pm_trades[0]["token_id"] == "yes-token"

        print("[OK] Canonical schema/state contracts hold across normalization, position state, and dashboard reads")
