#!/usr/bin/env python3
"""
Phase 1 Paper Trading Engine
Simulates trades based on signals, tracks performance, ranks strategies
"""

import json
import os
import requests
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path.home() / ".openclaw" / "workspace"
PAPER_TRADES_FILE = WORKSPACE / "logs" / "phase1-paper-trades.jsonl"
PERFORMANCE_FILE = WORKSPACE / "logs" / "phase1-performance.json"
SIGNALS_FILE = WORKSPACE / "logs" / "phase1-signals.jsonl"

PAPER_BALANCE = 97.80  # Starting paper balance
MAX_OPEN_POSITIONS = 3
MIN_EV_SCORE = 40  # Only paper trade signals with EV > 40


class PaperTrade:
    def __init__(self, signal, entry_price, position_size):
        self.signal = signal
        self.entry_price = entry_price
        self.position_size = position_size
        self.entry_time = datetime.now(timezone.utc)
        self.exit_price = None
        self.exit_time = None
        self.pnl = 0
        self.status = 'OPEN'
        self.stop_loss_pct = 15 if signal.get('conviction') == 'HIGH' else 10
        
    def check_exit(self, current_price):
        """Check if position should be closed"""
        pnl_pct = ((current_price - self.entry_price) / self.entry_price) * 100
        
        # Stop loss
        if pnl_pct < -self.stop_loss_pct:
            self.close(current_price, 'STOP_LOSS')
            return True
        
        # Take profit (funding normalized or >10% profit)
        if self.signal['signal_type'] == 'funding_arbitrage':
            # Check if funding normalized (for next scan, this is simplified)
            if pnl_pct > 10:
                self.close(current_price, 'TAKE_PROFIT')
                return True
        
        # Time-based exit (7 days max)
        days_open = (datetime.now(timezone.utc) - self.entry_time).days
        if days_open >= 7:
            self.close(current_price, 'TIME_EXIT')
            return True
        
        return False
    
    def close(self, exit_price, reason):
        """Close the position"""
        self.exit_price = exit_price
        self.exit_time = datetime.now(timezone.utc)
        
        # Calculate P&L
        if self.signal.get('direction') == 'LONG':
            pnl_pct = ((exit_price - self.entry_price) / self.entry_price)
        else:  # SHORT
            pnl_pct = ((self.entry_price - exit_price) / self.entry_price)
        
        self.pnl = self.position_size * pnl_pct
        self.status = reason
    
    def to_dict(self):
        return {
            'signal': self.signal,
            'entry_price': self.entry_price,
            'exit_price': self.exit_price,
            'position_size': self.position_size,
            'entry_time': self.entry_time.isoformat(),
            'exit_time': self.exit_time.isoformat() if self.exit_time else None,
            'pnl': round(self.pnl, 2),
            'pnl_pct': round((self.pnl / self.position_size) * 100, 2) if self.position_size > 0 else 0,
            'status': self.status,
            'stop_loss_pct': self.stop_loss_pct
        }


def load_open_positions():
    """Load currently open paper trades"""
    if not PAPER_TRADES_FILE.exists():
        return []
    
    open_positions = []
    with open(PAPER_TRADES_FILE) as f:
        for line in f:
            if line.strip():
                trade = json.loads(line)
                if trade['status'] == 'OPEN':
                    # Reconstruct PaperTrade object
                    pt = PaperTrade(trade['signal'], trade['entry_price'], trade['position_size'])
                    pt.entry_time = datetime.fromisoformat(trade['entry_time'])
                    pt.status = trade['status']
                    open_positions.append(pt)
    
    return open_positions


def load_latest_signals():
    """Load latest signals from signal scanner"""
    if not SIGNALS_FILE.exists():
        return []
    
    signals = []
    with open(SIGNALS_FILE) as f:
        for line in f:
            if line.strip():
                signals.append(json.loads(line))
    
    # Return only signals from last scan (last 5 hours)
    recent_signals = []
    cutoff = datetime.now(timezone.utc).timestamp() - (5 * 3600)
    
    for sig in signals:
        sig_time = datetime.fromisoformat(sig['timestamp']).timestamp()
        if sig_time > cutoff:
            recent_signals.append(sig)
    
    return recent_signals


def get_current_price(asset):
    """Get current price from Hyperliquid"""
    try:
        r = requests.post("https://api.hyperliquid.xyz/info",
                         json={"type": "metaAndAssetCtxs"}, timeout=10)
        data = r.json()
        universe = data[0]['universe']
        contexts = data[1]
        
        for a, ctx in zip(universe, contexts):
            if a['name'] == asset:
                return float(ctx.get('markPx', 0))
        
        return None
    except:
        return None


def update_open_positions(open_positions):
    """Check and update open positions"""
    print("📊 Checking open positions...")
    
    for pos in open_positions:
        asset = pos.signal.get('asset')
        if not asset:
            continue
        
        current_price = get_current_price(asset)
        if not current_price:
            continue
        
        pnl_pct = ((current_price - pos.entry_price) / pos.entry_price) * 100
        print(f"  {asset}: Entry ${pos.entry_price:.4f} → Now ${current_price:.4f} ({pnl_pct:+.1f}%)")
        
        # Check if should exit
        if pos.check_exit(current_price):
            print(f"    ✅ CLOSED: {pos.status} | P&L: ${pos.pnl:+.2f}")
            
            # Log closed trade
            PAPER_TRADES_FILE.parent.mkdir(exist_ok=True)
            with open(PAPER_TRADES_FILE, 'a') as f:
                f.write(json.dumps(pos.to_dict()) + '\n')


def open_new_positions(latest_signals, open_positions, balance):
    """Open new paper trades from signals"""
    if len(open_positions) >= MAX_OPEN_POSITIONS:
        print(f"⚠️ Max positions reached ({MAX_OPEN_POSITIONS})")
        return
    
    # Filter high-quality signals
    good_signals = [s for s in latest_signals 
                   if s.get('ev_score', 0) >= MIN_EV_SCORE 
                   and s.get('signal_type') == 'funding_arbitrage']
    
    if not good_signals:
        print("No high-quality signals to trade")
        return
    
    # Sort by EV
    good_signals.sort(key=lambda x: x['ev_score'], reverse=True)
    
    print(f"📈 Opening new positions from {len(good_signals)} signals...")
    
    for sig in good_signals[:MAX_OPEN_POSITIONS - len(open_positions)]:
        # Calculate position size
        if sig.get('conviction') == 'HIGH':
            pct = 0.05
        elif sig.get('conviction') == 'MEDIUM':
            pct = 0.03
        else:
            pct = 0.02
        
        position_size = balance * pct
        entry_price = sig.get('entry_price', 0)
        
        if entry_price == 0:
            continue
        
        # Create paper trade
        pt = PaperTrade(sig, entry_price, position_size)
        open_positions.append(pt)
        
        print(f"  ✅ OPENED: {sig['asset']} {sig['direction']} @ ${entry_price:.4f}")
        print(f"     Size: ${position_size:.2f} ({pct*100}%)")
        
        # Log
        PAPER_TRADES_FILE.parent.mkdir(exist_ok=True)
        with open(PAPER_TRADES_FILE, 'a') as f:
            f.write(json.dumps(pt.to_dict()) + '\n')


def calculate_performance():
    """Calculate overall performance metrics"""
    if not PAPER_TRADES_FILE.exists():
        return None
    
    all_trades = []
    with open(PAPER_TRADES_FILE) as f:
        for line in f:
            if line.strip():
                all_trades.append(json.loads(line))
    
    closed_trades = [t for t in all_trades if t['status'] != 'OPEN']
    
    if not closed_trades:
        return None
    
    wins = [t for t in closed_trades if t['pnl'] > 0]
    losses = [t for t in closed_trades if t['pnl'] <= 0]
    
    total_pnl = sum(t['pnl'] for t in closed_trades)
    win_rate = len(wins) / len(closed_trades) * 100 if closed_trades else 0
    avg_win = sum(t['pnl'] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t['pnl'] for t in losses) / len(losses) if losses else 0
    
    # Calculate by strategy type
    by_strategy = {}
    for t in closed_trades:
        strategy = t['signal'].get('signal_type', 'unknown')
        if strategy not in by_strategy:
            by_strategy[strategy] = {
                'trades': 0,
                'wins': 0,
                'total_pnl': 0,
                'avg_ev': 0
            }
        
        by_strategy[strategy]['trades'] += 1
        if t['pnl'] > 0:
            by_strategy[strategy]['wins'] += 1
        by_strategy[strategy]['total_pnl'] += t['pnl']
        by_strategy[strategy]['avg_ev'] = t['signal'].get('ev_score', 0)
    
    # Rank strategies
    strategy_rankings = []
    for strategy, stats in by_strategy.items():
        win_rate_strat = (stats['wins'] / stats['trades']) * 100 if stats['trades'] > 0 else 0
        strategy_rankings.append({
            'strategy': strategy,
            'trades': stats['trades'],
            'win_rate': round(win_rate_strat, 1),
            'total_pnl': round(stats['total_pnl'], 2),
            'avg_ev': round(stats['avg_ev'], 2),
            'score': round(win_rate_strat * (1 + stats['total_pnl']), 2)  # Combined score
        })
    
    strategy_rankings.sort(key=lambda x: x['score'], reverse=True)
    
    performance = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'total_trades': len(closed_trades),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate_pct': round(win_rate, 1),
        'total_pnl': round(total_pnl, 2),
        'avg_win': round(avg_win, 2),
        'avg_loss': round(avg_loss, 2),
        'best_trade': round(max(t['pnl'] for t in closed_trades), 2) if closed_trades else 0,
        'worst_trade': round(min(t['pnl'] for t in closed_trades), 2) if closed_trades else 0,
        'strategy_rankings': strategy_rankings
    }
    
    # Save performance
    with open(PERFORMANCE_FILE, 'w') as f:
        json.dumps(performance, indent=2)
    
    return performance


def main():
    print("=" * 80)
    print("PHASE 1: PAPER TRADING ENGINE")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S EDT')}")
    print("=" * 80)
    print()
    
    # Load state
    open_positions = load_open_positions()
    latest_signals = load_latest_signals()
    
    print(f"📊 Current State:")
    print(f"  Open Positions: {len(open_positions)}")
    print(f"  Latest Signals: {len(latest_signals)}")
    print()
    
    # Update existing positions
    update_open_positions(open_positions)
    
    # Open new positions if needed
    print()
    open_new_positions(latest_signals, open_positions, PAPER_BALANCE)
    
    # Calculate performance
    print()
    perf = calculate_performance()
    
    if perf:
        print("📊 PERFORMANCE SUMMARY:")
        print(f"  Total Trades: {perf['total_trades']}")
        print(f"  Win Rate: {perf['win_rate_pct']}%")
        print(f"  Total P&L: ${perf['total_pnl']:+.2f}")
        print(f"  Avg Win: ${perf['avg_win']:+.2f}")
        print(f"  Avg Loss: ${perf['avg_loss']:+.2f}")
        print()
        
        if perf['strategy_rankings']:
            print("🏆 STRATEGY RANKINGS:")
            for i, strat in enumerate(perf['strategy_rankings'], 1):
                print(f"  {i}. {strat['strategy']}: {strat['win_rate']}% WR, ${strat['total_pnl']:+.2f} PnL (Score: {strat['score']})")
    else:
        print("⏳ No closed trades yet")
    
    print("=" * 80)


if __name__ == "__main__":
    main()
