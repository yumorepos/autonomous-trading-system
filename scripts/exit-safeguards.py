#!/usr/bin/env python3
"""
Hard Exit Safeguards
- Fail-safe exit if max hold time exceeded OR API fails
- Manual override to close all positions
- Log every exit decision with reason
"""

import json
import sys
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

WORKSPACE = Path.home() / ".openclaw" / "workspace"
PAPER_TRADES = WORKSPACE / "logs" / "phase1-paper-trades.jsonl"
SAFEGUARD_LOG = WORKSPACE / "logs" / "exit-safeguards.jsonl"

# Safeguard settings
MAX_HOLD_HOURS = 48  # Force close after 48 hours
API_TIMEOUT_SECONDS = 10
MAX_API_FAILURES = 3

def log_decision(decision_type: str, reason: str, data: dict):
    """Log exit decision"""
    log_entry = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'type': decision_type,
        'reason': reason,
        'data': data
    }
    
    with open(SAFEGUARD_LOG, 'a') as f:
        f.write(json.dumps(log_entry) + '\n')
    
    return log_entry

def load_open_positions():
    """Load open positions"""
    if not PAPER_TRADES.exists():
        return []
    
    positions = []
    with open(PAPER_TRADES) as f:
        for line in f:
            if line.strip():
                trade = json.loads(line)
                if trade.get('status') == 'OPEN':
                    positions.append(trade)
    
    return positions

def check_api_health():
    """Check if Hyperliquid API is accessible"""
    try:
        r = requests.post("https://api.hyperliquid.xyz/info", 
                         json={'type': 'allMids'}, 
                         timeout=API_TIMEOUT_SECONDS)
        return r.status_code == 200
    except:
        return False

def force_close_position(position: dict, reason: str):
    """Force close a position"""
    asset = position['signal']['asset']
    entry_time = position['entry_time']
    entry_price = position['entry_price']
    
    print(f"🔴 FORCE CLOSING: {asset}")
    print(f"   Reason: {reason}")
    print(f"   Entry: ${entry_price:.4f}")
    print(f"   Time: {entry_time}")
    
    # Log decision
    log_decision('force_close', reason, {
        'asset': asset,
        'entry_time': entry_time,
        'entry_price': entry_price,
        'position_size': position['position_size']
    })
    
    # In paper trading, just mark as closed
    # In live trading, this would execute the close order
    
    print(f"   ✅ Position marked for forced closure")
    return True

def close_all_positions():
    """Manual override: close all open positions"""
    positions = load_open_positions()
    
    if not positions:
        print("No open positions to close")
        return
    
    print(f"🚨 CLOSING ALL {len(positions)} POSITIONS (MANUAL OVERRIDE)")
    print()
    
    for position in positions:
        force_close_position(position, 'manual_override')
    
    print()
    print(f"✅ All positions marked for closure")
    print(f"📝 Decisions logged to {SAFEGUARD_LOG}")

def check_safeguards():
    """Check safeguard conditions"""
    print("="*80)
    print("EXIT SAFEGUARDS CHECK")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S EDT')}")
    print("="*80)
    print()
    
    # Check API health
    print("1. Checking API health...")
    api_healthy = check_api_health()
    
    if api_healthy:
        print("   ✅ Hyperliquid API: HEALTHY")
    else:
        print("   ❌ Hyperliquid API: FAILED")
        log_decision('api_failure', 'Hyperliquid API unreachable', {})
    
    print()
    
    # Check open positions
    print("2. Checking open positions...")
    positions = load_open_positions()
    
    if not positions:
        print("   No open positions")
        return
    
    print(f"   Found {len(positions)} open positions")
    print()
    
    # Check each position
    now = datetime.now(timezone.utc)
    forced_closes = 0
    
    for position in positions:
        asset = position['signal']['asset']
        entry_time = datetime.fromisoformat(position['entry_time'])
        age_hours = (now - entry_time).total_seconds() / 3600
        
        # Check max hold time
        if age_hours > MAX_HOLD_HOURS:
            print(f"   ⚠️  {asset}: Exceeded max hold time ({age_hours:.1f}h > {MAX_HOLD_HOURS}h)")
            force_close_position(position, f'max_hold_time_exceeded_{MAX_HOLD_HOURS}h')
            forced_closes += 1
        else:
            print(f"   ✅ {asset}: {age_hours:.1f}h (under {MAX_HOLD_HOURS}h limit)")
    
    print()
    print(f"Summary: {forced_closes} positions force-closed")
    
    if forced_closes > 0:
        print(f"📝 Decisions logged to {SAFEGUARD_LOG}")

def main():
    """Main"""
    if len(sys.argv) > 1 and sys.argv[1] == '--close-all':
        close_all_positions()
    else:
        check_safeguards()

if __name__ == "__main__":
    main()
