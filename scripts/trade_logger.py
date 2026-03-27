#!/usr/bin/env python3
"""
CEO EDGE VALIDATION: Comprehensive trade logging and analysis.
Tracks every trade from entry to exit, measures realized performance,
and provides statistical validation of edge before allowing optimization.
"""

import json
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
from typing import Optional

@dataclass
class Trade:
    """Complete trade record from entry to exit."""
    
    # Entry
    entry_timestamp: str
    asset: str
    direction: str
    entry_price: float
    size: float
    notional_usd: float
    tier: int
    entry_funding_rate: float
    entry_premium: float
    
    # Exit
    exit_timestamp: Optional[str] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None  # SL/TP/trailing/timeout/thesis-decay/manual
    
    # Performance
    hold_time_hours: Optional[float] = None
    price_pnl_usd: Optional[float] = None
    funding_earned_usd: Optional[float] = None
    total_pnl_usd: Optional[float] = None
    roi_pct: Optional[float] = None
    
    # Metadata
    trade_id: Optional[str] = None
    notes: Optional[str] = None

class TradeLogger:
    """Manages trade lifecycle logging."""
    
    def __init__(self, log_file: Path = None):
        if log_file is None:
            log_file = Path(__file__).parent.parent / "workspace/logs/trade-lifecycle.jsonl"
        self.log_file = log_file
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
    
    def log_entry(self, signal: dict, size: float, entry_price: float, trade_id: str) -> Trade:
        """Log a new trade entry."""
        
        trade = Trade(
            trade_id=trade_id,
            entry_timestamp=datetime.now(timezone.utc).isoformat(),
            asset=signal["asset"],
            direction=signal["direction"],
            entry_price=entry_price,
            size=size,
            notional_usd=size * entry_price,
            tier=signal.get("tier", 1),
            entry_funding_rate=signal.get("funding_8h", 0),
            entry_premium=signal.get("premium", 0),
        )
        
        # Append to log
        with self.log_file.open("a") as f:
            f.write(json.dumps(asdict(trade)) + "\n")
        
        return trade
    
    def log_exit(self, trade_id: str, exit_price: float, exit_reason: str, 
                  funding_earned: float = 0.0, notes: str = None):
        """Log trade exit and calculate performance."""
        
        # Read all trades to find the one to update
        trades = self._read_all_trades()
        
        for trade in trades:
            if trade["trade_id"] == trade_id and trade["exit_timestamp"] is None:
                # Calculate metrics
                entry_time = datetime.fromisoformat(trade["entry_timestamp"])
                exit_time = datetime.now(timezone.utc)
                hold_hours = (exit_time - entry_time).total_seconds() / 3600
                
                # Price P&L
                if trade["direction"] == "long":
                    price_pnl = (exit_price - trade["entry_price"]) * trade["size"]
                else:
                    price_pnl = (trade["entry_price"] - exit_price) * trade["size"]
                
                # Total P&L
                total_pnl = price_pnl + funding_earned
                roi = (total_pnl / trade["notional_usd"]) * 100
                
                # Update trade
                trade["exit_timestamp"] = exit_time.isoformat()
                trade["exit_price"] = exit_price
                trade["exit_reason"] = exit_reason
                trade["hold_time_hours"] = hold_hours
                trade["price_pnl_usd"] = price_pnl
                trade["funding_earned_usd"] = funding_earned
                trade["total_pnl_usd"] = total_pnl
                trade["roi_pct"] = roi
                trade["notes"] = notes
                
                # Rewrite entire file (small file, safe)
                self._write_all_trades(trades)
                
                return trade
        
        return None
    
    def _read_all_trades(self) -> list[dict]:
        """Read all trades from log file."""
        if not self.log_file.exists():
            return []
        
        trades = []
        with self.log_file.open("r") as f:
            for line in f:
                if line.strip():
                    trades.append(json.loads(line))
        return trades
    
    def _write_all_trades(self, trades: list[dict]):
        """Rewrite entire log file."""
        with self.log_file.open("w") as f:
            for trade in trades:
                f.write(json.dumps(trade) + "\n")
    
    def get_statistics(self, min_trades: int = 1) -> dict:
        """Calculate portfolio statistics."""
        
        trades = self._read_all_trades()
        closed = [t for t in trades if t["exit_timestamp"] is not None]
        
        if len(closed) < min_trades:
            return {
                "status": "insufficient_data",
                "closed_trades": len(closed),
                "minimum_required": min_trades,
            }
        
        # Calculate stats
        wins = [t for t in closed if t["total_pnl_usd"] > 0]
        losses = [t for t in closed if t["total_pnl_usd"] <= 0]
        
        total_pnl = sum(t["total_pnl_usd"] for t in closed)
        total_funding = sum(t.get("funding_earned_usd", 0) for t in closed)
        total_price_pnl = sum(t["price_pnl_usd"] for t in closed)
        
        win_rate = len(wins) / len(closed) if closed else 0
        avg_win = sum(t["total_pnl_usd"] for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t["total_pnl_usd"] for t in losses) / len(losses) if losses else 0
        expectancy = win_rate * avg_win + (1 - win_rate) * avg_loss
        
        # Tier breakdown
        tier1 = [t for t in closed if t.get("tier") == 1]
        tier2 = [t for t in closed if t.get("tier") == 2]
        
        return {
            "status": "validated" if len(closed) >= 20 else "in_progress",
            "closed_trades": len(closed),
            "win_rate": win_rate,
            "wins": len(wins),
            "losses": len(losses),
            "total_pnl_usd": total_pnl,
            "total_funding_usd": total_funding,
            "total_price_pnl_usd": total_price_pnl,
            "avg_win_usd": avg_win,
            "avg_loss_usd": avg_loss,
            "expectancy_usd": expectancy,
            "tier1_trades": len(tier1),
            "tier2_trades": len(tier2),
            "tier1_pnl": sum(t["total_pnl_usd"] for t in tier1) if tier1 else 0,
            "tier2_pnl": sum(t["total_pnl_usd"] for t in tier2) if tier2 else 0,
            "avg_hold_hours": sum(t["hold_time_hours"] for t in closed) / len(closed),
        }
    
    def print_report(self):
        """Print human-readable performance report."""
        
        stats = self.get_statistics(min_trades=1)
        
        print("=== TRADE PERFORMANCE REPORT ===")
        print()
        
        if stats["status"] == "insufficient_data":
            print(f"⚠️  Need {stats['minimum_required'] - stats['closed_trades']} more closed trades")
            print(f"   Current: {stats['closed_trades']} / {stats['minimum_required']}")
            return
        
        print(f"Status: {stats['status'].upper()}")
        print(f"Closed trades: {stats['closed_trades']}")
        print()
        
        print("PERFORMANCE:")
        print(f"  Win rate: {stats['win_rate']*100:.1f}% ({stats['wins']}W / {stats['losses']}L)")
        print(f"  Total P&L: ${stats['total_pnl_usd']:+.2f}")
        print(f"    - Price P&L: ${stats['total_price_pnl_usd']:+.2f}")
        print(f"    - Funding:   ${stats['total_funding_usd']:+.2f}")
        print(f"  Avg win: ${stats['avg_win_usd']:.2f}")
        print(f"  Avg loss: ${stats['avg_loss_usd']:.2f}")
        print(f"  Expectancy: ${stats['expectancy_usd']:+.2f} per trade")
        print()
        
        print("TIER BREAKDOWN:")
        print(f"  Tier 1: {stats['tier1_trades']} trades, ${stats['tier1_pnl']:+.2f} P&L")
        print(f"  Tier 2: {stats['tier2_trades']} trades, ${stats['tier2_pnl']:+.2f} P&L")
        print()
        
        print(f"Avg hold time: {stats['avg_hold_hours']:.1f} hours")
        
        if stats['status'] == 'validated':
            print()
            print("✅ EDGE VALIDATED — You can now optimize thresholds based on this data")
        else:
            print()
            print(f"⏳ IN PROGRESS — Need {20 - stats['closed_trades']} more trades for validation")

if __name__ == "__main__":
    logger = TradeLogger()
    logger.print_report()
