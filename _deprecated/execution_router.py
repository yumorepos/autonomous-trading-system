#!/usr/bin/env python3
"""Execution Router — Routes signals to the appropriate exchange executor."""

from __future__ import annotations

import os
from typing import Any

try:
    from utils.paper_exchange_adapters import PaperExchangeAdapter, get_paper_exchange_adapter
except ImportError:
    PaperExchangeAdapter = None

    def get_paper_exchange_adapter(name: str):  # type: ignore[misc]
        return None


class ExecutionRouter:
    """Route signals to Polymarket or Hyperliquid executors."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.pm_live = False
        self.pm_executor = None
        self.hl_live = False

    def route_signal(self, signal: dict[str, Any]):
        """
        Route signal to appropriate executor.
        Returns: (exchange_name, live_mode, executor_or_adapter)
        """
        exchange = signal.get("exchange", "").lower()

        if "polymarket" in exchange:
            if self.pm_live and self.pm_executor:
                return "Polymarket", True, self.pm_executor
            else:
                adapter = get_paper_exchange_adapter("Polymarket")
                return "Polymarket", False, adapter

        elif "hyperliquid" in exchange:
            if self.hl_live:
                print("[ROUTER] Hyperliquid live execution not implemented")
                adapter = get_paper_exchange_adapter("Hyperliquid")
                return "Hyperliquid", False, adapter
            else:
                adapter = get_paper_exchange_adapter("Hyperliquid")
                return "Hyperliquid", False, adapter

        else:
            adapter = get_paper_exchange_adapter("Hyperliquid")
            return "Hyperliquid", False, adapter

    def execute_trade(self, signal: dict[str, Any]) -> dict[str, Any]:
        """Execute trade based on routing."""
        exchange, live_mode, executor = self.route_signal(signal)

        if live_mode:
            if exchange == "Polymarket":
                token_id = signal.get("market_id") or signal.get("asset", "")
                side = signal.get("direction", "").upper()
                size = signal.get("recommended_position_size_usd", 0)
                price = signal.get("entry_price", 0.5)
                return executor.execute_order(token_id, side, size, price)
            else:
                return {
                    "success": False,
                    "error": f"Live execution for {exchange} not implemented",
                    "exchange": exchange,
                }

        else:
            if PaperExchangeAdapter and isinstance(executor, PaperExchangeAdapter):
                try:
                    from scripts.phase1_paper_trader import PaperTradeEngine
                    position_id = f"paper-{exchange}-{os.urandom(4).hex()}"
                    engine = PaperTradeEngine(
                        signal=signal,
                        position_id=position_id,
                        exchange=exchange,
                    )
                    return engine.execute()
                except Exception as e:
                    return {
                        "success": False,
                        "error": str(e),
                        "exchange": exchange,
                    }
            else:
                return {
                    "success": False,
                    "error": f"No executor available for {exchange}",
                    "exchange": exchange,
                }


def test_routing() -> None:
    """Test execution routing."""
    router = ExecutionRouter(dry_run=True)

    test_signals = [
        {
            "exchange": "Polymarket",
            "market_id": "pm-btc-test",
            "asset": "pm-btc-test",
            "direction": "YES",
            "entry_price": 0.42,
            "recommended_position_size_usd": 3.0,
        },
        {
            "exchange": "Hyperliquid",
            "asset": "ETH",
            "direction": "LONG",
            "entry_price": 3500.0,
            "recommended_position_size_usd": 12.0,
        },
    ]

    for signal in test_signals:
        exchange, live_mode, executor = router.route_signal(signal)
        print(f"Signal {signal['asset']} -> {exchange} (live={live_mode}, executor={executor})")
        result = router.execute_trade(signal)
        print(f"Result: {result.get('success', False)}")


if __name__ == "__main__":
    test_routing()
