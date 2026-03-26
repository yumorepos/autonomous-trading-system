#!/usr/bin/env python3
"""
CEO OVERRIDE: Manual entry for when signal scanner is broken.
Usage: python3 scripts/manual_entry.py PROVE
"""

import sys
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

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/manual_entry.py ASSET [SIZE_USD]")
        sys.exit(1)
    
    asset = sys.argv[1]
    size = float(sys.argv[2]) if len(sys.argv) > 2 else 15.0
    
    manual_entry(asset, size)
