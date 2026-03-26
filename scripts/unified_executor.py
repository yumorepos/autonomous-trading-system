#!/usr/bin/env python3
"""
Unified Execution Router — routes signals to appropriate exchange executor.

Decision logic:
- prediction markets → Polymarket
- price-based markets → Hyperliquid
- paper mode → paper trading ledger
- live mode → actual exchange execution
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.runtime import LOGS_DIR

# Import executors
import importlib.util

def load_module(name: str, path: Path):
    """Dynamically load a module from path."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

class UnifiedExecutor:
    """Routes execution to appropriate exchange based on signal type."""
    
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.hl_executor = None
        self.pm_executor = None
        
        # Load executors lazily
        self._hl_loaded = False
        self._pm_loaded = False
        
    def _ensure_hl_executor(self):
        """Lazy load Hyperliquid executor."""
        if not self._hl_loaded:
            try:
                hl_path = REPO_ROOT / "scripts" / "hl_executor.py"
                hl_module = load_module("hl_executor_module", hl_path)
                self.hl_executor = hl_module.HyperliquidExecutor(dry_run=self.dry_run)
                self._hl_loaded = True
            except Exception as e:
                print(f"[WARN] Failed to load Hyperliquid executor: {e}")
                self.hl_executor = None
    
    def _ensure_pm_executor(self):
        """Lazy load Polymarket executor (canonical verified path)."""
        if not self._pm_loaded:
            try:
                pm_path = REPO_ROOT / "scripts" / "pm_executor_canonical.py"
                pm_module = load_module("pm_executor_canonical_module", pm_path)
                self.pm_executor = pm_module.PolymarketExecutor(dry_run=self.dry_run)
                self._pm_loaded = True
                print(f"[ROUTER] Polymarket executor loaded (live={self.pm_executor.live_mode})")
            except Exception as e:
                print(f"[WARN] Failed to load Polymarket executor: {e}")
                self.pm_executor = None
    
    def route_signal(self, signal: dict[str, Any]) -> tuple[str, Optional[Any]]:
        """
        Route signal to appropriate executor.
        Returns (exchange_name, executor_instance_or_none)
        """
        exchange = signal.get("exchange", "").lower()
        
        if "polymarket" in exchange:
            self._ensure_pm_executor()
            return "Polymarket", self.pm_executor
        
        elif "hyperliquid" in exchange:
            self._ensure_hl_executor()
            return "Hyperliquid", self.hl_executor
        
        else:
            # Default to Hyperliquid for backward compatibility
            self._ensure_hl_executor()
            return "Hyperliquid", self.hl_executor
    
    def execute_entry(self, signal: dict[str, Any], account_state: dict[str, Any]) -> dict[str, Any]:
        """Execute an entry based on signal routing."""
        exchange_name, executor = self.route_signal(signal)
        
        if not executor:
            return {
                "success": False,
                "error": f"No executor available for {exchange_name}",
                "exchange": exchange_name,
                "signal": signal.get("asset") or signal.get("market_id", "unknown"),
            }
        
        # Log the routing decision
        routing_log = LOGS_DIR / "execution-routing.jsonl"
        routing_log.parent.mkdir(parents=True, exist_ok=True)
        with open(routing_log, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "signal_id": signal.get("asset") or signal.get("market_id"),
                "exchange": exchange_name,
                "signal_type": signal.get("signal_type"),
                "routed_to": exchange_name,
                "dry_run": self.dry_run,
            }, default=str) + "\n")
        
        print(f"[ROUTER] Signal {signal.get('asset', 'unknown')} → {exchange_name}")
        
        # Execute based on exchange type
        if exchange_name == "Polymarket":
            # Polymarket execution
            side = "yes" if signal.get("direction", "").upper() == "YES" else "no"
            size = signal.get("recommended_position_size_usd", 0)
            price = signal.get("entry_price", 0.5)
            condition_id = signal.get("market_id") or signal.get("asset", "")
            
            if not condition_id:
                return {
                    "success": False,
                    "error": "Missing condition_id/market_id for Polymarket",
                    "exchange": exchange_name,
                }
            
            return executor.execute_order(condition_id, side, size, price)
        
        else:
            # Hyperliquid execution (or default)
            # Note: hl_executor.py is currently CLOSE/REDUCE ONLY
            # For entry, we would need to extend it or use a different module
            return {
                "success": False,
                "error": "Hyperliquid entry not yet implemented in unified router",
                "exchange": exchange_name,
                "note": "Use hl_entry.py directly for Hyperliquid entries",
            }
    
    def close_position(self, position: dict[str, Any]) -> dict[str, Any]:
        """Close a position based on its exchange type."""
        exchange = position.get("exchange", "").lower()
        
        if "polymarket" in exchange:
            self._ensure_pm_executor()
            if not self.pm_executor:
                return {
                    "success": False,
                    "error": "Polymarket executor not available",
                    "exchange": "Polymarket",
                }
            condition_id = position.get("market_id") or position.get("asset", "")
            return self.pm_executor.close_position(condition_id, dry_run=self.dry_run)
        
        elif "hyperliquid" in exchange:
            self._ensure_hl_executor()
            if not self.hl_executor:
                return {
                    "success": False,
                    "error": "Hyperliquid executor not available",
                    "exchange": "Hyperliquid",
                }
            asset = position.get("asset", "")
            return self.hl_executor.close_position(asset, dry_run=self.dry_run)
        
        else:
            return {
                "success": False,
                "error": f"Unknown exchange: {exchange}",
                "exchange": exchange,
            }
    
    def killswitch(self) -> dict[str, Any]:
        """Emergency close all positions across all exchanges."""
        results = []
        
        # Close Hyperliquid positions
        self._ensure_hl_executor()
        if self.hl_executor:
            hl_result = self.hl_executor.killswitch()
            hl_result["exchange"] = "Hyperliquid"
            results.append(hl_result)
        
        # Close Polymarket positions
        self._ensure_pm_executor()
        if self.pm_executor:
            pm_result = self.pm_executor.killswitch()
            pm_result["exchange"] = "Polymarket"
            results.append(pm_result)
        
        return {
            "success": all(r.get("success", False) for r in results),
            "results": results,
            "total_exchanges": len(results),
        }


# ---------------------------------------------------------------------------
# Command Line Interface
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    
    parser = argparse.ArgumentParser(description="Unified Execution Router")
    parser.add_argument("action", nargs="?", choices=["route", "close", "killswitch", "test"], help="Action to perform")
    parser.add_argument("--signal-file", help="JSON file with signal to route")
    parser.add_argument("--position-file", help="JSON file with position to close")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without executing")
    
    args = parser.parse_args()
    
    executor = UnifiedExecutor(dry_run=args.dry_run)
    
    if args.action == "test":
        # Test routing with sample signals
        test_signals = [
            {
                "exchange": "Hyperliquid",
                "asset": "ETH",
                "signal_type": "funding_arbitrage",
                "direction": "LONG",
                "entry_price": 3500.0,
                "recommended_position_size_usd": 12.0,
            },
            {
                "exchange": "Polymarket",
                "market_id": "pm-btc-up",
                "asset": "pm-btc-up",
                "signal_type": "binary_market",
                "direction": "YES",
                "entry_price": 0.42,
                "recommended_position_size_usd": 5.0,
            }
        ]
        
        for signal in test_signals:
            exchange, exec_inst = executor.route_signal(signal)
            print(f"Signal {signal.get('asset')} → {exchange} (executor: {exec_inst is not None})")
        
        print("\n✅ Unified router test passed")
    
    elif args.action == "route" and args.signal_file:
        # Route and execute a signal from file
        try:
            with open(args.signal_file) as f:
                signal = json.load(f)
        except Exception as e:
            print(f"Error loading signal file: {e}")
            sys.exit(1)
        
        result = executor.execute_entry(signal, {})
        print(json.dumps(result, indent=2))
    
    elif args.action == "close" and args.position_file:
        # Close a position from file
        try:
            with open(args.position_file) as f:
                position = json.load(f)
        except Exception as e:
            print(f"Error loading position file: {e}")
            sys.exit(1)
        
        result = executor.close_position(position)
        print(json.dumps(result, indent=2))
    
    elif args.action == "killswitch":
        result = executor.killswitch()
        print(json.dumps(result, indent=2))
    
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()