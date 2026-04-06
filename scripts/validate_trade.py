#!/usr/bin/env python3
"""
Strict trade validation: Verify all 5 proof sources for a given trade.
"""

import json
import sys
from pathlib import Path
from hyperliquid.info import Info
from hyperliquid.utils import constants

ENGINE_ADDRESS = "0x8743f51c57e90644a0c141eD99064C4e9efFC01c"

def validate_trade(coin: str) -> dict:
    """
    Validate a trade has all 5 proofs.
    
    Returns dict with:
        - valid: bool
        - proofs: dict of proof results
        - issues: list of problems found
    """
    info = Info(constants.MAINNET_API_URL, skip_ws=True)
    issues = []
    proofs = {}
    
    # PROOF 1: Exchange fill
    fills = info.user_fills(ENGINE_ADDRESS)
    fill_found = any(f['coin'] == coin for f in fills[:10])  # Check last 10 fills
    proofs['exchange_fill'] = fill_found
    if not fill_found:
        issues.append(f"No exchange fill found for {coin}")
    else:
        fill = next(f for f in fills if f['coin'] == coin)
        proofs['fill_data'] = {
            'price': fill['px'],
            'size': fill['sz'],
            'side': fill['side'],
            'time': fill['time'],
        }
    
    # PROOF 2: Exchange position
    state = info.user_state(ENGINE_ADDRESS)
    positions = state.get('assetPositions', [])
    position_found = any(ap['position']['coin'] == coin for ap in positions)
    proofs['exchange_position'] = position_found
    if not position_found:
        issues.append(f"No exchange position found for {coin}")
    else:
        pos = next(ap['position'] for ap in positions if ap['position']['coin'] == coin)
        proofs['position_data'] = {
            'size': pos['szi'],
            'entry_price': pos.get('entryPx'),
            'unrealized_pnl': pos.get('unrealizedPnl'),
            'leverage': pos.get('leverage', {}).get('value'),
        }
    
    # PROOF 3: Log event
    log_file = Path("workspace/logs/trading_engine.jsonl")
    if not log_file.exists():
        issues.append("Trading engine log file not found")
        proofs['log_event'] = False
    else:
        with open(log_file) as f:
            lines = f.readlines()
        events = [json.loads(l) for l in lines if l.strip()]
        filled_events = [e for e in events if e.get('event') == 'order_filled' and e.get('coin') == coin]
        proofs['log_event'] = len(filled_events) > 0
        if not filled_events:
            issues.append(f"No order_filled event found for {coin}")
        else:
            proofs['log_data'] = filled_events[-1]  # Most recent
    
    # PROOF 4: Ledger entry
    ledger_file = Path("workspace/logs/trade-ledger.jsonl")
    if not ledger_file.exists():
        issues.append("Trade ledger file not found")
        proofs['ledger_entry'] = False
    else:
        with open(ledger_file) as f:
            lines = f.readlines()
        entries = [json.loads(l) for l in lines if l.strip()]
        entry_events = [e for e in entries if e.get('action') == 'entry' and e.get('coin') == coin]
        proofs['ledger_entry'] = len(entry_events) > 0
        if not entry_events:
            issues.append(f"No ledger entry found for {coin}")
        else:
            proofs['ledger_data'] = entry_events[-1]  # Most recent
    
    # PROOF 5: Internal state
    state_file = Path("workspace/logs/trading_engine_state.json")
    if not state_file.exists():
        issues.append("Engine state file not found")
        proofs['internal_state'] = False
    else:
        with open(state_file) as f:
            engine_state = json.load(f)
        open_positions = engine_state.get('open_positions', {})
        proofs['internal_state'] = coin in open_positions
        if coin not in open_positions:
            issues.append(f"Coin {coin} not tracked in internal state")
        else:
            proofs['state_data'] = open_positions[coin]
    
    # Cross-verify data consistency
    if all([proofs.get('exchange_fill'), proofs.get('log_event'), proofs.get('internal_state')]):
        # Compare prices
        fill_price = float(proofs.get('fill_data', {}).get('price', 0))
        log_price = proofs.get('log_data', {}).get('price', 0)
        state_price = proofs.get('state_data', {}).get('entry_price', 0)
        
        if fill_price and log_price and state_price:
            # Allow 1% variance for slippage
            max_diff = max(abs(fill_price - log_price), abs(log_price - state_price))
            if max_diff / fill_price > 0.01:
                issues.append(f"Price inconsistency: fill=${fill_price:.5f}, log=${log_price:.5f}, state=${state_price:.5f}")
    
    valid = all([
        proofs.get('exchange_fill', False),
        proofs.get('exchange_position', False),
        proofs.get('log_event', False),
        proofs.get('ledger_entry', False),
        proofs.get('internal_state', False),
    ]) and len(issues) == 0
    
    return {
        'valid': valid,
        'proofs': proofs,
        'issues': issues,
    }

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 validate_trade.py <COIN>")
        print("Example: python3 validate_trade.py SUPER")
        sys.exit(1)
    
    coin = sys.argv[1].upper()
    result = validate_trade(coin)
    
    print(f"\n{'='*70}")
    print(f"  TRADE VALIDATION: {coin}")
    print(f"{'='*70}\n")
    
    print("PROOFS:")
    for i, (proof_name, passed) in enumerate(result['proofs'].items(), 1):
        if isinstance(passed, bool):
            status = "✅ PASS" if passed else "❌ FAIL"
            print(f"  {i}. {proof_name:20} {status}")
    
    if result['issues']:
        print(f"\nISSUES FOUND ({len(result['issues'])}):")
        for issue in result['issues']:
            print(f"  - {issue}")
    
    print(f"\nVALIDATION RESULT: {'✅ VALID' if result['valid'] else '❌ INVALID'}")
    print(f"{'='*70}\n")
    
    sys.exit(0 if result['valid'] else 1)
