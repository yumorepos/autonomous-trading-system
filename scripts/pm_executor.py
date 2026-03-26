#!/usr/bin/env python3
"""
Polymarket Executor — Verified CLOB execution path.

Based on verified implementation from polymarket-trader/execute_trade.py.
Uses py_clob_client with signature_type=2 (GNOSIS_SAFE).

Security: All secrets from environment variables only.
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

EXECUTION_LOG = LOGS_DIR / "pm-execution.jsonl"

class PolymarketExecutor:
    """Verified Polymarket execution client."""
    
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        
        # Load credentials from environment ONLY
        self.private_key = os.environ.get("PM_PRIVATE_KEY", "")
        self.funder_address = os.environ.get("PM_FUNDER_ADDRESS", "")
        
        # Verified configuration
        self.host = "https://clob.polymarket.com"
        self.chain_id = 137  # Polygon mainnet
        self.signature_type = 2  # GNOSIS_SAFE (verified working)
        
        self.client = None
        self.live_mode = False
        
        if self.private_key and not dry_run:
            try:
                from py_clob_client.client import ClobClient
                
                # Step 1: Derive API credentials (verified path)
                temp_client = ClobClient(
                    host=self.host,
                    key=self.private_key,
                    chain_id=self.chain_id
                )
                api_creds = temp_client.create_or_derive_api_creds()
                
                # Step 2: Initialize trading client (verified path)
                self.client = ClobClient(
                    host=self.host,
                    key=self.private_key,
                    chain_id=self.chain_id,
                    creds=api_creds,
                    signature_type=self.signature_type,
                    funder=self.funder_address or ""
                )
                
                self.live_mode = True
                print(f"[PM] Live client initialized (signature_type={self.signature_type})")
                
            except ImportError:
                print("[PM] py_clob_client not installed")
                print("[PM] Install with: pip install py-clob-client")
            except Exception as e:
                print(f"[PM] Failed to initialize client: {e}")
        
    def log_execution(self, event: dict[str, Any]) -> None:
        """Log execution event."""
        event["timestamp"] = datetime.now(timezone.utc).isoformat()
        EXECUTION_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(EXECUTION_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
    
    def execute_order(self, token_id: str, side: str, size: float, price: float) -> dict[str, Any]:
        """Execute order using verified CLOB path."""
        
        if self.dry_run:
            order_id = f"paper-pm-{int(datetime.now(timezone.utc).timestamp() * 1000)}"
            result = {
                "success": True,
                "order_id": order_id,
                "token_id": token_id,
                "side": side,
                "size": size,
                "price": price,
                "dry_run": True,
                "live": False,
            }
            self.log_execution({
                "action": "place",
                "exchange": "Polymarket",
                "token_id": token_id,
                "side": side,
                "result": "success",
                "dry_run": True,
            })
            return result
        
        if not self.live_mode or not self.client:
            return {
                "success": False,
                "error": "Live trading not enabled",
                "token_id": token_id,
                "side": side,
            }
        
        try:
            from py_clob_client.clob_types import OrderArgs, OrderType
            from py_clob_client.order_builder.constants import BUY, SELL
            
            order_side = BUY if side.upper() == "YES" else SELL
            
            # VERIFIED PATH: create_and_post_order
            response = self.client.create_and_post_order(
                OrderArgs(
                    token_id=token_id,
                    price=price,
                    size=size,
                    side=order_side,
                ),
                options={
                    "tick_size": "0.01",
                    "neg_risk": False,
                },
                order_type=OrderType.GTC  # Good Till Cancelled
            )
            
            result = {
                "success": True,
                "order_id": response.get("orderID", f"pm-{int(datetime.now(timezone.utc).timestamp() * 1000)}"),
                "token_id": token_id,
                "side": side,
                "size": size,
                "price": price,
                "response": response,
                "live": True,
                "signature_type": self.signature_type,
            }
            
            self.log_execution({
                "action": "place",
                "exchange": "Polymarket",
                "token_id": token_id,
                "side": side,
                "order_id": result["order_id"],
                "result": "success",
                "live": True,
            })
            
            return result
            
        except Exception as e:
            result = {
                "success": False,
                "error": str(e),
                "token_id": token_id,
                "side": side,
                "live": True,
            }
            
            self.log_execution({
                "action": "place",
                "exchange": "Polymarket",
                "token_id": token_id,
                "side": side,
                "result": "failed",
                "error": str(e),
                "live": True,
            })
            
            return result
    
    def cancel_order(self, order_id: str) -> dict[str, Any]:
        """Cancel an order."""
        if not self.live_mode or not self.client:
            return {
                "success": False,
                "error": "Live trading not enabled",
                "order_id": order_id,
            }
        
        try:
            response = self.client.cancel(order_id=order_id)
            
            self.log_execution({
                "action": "cancel",
                "exchange": "Polymarket",
                "order_id": order_id,
                "result": "success",
            })
            
            return {
                "success": True,
                "order_id": order_id,
                "response": response,
            }
            
        except Exception as e:
            self.log_execution({
                "action": "cancel",
                "exchange": "Polymarket",
                "order_id": order_id,
                "result": "failed",
                "error": str(e),
            })
            
            return {
                "success": False,
                "error": str(e),
                "order_id": order_id,
            }


def main() -> None:
    """Test executor."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Polymarket Executor")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without executing")
    
    args = parser.parse_args()
    
    executor = PolymarketExecutor(dry_run=args.dry_run)
    
    print(f"Live mode: {executor.live_mode}")
    print(f"Signature type: {executor.signature_type}")
    print(f"Environment check:")
    print(f"  PM_PRIVATE_KEY: {'[SET]' if executor.private_key else 'not set'}")
    print(f"  PM_FUNDER_ADDRESS: {'[SET]' if executor.funder_address else 'not set'}")
    
    # Test with sample order
    test_result = executor.execute_order(
        token_id="test-token",
        side="YES",
        size=5.0,
        price=0.55
    )
    
    print(f"\nTest execution: {test_result.get('success', False)}")
    print(f"Dry run: {args.dry_run}")
    print(f"Live: {executor.live_mode}")


if __name__ == "__main__":
    main()