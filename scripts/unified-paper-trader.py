#!/usr/bin/env python3
"""
Unified Paper Trading Engine
Handles both Hyperliquid and Polymarket signals
Architecture: signal → validation → execution → tracking
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List

# Add scripts to path for imports
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.runtime import WORKSPACE_ROOT as WORKSPACE, LOGS_DIR, DATA_DIR
sys.path.insert(0, str(REPO_ROOT / "scripts"))

# Import PolymarketExecutor directly
import importlib.util
spec = importlib.util.spec_from_file_location("polymarket_executor", REPO_ROOT / "scripts" / "polymarket-executor.py")
pm_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pm_module)
PolymarketExecutor = pm_module.PolymarketExecutor

SIGNALS_FILE = LOGS_DIR / "phase1-signals.jsonl"
PAPER_TRADES_FILE = LOGS_DIR / "phase1-paper-trades.jsonl"
PERFORMANCE_FILE = LOGS_DIR / "phase1-performance.json"

# Trading parameters
MAX_OPEN_POSITIONS = 5
MIN_EV_SCORE = 40


class UnifiedPaperTrader:
    """Unified paper trading across Hyperliquid and Polymarket"""
    
    def __init__(self):
        self.polymarket = PolymarketExecutor(paper_trading=True)
        self.open_positions = self.load_open_positions()
    
    def load_open_positions(self) -> list:
        """Load all open positions from log"""
        if not PAPER_TRADES_FILE.exists():
            return []
        
        open_pos = []
        with open(PAPER_TRADES_FILE) as f:
            for line in f:
                if line.strip():
                    trade = json.loads(line)
                    if trade['status'] == 'OPEN':
                        open_pos.append(trade)
        
        return open_pos
    
    def load_latest_signals(self, limit: int = 10) -> list:
        """Load latest signals from log"""
        if not SIGNALS_FILE.exists():
            return []
        
        signals = []
        with open(SIGNALS_FILE) as f:
            for line in f:
                if line.strip():
                    signals.append(json.loads(line))
        
        # Return last N signals
        return signals[-limit:]
    
    def execute_signal(self, signal: Dict) -> Dict:
        """Execute signal on appropriate exchange"""
        
        source = signal.get('source', '').lower()
        
        if 'polymarket' in source:
            return self.execute_polymarket_signal(signal)
        else:
            # Default to Hyperliquid (existing paper trader handles this)
            return {'status': 'SKIPPED', 'reason': 'Hyperliquid handled by phase1-paper-trader.py'}
    
    def execute_polymarket_signal(self, signal: Dict) -> Dict:
        """Execute Polymarket signal"""
        
        # Validate signal
        valid, reason = self.polymarket.validate_signal(signal)
        if not valid:
            return {'status': 'REJECTED', 'reason': reason}
        
        # Check EV score
        if signal.get('ev_score', 0) < MIN_EV_SCORE:
            return {'status': 'REJECTED', 'reason': f"EV score {signal.get('ev_score')} < {MIN_EV_SCORE}"}
        
        # Check max open positions
        if len(self.open_positions) >= MAX_OPEN_POSITIONS:
            return {'status': 'REJECTED', 'reason': f"Max {MAX_OPEN_POSITIONS} positions already open"}
        
        # Execute paper trade
        result = self.polymarket.paper_buy(signal)
        
        if result['status'] == 'SUCCESS':
            self.open_positions.append(result['trade'])
        
        return result
    
    def update_positions(self):
        """Update all open Polymarket positions"""
        
        updated = []
        
        for pos in list(self.open_positions):
            if pos.get('type') != 'PAPER' or 'market_id' not in pos.get('signal', {}):
                continue
            
            # Check if should close (simplified: close after 24h or 10% profit)
            entry_time = datetime.fromisoformat(pos['entry_time'].replace('Z', '+00:00'))
            age_hours = (datetime.now(timezone.utc) - entry_time).total_seconds() / 3600
            
            # Get current market data
            market = self.polymarket.get_market_data(pos['signal']['market_id'])
            if not market:
                continue
            
            current_price = self.polymarket.get_current_price(market, pos['side'])
            if not current_price:
                continue
            
            # Calculate current P&L
            current_pnl_pct = ((current_price - pos['entry_price']) / pos['entry_price']) * 100
            
            # Close conditions
            should_close = False
            close_reason = None
            
            if age_hours > 24:
                should_close = True
                close_reason = "Time limit (24h)"
            elif current_pnl_pct < -10:
                should_close = True
                close_reason = "Stop loss (-10%)"
            elif current_pnl_pct > 10:
                should_close = True
                close_reason = "Take profit (+10%)"
            
            if should_close:
                result = self.polymarket.paper_close(pos['trade_id'], close_reason)
                if result['status'] == 'SUCCESS':
                    self.open_positions.remove(pos)
                    updated.append(result['trade'])
        
        return updated
    
    def run_cycle(self):
        """Run one paper trading cycle"""
        
        print("=" * 80)
        print("UNIFIED PAPER TRADER — Hyperliquid + Polymarket")
        print(f"Cycle Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S EDT')}")
        print("=" * 80)
        print()
        
        # Update open positions
        print("1. Updating open positions...")
        closed = self.update_positions()
        print(f"   Closed: {len(closed)} positions")
        print()
        
        # Load latest signals
        print("2. Loading latest signals...")
        signals = self.load_latest_signals(limit=10)
        polymarket_signals = [s for s in signals if 'polymarket' in s.get('source', '').lower()]
        print(f"   Found: {len(polymarket_signals)} Polymarket signals")
        print()
        
        # Execute new signals
        print("3. Executing new signals...")
        executed = 0
        
        for signal in polymarket_signals:
            result = self.execute_signal(signal)
            
            if result['status'] == 'SUCCESS':
                executed += 1
                print(f"   ✅ OPENED: {signal.get('market_question', 'Unknown market')}")
            elif result['status'] == 'REJECTED':
                print(f"   ⚠️  REJECTED: {result['reason']}")
        
        print(f"   Executed: {executed} new positions")
        print()
        
        # Status summary
        pm_status = self.polymarket.get_status()
        print("=" * 80)
        print("STATUS:")
        print(f"  Polymarket Balance: ${pm_status['paper_balance']:.2f}")
        print(f"  Open Positions: {pm_status['open_positions']}")
        print(f"  Closed Positions: {pm_status['closed_positions']}")
        print("=" * 80)


def main():
    trader = UnifiedPaperTrader()
    trader.run_cycle()


if __name__ == "__main__":
    main()
