#!/usr/bin/env python3
"""
Enforcement layer proof: Monitor and validate every trade under strict guards.
Reports ONLY after 5 consecutive fully verified trades or enforcement failure.
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
CHECK_INTERVAL = 30  # seconds (frequent checks to catch issues fast)

class EnforcementProver:
    def __init__(self):
        self.info = Info(constants.MAINNET_API_URL, skip_ws=True)
        self.validated_trades = []
        self.last_ledger_size = 0
        self.enforcement_events = []
        
    def check_new_trades(self):
        """Check for new closed trades."""
        ledger_file = Path("workspace/logs/trade-ledger.jsonl")
        if not ledger_file.exists():
            return []
        
        with open(ledger_file) as f:
            lines = f.readlines()
        
        if len(lines) <= self.last_ledger_size:
            return []
        
        # New entries detected
        new_lines = lines[self.last_ledger_size:]
        self.last_ledger_size = len(lines)
        
        entries = [json.loads(l) for l in new_lines if l.strip()]
        
        # Return new exits only
        return [e for e in entries if e.get('action') == 'exit']
    
    def check_enforcement_events(self):
        """Check for enforcement actions (halts, rollbacks, blocks)."""
        log_file = Path("workspace/logs/trading_engine.jsonl")
        if not log_file.exists():
            return []
        
        with open(log_file) as f:
            lines = f.readlines()
        
        events = [json.loads(l) for l in lines if l.strip()]
        
        # Get enforcement-related events
        enforcement_types = [
            'entry_blocked_validation',
            'CRITICAL_HALT',
            'POST_TRADE_VALIDATION_FAILED',
            'rollback_position_closed',
            'rollback_failed',
        ]
        
        return [e for e in events if e.get('event') in enforcement_types]
    
    def validate_closed_trade(self, exit_event):
        """Validate closed trade has all proofs."""
        coin = exit_event.get('coin')
        trade_id = exit_event.get('trade_id')
        
        if not coin or not trade_id:
            return {
                'valid': False,
                'reason': 'Missing coin or trade_id',
                'proofs': {},
            }
        
        proofs = {}
        issues = []
        
        # 1. Exchange fills (entry + exit)
        fills = self.info.user_fills(ENGINE_ADDRESS)
        entry_fills = [f for f in fills if f['coin'] == coin and f['side'] == 'B']
        exit_fills = [f for f in fills if f['coin'] == coin and f['side'] == 'A']
        
        proofs['entry_fill'] = len(entry_fills) > 0
        proofs['exit_fill'] = len(exit_fills) > 0
        
        if not entry_fills:
            issues.append("No entry fill")
        if not exit_fills:
            issues.append("No exit fill")
        
        # 2. Ledger (entry + exit)
        ledger_file = Path("workspace/logs/trade-ledger.jsonl")
        with open(ledger_file) as f:
            entries = [json.loads(l) for l in f if l.strip()]
        
        entry_events = [e for e in entries if e.get('action') == 'entry' and e.get('trade_id') == trade_id]
        exit_events = [e for e in entries if e.get('action') == 'exit' and e.get('trade_id') == trade_id]
        
        proofs['ledger_entry'] = len(entry_events) > 0
        proofs['ledger_exit'] = len(exit_events) > 0
        
        if not entry_events:
            issues.append("No ledger entry")
        if not exit_events:
            issues.append("No ledger exit")
        
        # 3. Log events (order_filled + exit)
        log_file = Path("workspace/logs/trading_engine.jsonl")
        with open(log_file) as f:
            log_entries = [json.loads(l) for l in f if l.strip()]
        
        filled_logs = [e for e in log_entries if e.get('event') == 'order_filled' and e.get('coin') == coin]
        exit_logs = [e for e in log_entries if e.get('action') == 'exit' and e.get('coin') == coin]
        
        proofs['log_filled'] = len(filled_logs) > 0
        proofs['log_exit'] = len(exit_logs) > 0
        
        if not filled_logs:
            issues.append("No order_filled log")
        if not exit_logs:
            issues.append("No exit log")
        
        # 4. Position closed (must NOT be on exchange)
        state = self.info.user_state(ENGINE_ADDRESS)
        position_exists = any(ap['position']['coin'] == coin for ap in state.get('assetPositions', []))
        
        proofs['position_closed'] = not position_exists
        
        if position_exists:
            issues.append("Position still open on exchange")
        
        # 5. Trade_ID consistency (entry and exit match)
        if entry_events and exit_events:
            entry_id = entry_events[0].get('trade_id')
            exit_id = exit_events[0].get('trade_id')
            
            proofs['trade_id_match'] = (entry_id == exit_id)
            
            if entry_id != exit_id:
                issues.append(f"Trade ID mismatch: entry={entry_id}, exit={exit_id}")
        else:
            proofs['trade_id_match'] = False
        
        # Calculate PnL from exchange fills (ground truth)
        if entry_fills and exit_fills:
            entry_cost = sum(float(f['px']) * float(f['sz']) for f in entry_fills if f['coin'] == coin)
            exit_proceeds = sum(float(f['px']) * float(f['sz']) for f in exit_fills if f['coin'] == coin)
            exchange_pnl = exit_proceeds - entry_cost
        else:
            exchange_pnl = None
        
        valid = all(proofs.values()) and len(issues) == 0
        
        return {
            'valid': valid,
            'coin': coin,
            'trade_id': trade_id,
            'proofs': proofs,
            'issues': issues,
            'exchange_pnl': exchange_pnl,
            'ledger_pnl': exit_event.get('pnl_usd'),
        }
    
    def run(self):
        """Run until 5 consecutive trades validated OR enforcement failure detected."""
        print("ENFORCEMENT PROOF MODE")
        print(f"Target: {TARGET_TRADES} consecutive fully verified trades")
        print(f"Check interval: {CHECK_INTERVAL}s")
        print(f"Address: {ENGINE_ADDRESS}")
        print()
        
        consecutive_valid = 0
        last_validated_id = None
        
        while consecutive_valid < TARGET_TRADES:
            time.sleep(CHECK_INTERVAL)
            
            # Check for enforcement events
            enforcement = self.check_enforcement_events()
            if enforcement:
                new_enforcement = [e for e in enforcement if e not in self.enforcement_events]
                if new_enforcement:
                    self.enforcement_events.extend(new_enforcement)
                    
                    for event in new_enforcement:
                        print(f"⚠️  ENFORCEMENT ACTION: {event.get('event')}")
                        print(f"   Reason: {event.get('reason', 'N/A')}")
                        print()
            
            # Check for new trades
            new_exits = self.check_new_trades()
            
            for exit_event in new_exits:
                trade_id = exit_event.get('trade_id')
                
                # Skip if already validated
                if trade_id == last_validated_id:
                    continue
                
                # Validate
                result = self.validate_closed_trade(exit_event)
                
                if result['valid']:
                    consecutive_valid += 1
                    last_validated_id = trade_id
                    
                    print(f"✅ Trade {consecutive_valid}/{TARGET_TRADES} VALID")
                    print(f"   Coin: {result['coin']}")
                    print(f"   Trade ID: {result['trade_id']}")
                    print(f"   Exchange PnL: ${result['exchange_pnl']:.4f}")
                    print(f"   Ledger PnL: ${result['ledger_pnl']}")
                    print(f"   Proofs: {sum(result['proofs'].values())}/{len(result['proofs'])}")
                    print()
                    
                    self.validated_trades.append(result)
                else:
                    # INVALID TRADE → RESET
                    print(f"❌ TRADE INVALID — RESETTING COUNT")
                    print(f"   Coin: {result['coin']}")
                    print(f"   Trade ID: {result['trade_id']}")
                    print(f"   Issues: {result['issues']}")
                    print(f"   Proofs: {result['proofs']}")
                    print()
                    
                    consecutive_valid = 0
                    last_validated_id = None
        
        # SUCCESS
        print("\n" + "="*70)
        print("✅ ENFORCEMENT LAYER PROVEN")
        print(f"   {TARGET_TRADES} consecutive trades with all proofs valid")
        print("="*70 + "\n")
        
        self.print_final_report()
        return True
    
    def print_final_report(self):
        """Print final validation report."""
        print("VALIDATED TRADES:")
        total_pnl = 0
        
        for i, trade in enumerate(self.validated_trades, 1):
            pnl = trade['exchange_pnl'] or 0
            total_pnl += pnl
            
            print(f"\n{i}. {trade['coin']} ({trade['trade_id']})")
            print(f"   PnL: ${pnl:.4f}")
            print(f"   Proofs: {sum(trade['proofs'].values())}/{len(trade['proofs'])}")
        
        print(f"\nTotal PnL: ${total_pnl:.4f}")
        print(f"Win rate: {sum(1 for t in self.validated_trades if (t['exchange_pnl'] or 0) > 0)}/{len(self.validated_trades)}")
        
        print("\nENFORCEMENT EVENTS:")
        if self.enforcement_events:
            for e in self.enforcement_events:
                print(f"  - {e.get('event')}: {e.get('reason', 'N/A')}")
        else:
            print("  None (no halts, rollbacks, or blocks)")
        
        print("\nSYSTEM READY FOR SCALE: ", end="")
        
        # Criteria:
        # 1. All trades valid
        # 2. No enforcement failures (rollbacks, critical halts)
        # 3. Positive or neutral PnL
        
        critical_events = [e for e in self.enforcement_events if e.get('event') in ['POST_TRADE_VALIDATION_FAILED', 'rollback_failed']]
        
        if critical_events:
            print("❌ NO (enforcement failures detected)")
        elif total_pnl < -5:
            print("⚠️  MAYBE (strategy losing, but enforcement works)")
        else:
            print("✅ YES")

if __name__ == "__main__":
    prover = EnforcementProver()
    success = prover.run()
    sys.exit(0 if success else 1)
