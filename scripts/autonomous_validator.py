#!/usr/bin/env python3
"""
Autonomous strict validation monitor: Run until 5 consecutive trades verified.
"""

import json
import time
import sys
from pathlib import Path
from datetime import datetime, timezone
from hyperliquid.info import Info
from hyperliquid.utils import constants

ENGINE_ADDRESS = "0x8743f51c57e90644a0c141eD99064C4e9efFC01c"
TARGET_TRADES = 5
CHECK_INTERVAL = 60  # seconds

class TradeValidator:
    def __init__(self):
        self.info = Info(constants.MAINNET_API_URL, skip_ws=True)
        self.validated_trades = []
        self.last_check_time = 0
        
    def get_closed_trades(self):
        """Get list of closed trades from ledger (exit events)."""
        ledger_file = Path("workspace/logs/trade-ledger.jsonl")
        if not ledger_file.exists():
            return []
        
        with open(ledger_file) as f:
            lines = f.readlines()
        
        entries = [json.loads(l) for l in lines if l.strip()]
        exits = [e for e in entries if e.get('action') == 'exit']
        
        # Return most recent exits
        return sorted(exits, key=lambda x: x.get('timestamp', ''), reverse=True)
    
    def validate_closed_trade(self, exit_event):
        """Validate a closed trade has all proofs for entry AND exit."""
        coin = exit_event.get('coin')
        trade_id = exit_event.get('trade_id')
        
        if not coin or not trade_id:
            return {'valid': False, 'reason': 'Missing coin or trade_id in exit event'}
        
        issues = []
        proofs = {}
        
        # ENTRY PROOFS
        # 1. Exchange fill (entry)
        fills = self.info.user_fills(ENGINE_ADDRESS)
        entry_fills = [f for f in fills if f['coin'] == coin and f['side'] == 'B']  # Buy
        proofs['entry_fill'] = len(entry_fills) > 0
        if not entry_fills:
            issues.append(f"No entry fill for {coin}")
        
        # 2. Ledger entry
        ledger_file = Path("workspace/logs/trade-ledger.jsonl")
        with open(ledger_file) as f:
            entries = [json.loads(l) for l in f if l.strip()]
        
        entry_events = [e for e in entries if e.get('action') == 'entry' and e.get('coin') == coin and e.get('trade_id') == trade_id]
        proofs['entry_ledger'] = len(entry_events) > 0
        if not entry_events:
            issues.append(f"No ledger entry for {coin}/{trade_id}")
        
        # 3. Log event (entry)
        log_file = Path("workspace/logs/trading_engine.jsonl")
        with open(log_file) as f:
            log_entries = [json.loads(l) for l in f if l.strip()]
        
        entry_logs = [e for e in log_entries if e.get('event') == 'order_filled' and e.get('coin') == coin]
        proofs['entry_log'] = len(entry_logs) > 0
        if not entry_logs:
            issues.append(f"No order_filled log for {coin}")
        
        # EXIT PROOFS
        # 4. Exchange fill (exit)
        exit_fills = [f for f in fills if f['coin'] == coin and f['side'] == 'A']  # Ask (sell)
        proofs['exit_fill'] = len(exit_fills) > 0
        if not exit_fills:
            issues.append(f"No exit fill for {coin}")
        
        # 5. Ledger exit (already have this from input)
        proofs['exit_ledger'] = True
        
        # 6. Log event (exit)
        exit_logs = [e for e in log_entries if e.get('action') == 'exit' and e.get('coin') == coin]
        proofs['exit_log'] = len(exit_logs) > 0
        if not exit_logs:
            issues.append(f"No exit log for {coin}")
        
        # 7. Position must be CLOSED on exchange
        state = self.info.user_state(ENGINE_ADDRESS)
        positions = state.get('assetPositions', [])
        position_exists = any(ap['position']['coin'] == coin for ap in positions)
        proofs['position_closed'] = not position_exists
        if position_exists:
            issues.append(f"Position {coin} still open on exchange")
        
        valid = all([
            proofs.get('entry_fill', False),
            proofs.get('entry_ledger', False),
            proofs.get('entry_log', False),
            proofs.get('exit_fill', False),
            proofs.get('exit_ledger', False),
            proofs.get('exit_log', False),
            proofs.get('position_closed', False),
        ]) and len(issues) == 0
        
        return {
            'valid': valid,
            'coin': coin,
            'trade_id': trade_id,
            'proofs': proofs,
            'issues': issues,
            'exit_event': exit_event,
        }
    
    def run(self):
        """Run continuous validation until TARGET_TRADES reached."""
        print(f"Starting autonomous validation (target: {TARGET_TRADES} trades)")
        print(f"Check interval: {CHECK_INTERVAL}s")
        print(f"Address: {ENGINE_ADDRESS}")
        print()
        
        consecutive_valid = 0
        last_validated_id = None
        
        while consecutive_valid < TARGET_TRADES:
            time.sleep(CHECK_INTERVAL)
            
            # Get recent closed trades
            closed_trades = self.get_closed_trades()
            
            if not closed_trades:
                continue
            
            # Check most recent trade
            latest = closed_trades[0]
            latest_id = latest.get('trade_id')
            
            # Skip if already validated
            if latest_id == last_validated_id:
                continue
            
            # Validate
            result = self.validate_closed_trade(latest)
            
            if result['valid']:
                consecutive_valid += 1
                last_validated_id = latest_id
                
                print(f"[{datetime.now(timezone.utc).isoformat()[:19]}] ✅ Trade {consecutive_valid}/{TARGET_TRADES} VALID")
                print(f"  Coin: {result['coin']}")
                print(f"  Trade ID: {result['trade_id']}")
                print(f"  PnL: ${result['exit_event'].get('pnl_usd', 0):.4f}")
                print()
                
                # Save validated trade
                self.validated_trades.append(result)
            else:
                # Reset on invalid trade
                print(f"[{datetime.now(timezone.utc).isoformat()[:19]}] ❌ Trade INVALID - RESETTING COUNT")
                print(f"  Coin: {result['coin']}")
                print(f"  Trade ID: {result['trade_id']}")
                print(f"  Issues: {result['issues']}")
                print()
                
                consecutive_valid = 0
                last_validated_id = None
        
        # Validation complete
        print(f"\n{'='*70}")
        print(f"  STRICT VALIDATION COMPLETE: {TARGET_TRADES} CONSECUTIVE TRADES VERIFIED")
        print(f"{'='*70}\n")
        
        self.print_scoreboard()
        return self.validated_trades
    
    def print_scoreboard(self):
        """Print final scoreboard."""
        print("VALIDATED TRADES:")
        for i, trade in enumerate(self.validated_trades, 1):
            print(f"\n{i}. {trade['coin']} ({trade['trade_id']})")
            print(f"   PnL: ${trade['exit_event'].get('pnl_usd', 0):.4f}")
            print(f"   Proofs: {sum(trade['proofs'].values())}/{len(trade['proofs'])} ✅")
        
        total_pnl = sum(t['exit_event'].get('pnl_usd', 0) for t in self.validated_trades)
        print(f"\nTotal PnL: ${total_pnl:.4f}")
        print(f"System ready for scale: {total_pnl >= 0}")

if __name__ == "__main__":
    validator = TradeValidator()
    validator.run()
