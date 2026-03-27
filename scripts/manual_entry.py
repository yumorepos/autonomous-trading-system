#!/usr/bin/env python3
"""
⛔ DEPRECATED — DO NOT USE

This script is DISABLED. All trading is now handled by trading_engine.py.

Reason: Manual entries bypass capital protection. The engine enforces
        heartbeat checks and circuit breaker before all entries.

Migration: Use trading_engine.py (handles all entries with protection)

=== ORIGINAL DOCSTRING (PRESERVED) ===
CEO OVERRIDE: Manual entry for when signal scanner is broken.
Usage: python3 scripts/manual_entry.py PROVE
"""

# Minimal imports for abort message
import sys

# ABORT BEFORE ANY TRADING CODE LOADS
if __name__ == "__main__":
    print("=" * 70)
    print("⛔ SCRIPT DISABLED")
    print("=" * 70)
    print()
    print("Manual entry is disabled to prevent bypass of capital protection.")
    print()
    print("All entries must go through: scripts/trading_engine.py")
    print()
    print("Reason: Engine enforces heartbeat + circuit breaker checks.")
    print()
    print("If you need to manually open a position (extreme emergency):")
    print("  1. Stop engine: launchctl unload ~/Library/LaunchAgents/com.ats.trading-engine.plist")
    print("  2. Use Hyperliquid web UI (prevents automated bypass)")
    print("  3. Restart engine: launchctl load ~/Library/LaunchAgents/com.ats.trading-engine.plist")
    print()
    sys.exit(1)

# === UNREACHABLE CODE (PRESERVED FOR REFERENCE) ===

import os
from pathlib import Path

# Set live mode
os.environ["ENTRY_MODE"] = "live"

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.utils.hyperliquid_client import get_hl_client
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants
from eth_account import Account
import json

def manual_entry(asset: str, size_usd: float = 15.0):
    """Execute manual entry with CEO override."""
    
    print(f"=== CEO MANUAL ENTRY: {asset} ===")
    print()
    
    # Get account
    private_key = os.environ["HL_PRIVATE_KEY"]
    account = Account.from_key(private_key)
    exchange = Exchange(account, constants.MAINNET_API_URL)
    
    # Get current price
    client = get_hl_client()
    mid = client.get_mid(asset)
    
    if not mid:
        print(f"❌ Can't get mid price for {asset}")
        return
    
    print(f"Asset: {asset}")
    print(f"Mid price: ${mid}")
    print(f"Position size: ${size_usd}")
    
    # Calculate size in coins (3x leverage)
    leverage = 3
    coins = (size_usd * leverage) / mid
    
    print(f"Coins: {coins:.2f}")
    print(f"Notional: ${coins * mid:.2f}")
    print()
    
    # Confirm
    confirm = input("Execute? (yes/no): ")
    if confirm.lower() != "yes":
        print("Cancelled")
        return
    
    # Execute market buy
    print("Executing market buy...")
    
    try:
        response = exchange.market_open(asset, True, coins, None, 0.05)  # 5% slippage
        print(json.dumps(response, indent=2))
        
        # Log to entry log
        log_file = Path("workspace/logs/hl-entry.jsonl")
        log_entry = {
            "timestamp": str(pd.Timestamp.now(tz='UTC')),
            "action": "CEO_MANUAL_ENTRY",
            "asset": asset,
            "size": coins,
            "mid_price": mid,
            "notional_usd": size_usd,
            "exchange_response": response,
        }
        with log_file.open("a") as f:
            f.write(json.dumps(log_entry) + "\n")
        
        print()
        print(f"✅ Entry logged to {log_file}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return

# if __name__ == "__main__" block moved to top (abort before imports)
