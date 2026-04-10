#!/usr/bin/env python3
"""
Position Health Dashboard — Quick status check for open positions.

Usage:
    python3 scripts/position_health.py
"""

import json
import requests
from datetime import datetime, timezone

WALLET = "0x8743f51c57e90644a0c141eD99064C4e9efFC01c"
HL_API = "https://api.hyperliquid.xyz/info"

# Exit thresholds (from risk-guardian.py)
STOP_LOSS_ROE = -0.07           # -7%
TAKE_PROFIT_ROE = 0.10          # +10%
TRAILING_STOP_ACTIVATE = 0.02   # +2%

def get_positions():
    """Fetch current perp positions."""
    payload = {"type": "clearinghouseState", "user": WALLET}
    resp = requests.post(HL_API, json=payload)
    data = resp.json()
    return data.get("assetPositions", [])

def get_spot_balance():
    """Fetch spot USDC balance."""
    payload = {"type": "spotClearinghouseState", "user": WALLET}
    resp = requests.post(HL_API, json=payload)
    data = resp.json()
    
    for balance in data.get("balances", []):
        if balance["coin"] == "USDC":
            return float(balance["total"])
    return 0.0

def main():
    print("=" * 70)
    print("  POSITION HEALTH DASHBOARD")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print("=" * 70)
    print()
    
    # Capital
    spot = get_spot_balance()
    positions = get_positions()
    
    total_notional = 0
    total_pnl = 0
    
    print(f"CAPITAL:")
    print(f"  Spot USDC: ${spot:.2f}")
    
    if not positions:
        print()
        print("POSITIONS: None")
        return
    
    print()
    print(f"POSITIONS: {len(positions)}")
    print()
    
    for pos in positions:
        p = pos["position"]
        coin = p["coin"]
        size = float(p["szi"])
        entry_px = float(p["entryPx"])
        
        notional = float(p["positionValue"])
        unrealized_pnl = float(p["unrealizedPnl"])
        roe = float(p["returnOnEquity"]) * 100  # Already calculated by API
        
        # Calculate current mark price from position value
        mark_px = notional / abs(size) if size != 0 else entry_px
        
        total_notional += notional
        total_pnl += unrealized_pnl
        
        # Direction
        direction = "LONG" if size > 0 else "SHORT"
        
        # Status indicators
        status = []
        
        sl_threshold = STOP_LOSS_ROE * 100  # -7%
        tp_threshold = TAKE_PROFIT_ROE * 100  # +10%
        trailing_threshold = TRAILING_STOP_ACTIVATE * 100  # +2%
        
        if roe <= sl_threshold:
            status.append("🔴 AT/BELOW SL — WILL EXIT")
        elif roe >= tp_threshold:
            status.append("🟢 AT/ABOVE TP — WILL EXIT")
        elif roe >= trailing_threshold:
            status.append("🟡 TRAILING ACTIVE")
        
        # Distance to triggers
        sl_dist = abs(roe - sl_threshold)
        tp_dist = abs(tp_threshold - roe)
        
        print(f"  {coin} {direction}")
        print(f"    Size: {abs(size):.1f} @ ${entry_px} (mark ${mark_px})")
        print(f"    Notional: ${notional:.2f}")
        print(f"    ROE: {roe:+.2f}% | P&L: ${unrealized_pnl:+.2f}")
        
        if status:
            print(f"    Status: {' | '.join(status)}")
        else:
            print(f"    Distance: SL {sl_dist:.2f}% away | TP {tp_dist:.2f}% away")
        
        print()
    
    print("=" * 70)
    print(f"SUMMARY:")
    print(f"  Total deployed: ${total_notional:.2f}")
    print(f"  Total P&L: ${total_pnl:+.2f}")
    print(f"  Available: ${spot:.2f}")
    print(f"  Total capital: ${spot + total_notional + total_pnl:.2f}")
    print("=" * 70)

if __name__ == "__main__":
    main()
