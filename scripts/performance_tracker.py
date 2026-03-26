#!/usr/bin/env python3
"""
Performance Tracker — Measures trading system performance.

Metrics:
- trades count
- open positions count
- closed trades count
- win rate
- realized PnL
- expectancy per trade
- drawdown
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sys
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.runtime import LOGS_DIR
from models.position_state import get_open_positions
from models.trade_schema import normalize_trade_record, is_trade_closed

PERFORMANCE_FILE = LOGS_DIR / "phase1-performance.json"
TRADES_FILE = LOGS_DIR / "phase1-paper-trades.jsonl"
POSITION_STATE_FILE = LOGS_DIR / "position-state.json"

class PerformanceTracker:
    """Tracks trading performance metrics."""
    
    def load_trades(self) -> list[dict[str, Any]]:
        """Load all trades from trades file."""
        trades = []
        if TRADES_FILE.exists():
            with open(TRADES_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        try:
                            trade = json.loads(line)
                            trades.append(trade)
                        except json.JSONDecodeError:
                            continue
        return trades
    
    def calculate_metrics(self, trades: list[dict[str, Any]]) -> dict[str, Any]:
        """Calculate performance metrics from trades."""
        normalized_trades = [normalize_trade_record(trade) for trade in trades]
        closed_trades = [t for t in normalized_trades if is_trade_closed(t)]
        total_trades = len(normalized_trades)
        open_positions = list(get_open_positions(POSITION_STATE_FILE))
        open_positions_count = len(open_positions)
        
        # Basic metrics
        winners = [t for t in closed_trades if (t.get('realized_pnl_usd') or 0) > 0]
        losers = [t for t in closed_trades if (t.get('realized_pnl_usd') or 0) <= 0]
        total_pnl = sum((t.get('realized_pnl_usd') or 0) for t in closed_trades)
        
        # Exchange breakdown
        exchange_breakdown: dict[str, dict[str, float | int]] = {}
        for trade in closed_trades:
            exchange = trade.get('exchange', 'unknown')
            breakdown = exchange_breakdown.setdefault(exchange, {'trades': 0, 'pnl': 0.0, 'winners': 0})
            breakdown['trades'] += 1
            breakdown['pnl'] += (trade.get('realized_pnl_usd') or 0)
            if (trade.get('realized_pnl_usd') or 0) > 0:
                breakdown['winners'] += 1
        
        # Expectancy calculation
        expectancy = total_pnl / len(closed_trades) if closed_trades else 0
        
        # Drawdown calculation
        running_pnl = 0
        peak = 0
        drawdown = 0
        for trade in sorted(closed_trades, key=lambda t: t.get('timestamp', '')):
            pnl = trade.get('realized_pnl_usd') or 0
            running_pnl += pnl
            if running_pnl > peak:
                peak = running_pnl
            else:
                current_drawdown = peak - running_pnl
                if current_drawdown > drawdown:
                    drawdown = current_drawdown
        
        return {
            'total_trades': total_trades,
            'trade_count': total_trades,
            'open_positions': open_positions_count,
            'closed_trades': len(closed_trades),
            'winners': len(winners),
            'losers': len(losers),
            'win_rate': len(winners) / len(closed_trades) * 100 if closed_trades else 0,
            'total_pnl_usd': total_pnl,
            'expectancy_usd': expectancy,
            'max_drawdown_usd': drawdown,
            'exchange_breakdown': exchange_breakdown,
            'last_updated': datetime.now(timezone.utc).isoformat(),
        }
    
    def update_performance(self) -> dict[str, Any]:
        """Update performance metrics."""
        trades = self.load_trades()
        metrics = self.calculate_metrics(trades)
        PERFORMANCE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(PERFORMANCE_FILE, 'w', encoding='utf-8') as f:
            json.dump(metrics, f, indent=2)
        return metrics
    
    def display_performance(self) -> None:
        """Display current performance metrics."""
        metrics = self.update_performance()
        print("=== Trading Performance Metrics ===")
        print(f"Total trades: {metrics['trade_count']}")
        print(f"Open positions: {metrics['open_positions']}")
        print(f"Closed trades: {metrics['closed_trades']}")
        print(f"Winners: {metrics['winners']}")
        print(f"Losers: {metrics['losers']}")
        print(f"Win rate: {metrics['win_rate']:.1f}%")
        print(f"Total PnL: ${metrics['total_pnl_usd']:+.2f}")
        print(f"Expectancy per trade: ${metrics['expectancy_usd']:.2f}")
        print(f"Max drawdown: ${metrics['max_drawdown_usd']:.2f}")
        print("\nExchange breakdown:")
        if metrics['exchange_breakdown']:
            for exchange, data in metrics['exchange_breakdown'].items():
                print(f"  {exchange}: {data['trades']} trades, ${data['pnl']:.2f} PnL, {data['winners']} winners")
        else:
            print("  (no closed trades yet)")
        print(f"\nLast updated: {metrics['last_updated']}")

if __name__ == "__main__":
    tracker = PerformanceTracker()
    tracker.display_performance()
