#!/usr/bin/env python3
"""
Performance Dashboard (CLI)
Shows: total trades, win rate, avg P&L, per-exchange stats, open vs closed
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List

WORKSPACE = Path.home() / ".openclaw" / "workspace"

class PerformanceDashboard:
    """CLI performance dashboard"""
    
    def __init__(self):
        self.hl_trades = self.load_trades(WORKSPACE / "logs" / "phase1-paper-trades.jsonl")
        self.pm_trades = self.load_trades(WORKSPACE / "logs" / "polymarket-trades.jsonl")
        self.test_trades = self.load_trades(WORKSPACE / "logs" / "test-lifecycle-trades.jsonl")
    
    def load_trades(self, file_path: Path) -> List[Dict]:
        """Load trades from JSONL"""
        if not file_path.exists():
            return []
        
        trades = []
        with open(file_path) as f:
            for line in f:
                if line.strip():
                    trades.append(json.loads(line))
        return trades
    
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
        
        winners = [t for t in closed_trades if t.get('pnl', 0) > 0]
        losers = [t for t in closed_trades if t.get('pnl', 0) < 0]
        
        total_pnl = sum(t.get('pnl', 0) for t in closed_trades)
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
        all_trades = self.hl_trades + self.pm_trades + self.test_trades
        combined_stats = self.calculate_stats(all_trades)
        
        hl_stats = self.calculate_stats(self.hl_trades)
        pm_stats = self.calculate_stats(self.pm_trades)
        test_stats = self.calculate_stats(self.test_trades)
        
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
        print("Test Trades (Simulated)")
        print(f"  Total:    {test_stats['total']}")
        print(f"  Open:     {test_stats['open']}")
        print(f"  Closed:   {test_stats['closed']}")
        print(f"  Win Rate: {test_stats['win_rate']:.1f}%")
        print(f"  P&L:      ${test_stats['total_pnl']:+.2f}")
        
        print()
        print("="*80)
        
        # Open positions detail
        if combined_stats['open'] > 0:
            print()
            print("📈 OPEN POSITIONS")
            print("-" * 80)
            
            open_trades = [t for t in all_trades if t.get('status') == 'OPEN']
            for trade in open_trades[:10]:  # Show max 10
                exchange = trade.get('source', trade.get('exchange', 'Unknown'))
                asset = trade.get('asset', 'Unknown')
                entry = trade.get('entry_price', trade.get('price', 0))
                print(f"  [{exchange}] {asset} @ ${entry:.2f}")
            
            if len(open_trades) > 10:
                print(f"  ... and {len(open_trades) - 10} more")


def main():
    """Show performance dashboard"""
    dashboard = PerformanceDashboard()
    dashboard.display()


if __name__ == "__main__":
    main()
