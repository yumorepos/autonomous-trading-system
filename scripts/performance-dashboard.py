#!/usr/bin/env python3
"""
Performance Dashboard (CLI)
Shows: total trades, win rate, avg P&L, per-exchange stats, open vs closed
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.runtime import WORKSPACE_ROOT as WORKSPACE, LOGS_DIR, DATA_DIR
from models.trade_schema import normalize_trade_record
from utils.json_utils import safe_read_jsonl

class PerformanceDashboard:
    """CLI performance dashboard"""
    
    def __init__(self):
        self.hl_trades = self.load_trades(LOGS_DIR / "phase1-paper-trades.jsonl")
        self.pm_trades = self.load_trades(LOGS_DIR / "polymarket-trades.jsonl")
    
    def load_trades(self, file_path: Path) -> List[Dict]:
        """Load trades from JSONL"""
        return [normalize_trade_record(record) for record in safe_read_jsonl(file_path)]
    
    def calculate_stats(self, trades: List[Dict]) -> Dict:
        """Calculate performance stats"""
        if not trades:
            return {
                'total': 0,
                'open': 0,
                'closed': 0,
                'win_rate': 0,
                'total_pnl': 0,
                'avg_pnl': 0,
                'winners': 0,
                'losers': 0
            }
        
        closed_trades = [t for t in trades if t.get('status') == 'CLOSED']
        open_trades = [t for t in trades if t.get('status') == 'OPEN']
        
        winners = [t for t in closed_trades if (t.get('realized_pnl_usd') or 0) > 0]
        losers = [t for t in closed_trades if (t.get('realized_pnl_usd') or 0) < 0]
        
        total_pnl = sum(t.get('realized_pnl_usd', 0) or 0 for t in closed_trades)
        avg_pnl = total_pnl / len(closed_trades) if closed_trades else 0
        win_rate = (len(winners) / len(closed_trades) * 100) if closed_trades else 0
        
        return {
            'total': len(trades),
            'open': len(open_trades),
            'closed': len(closed_trades),
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'avg_pnl': avg_pnl,
            'winners': len(winners),
            'losers': len(losers)
        }
    
    def display(self):
        """Display performance dashboard"""
        # Calculate combined stats
        all_trades = self.hl_trades + self.pm_trades
        combined_stats = self.calculate_stats(all_trades)
        
        hl_stats = self.calculate_stats(self.hl_trades)
        pm_stats = self.calculate_stats(self.pm_trades)
        
        print("="*80)
        print("PERFORMANCE DASHBOARD")
        print(f"Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S EDT')}")
        print("="*80)
        print()
        
        # Overall stats
        print("📊 OVERALL PERFORMANCE")
        print("-" * 80)
        print(f"Total Trades:     {combined_stats['total']}")
        print(f"Open Positions:   {combined_stats['open']}")
        print(f"Closed Trades:    {combined_stats['closed']}")
        print(f"Win Rate:         {combined_stats['win_rate']:.1f}%")
        print(f"Total P&L:        ${combined_stats['total_pnl']:+.2f}")
        print(f"Avg P&L:          ${combined_stats['avg_pnl']:+.2f}")
        print(f"Winners:          {combined_stats['winners']}")
        print(f"Losers:           {combined_stats['losers']}")
        print()
        
        # Per-exchange stats
        print("🏪 PER-EXCHANGE BREAKDOWN")
        print("-" * 80)
        
        print()
        print("Hyperliquid (Real Paper Trading)")
        print(f"  Total:    {hl_stats['total']}")
        print(f"  Open:     {hl_stats['open']}")
        print(f"  Closed:   {hl_stats['closed']}")
        print(f"  Win Rate: {hl_stats['win_rate']:.1f}%")
        print(f"  P&L:      ${hl_stats['total_pnl']:+.2f}")
        
        print()
        print("Polymarket (Real Paper Trading)")
        print(f"  Total:    {pm_stats['total']}")
        print(f"  Open:     {pm_stats['open']}")
        print(f"  Closed:   {pm_stats['closed']}")
        print(f"  Win Rate: {pm_stats['win_rate']:.1f}%")
        print(f"  P&L:      ${pm_stats['total_pnl']:+.2f}")
        
        print()
        print("="*80)
        
        # Open positions detail
        if combined_stats['open'] > 0:
            print()
            print("📈 OPEN POSITIONS")
            print("-" * 80)
            
            open_trades = [t for t in all_trades if t.get('status') == 'OPEN']
            for trade in open_trades[:10]:  # Show max 10
                exchange = trade.get('raw', {}).get('source', trade.get('raw', {}).get('exchange', 'Unknown'))
                asset = trade.get('symbol', 'Unknown')
                entry = trade.get('entry_price', 0) or 0
                print(f"  [{exchange}] {asset} @ ${entry:.2f}")
            
            if len(open_trades) > 10:
                print(f"  ... and {len(open_trades) - 10} more")


def main():
    """Show performance dashboard"""
    dashboard = PerformanceDashboard()
    dashboard.display()


if __name__ == "__main__":
    main()
