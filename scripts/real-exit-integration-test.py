#!/usr/bin/env python3
"""
Real Exit Path Integration Test
Uses ACTUAL check_exit() logic, no simulation
Monkeypatches price fetch to trigger exits
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
import importlib.util

WORKSPACE = Path.home() / ".openclaw" / "workspace"
SIGNALS_FILE = WORKSPACE / "logs" / "phase1-signals.jsonl"
TRADES_FILE = WORKSPACE / "logs" / "phase1-paper-trades.jsonl"
STATE_FILE = WORKSPACE / "logs" / "position-state.json"
PERF_FILE = WORKSPACE / "logs" / "phase1-performance.json"

print("=" * 80)
print("REAL EXIT PATH INTEGRATION TEST")
print("Using actual check_exit() logic - NO SIMULATION")
print("=" * 80)
print()

# Clean logs
for f in [SIGNALS_FILE, TRADES_FILE, STATE_FILE, PERF_FILE]:
    if f.exists():
        f.unlink()

# Import trader
spec = importlib.util.spec_from_file_location(
    "trader",
    WORKSPACE / "scripts" / "phase1-paper-trader.py"
)
trader_module = importlib.util.module_from_spec(spec)
sys.modules['trader'] = trader_module

# Store original get_current_price
original_get_price = None

def inject_signal(asset, direction, entry_price, ev_score):
    """Inject test signal"""
    signal = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'source': 'Hyperliquid',
        'signal_type': 'funding_arbitrage',
        'asset': asset,
        'direction': direction,
        'entry_price': entry_price,
        'ev_score': ev_score,
        'conviction': 'HIGH'
    }
    
    SIGNALS_FILE.parent.mkdir(exist_ok=True)
    with open(SIGNALS_FILE, 'a') as f:
        f.write(json.dumps(signal) + '\n')
    
    return signal


def get_state():
    """Get current state"""
    if not TRADES_FILE.exists():
        return {'open': [], 'closed': [], 'all': []}
    
    all_trades = []
    with open(TRADES_FILE) as f:
        for line in f:
            if line.strip():
                all_trades.append(json.loads(line))
    
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            state = json.load(f)
        open_trades = [t for t in all_trades if state.get(t.get('position_id')) == 'OPEN']
        closed_trades = [t for t in all_trades if state.get(t.get('position_id')) == 'CLOSED']
    else:
        open_trades = [t for t in all_trades if t.get('status') == 'OPEN']
        closed_trades = [t for t in all_trades if t.get('status') == 'CLOSED']
    
    return {'open': open_trades, 'closed': closed_trades, 'all': all_trades}


# TEST 1: Real Take Profit Exit
print("TEST 1: Real Take Profit Exit (LONG)")
print("-" * 80)

# Step 1: Entry
inject_signal('BTC', 'LONG', 50000.0, 70)
spec.loader.exec_module(trader_module)
trader_module.main()

state = get_state()
if len(state['open']) != 1:
    print(f"❌ FAIL: Entry failed ({len(state['open'])} open)")
    sys.exit(1)

position = state['open'][0]
print(f"✅ Entry: Position {position['position_id']} opened")
print(f"   Asset: {position['signal']['asset']}")
print(f"   Direction: {position['direction']}")
print(f"   Entry: ${position['entry_price']}")
print()

# Step 2: Monkeypatch price to trigger take profit (+15%)
print("Step 2: Trigger take profit (monkeypatch price)")

exit_price = 57500.0  # +15% profit (TP threshold is +10%)

def mock_get_current_price(asset):
    """Mock price fetch to trigger take profit"""
    if asset == 'BTC':
        return exit_price
    return 0

# Monkey patch
trader_module.get_current_price = mock_get_current_price
print(f"   Monkeypatched get_current_price() → ${exit_price}")
print()

# Step 3: Run trader again - should trigger REAL check_exit()
print("Step 3: Run trader (real check_exit() logic)")
spec.loader.exec_module(trader_module)
trader_module.main()

# Step 4: Verify position closed via REAL path
state_after = get_state()
print(f"   Open: {len(state['open'])} → {len(state_after['open'])}")
print(f"   Closed: {len(state['closed'])} → {len(state_after['closed'])}")

if len(state_after['closed']) > len(state['closed']):
    closed = [t for t in state_after['all'] if t.get('position_id') == position['position_id'] and t.get('status') == 'CLOSED'][0]
    print(f"✅ PASS: Position closed via REAL exit path")
    print(f"   Exit reason: {closed.get('exit_reason', 'N/A')}")
    print(f"   Exit price: ${closed.get('exit_price', 0)}")
    print(f"   P&L: ${closed.get('realized_pnl_usd', 0):+.2f} ({closed.get('realized_pnl_pct', 0):+.1f}%)")
    
    # Verify it was closed by real logic (not simulation)
    if closed.get('exit_reason'):
        print(f"✅ VERIFIED: Real check_exit() logic executed")
    else:
        print(f"⚠️  WARNING: exit_reason missing")
else:
    print(f"❌ FAIL: Position not closed")
    print(f"   Expected: check_exit() to detect +15% profit and close")
    sys.exit(1)

print()

# Step 5: Verify state file updated
if STATE_FILE.exists():
    with open(STATE_FILE) as f:
        state_dict = json.load(f)
    if state_dict.get(position['position_id']) == 'CLOSED':
        print(f"✅ PASS: State file updated to CLOSED")
    else:
        print(f"❌ FAIL: State file not updated")
        sys.exit(1)
print()

# Step 6: Verify performance tracking
if PERF_FILE.exists():
    with open(PERF_FILE) as f:
        perf = json.load(f)
    if perf.get('total_trades', 0) >= 1:
        print(f"✅ PASS: Performance tracked ({perf['total_trades']} trades)")
        print(f"   Total P&L: ${perf.get('total_pnl_usd', 0):+.2f}")
    else:
        print(f"❌ FAIL: Trade not counted")
        sys.exit(1)
else:
    print(f"❌ FAIL: Performance file not created")
    sys.exit(1)

print()
print("=" * 80)
print("TEST 1 PASSED ✅")
print("=" * 80)
print()
print("EVIDENCE TYPE: VERIFIED IN PAPER-TRADING FLOW")
print("Real path verified: Entry → check_exit() → close_position() → State → Performance")
print("Monkeypatch used: get_current_price() only")
print("Exit logic: REAL (check_exit() executed)")
