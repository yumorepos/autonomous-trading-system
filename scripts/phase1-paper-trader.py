#!/usr/bin/env python3
"""
Phase 1 Paper Trading Engine - FIXED VERSION
Simulates trades based on signals, tracks performance, ranks strategies
FIXES: SHORT PnL, position IDs, multi-strategy, performance persistence
"""

import json
import os
import requests
import uuid
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path.home() / ".openclaw" / "workspace"
PAPER_TRADES_FILE = WORKSPACE / "logs" / "phase1-paper-trades.jsonl"
PERFORMANCE_FILE = WORKSPACE / "logs" / "phase1-performance.json"
SIGNALS_FILE = WORKSPACE / "logs" / "phase1-signals.jsonl"
POSITION_STATE_FILE = WORKSPACE / "logs" / "position-state.json"

PAPER_BALANCE = 97.80  # Starting paper balance
MAX_OPEN_POSITIONS = 3  # Hard cap
MIN_EV_SCORE = 40  # Only paper trade signals with EV > 40

# Exit thresholds
TAKE_PROFIT_PCT = 10.0
STOP_LOSS_PCT = -10.0
TIMEOUT_HOURS = 24.0


class PaperTrader:
    """Paper trading engine with multi-strategy support"""
    
    def __init__(self, signal):
        self.signal = signal
        self.position_id = str(uuid.uuid4())[:8]
        
    def execute(self):
        """Execute paper trade for any strategy type"""
        signal_type = self.signal.get('signal_type')
        
        # ONLY funding_arbitrage supported (Polymarket disabled - schema incomplete)
        if signal_type == 'funding_arbitrage':
            return self.execute_hyperliquid()
        else:
            # Polymarket explicitly disabled (scanner missing required fields)
            return None
    
    def execute_hyperliquid(self):
        """Execute Hyperliquid funding arbitrage"""
        asset = self.signal['asset']
        direction = self.signal['direction']
        entry_price = self.signal['entry_price']
        
        # Calculate position size (2% of account for MEDIUM conviction)
        position_size_usd = PAPER_BALANCE * 0.02
        position_size = position_size_usd / entry_price
        
        trade = {
            'position_id': self.position_id,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'signal': self.signal,
            'exchange': 'Hyperliquid',
            'strategy': 'funding_arbitrage',
            'entry_price': entry_price,
            'position_size': position_size,
            'position_size_usd': position_size_usd,
            'direction': direction,
            'entry_time': datetime.now(timezone.utc).isoformat(),
            'status': 'OPEN',
            'stop_loss_pct': STOP_LOSS_PCT,
            'take_profit_pct': TAKE_PROFIT_PCT,
            'timeout_hours': TIMEOUT_HOURS
        }
        
        print(f"  ✅ Paper trade: {direction} {position_size:.4f} {asset} @ ${entry_price:.4f}")
        return trade
    
    # Polymarket DISABLED - scanner schema incomplete (missing market_id, side)


def get_current_price(asset: str) -> float:
    """Get current Hyperliquid price"""
    try:
        r = requests.post("https://api.hyperliquid.xyz/info",
                         json={'type': 'allMids'}, timeout=5)
        if r.status_code == 200:
            prices = r.json()
            return float(prices.get(asset, 0))
    except:
        pass
    return 0


def calculate_pnl(entry_price: float, current_price: float, position_size: float, direction: str) -> tuple:
    """
    Calculate P&L correctly for LONG and SHORT positions
    
    FIXED: Was using LONG-only formula for all positions
    """
    if direction == 'LONG':
        pnl_usd = (current_price - entry_price) * position_size
        pnl_pct = ((current_price - entry_price) / entry_price) * 100
    else:  # SHORT
        pnl_usd = (entry_price - current_price) * position_size
        pnl_pct = ((entry_price - current_price) / entry_price) * 100
    
    return pnl_usd, pnl_pct


def check_exit(position: dict) -> tuple[bool, str]:
    """
    Check if position should exit
    Returns: (should_exit, reason)
    """
    # Validate required fields
    if not position.get('signal') or 'asset' not in position.get('signal', {}):
        return False, None
    if 'entry_price' not in position or 'entry_time' not in position:
        return False, None
    
    asset = position['signal']['asset']
    entry_price = position['entry_price']
    direction = position.get('direction', 'LONG')
    
    current_price = get_current_price(asset)
    if not current_price:
        return False, None
    
    # Calculate P&L with correct formula for direction
    _, pnl_pct = calculate_pnl(entry_price, current_price, position['position_size'], direction)
    
    # Check take profit
    if pnl_pct >= TAKE_PROFIT_PCT:
        return True, 'take_profit'
    
    # Check stop loss
    if pnl_pct <= STOP_LOSS_PCT:
        return True, 'stop_loss'
    
    # Check time limit
    entry_time = datetime.fromisoformat(position['entry_time'])
    now = datetime.now(timezone.utc)
    age_hours = (now - entry_time).total_seconds() / 3600
    
    if age_hours >= TIMEOUT_HOURS:
        return True, 'timeout'
    
    return False, None


def load_position_state() -> dict:
    """
    Load position state from dedicated state file
    
    FIXED: Replaces fragile JSONL append-only reconstruction
    State file tracks: position_id -> status mapping
    """
    if not POSITION_STATE_FILE.exists():
        return {}
    
    try:
        with open(POSITION_STATE_FILE) as f:
            return json.load(f)
    except:
        return {}


def save_position_state(state: dict):
    """Save position state to file"""
    POSITION_STATE_FILE.parent.mkdir(exist_ok=True)
    with open(POSITION_STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def load_open_positions() -> list:
    """
    Load open positions with ghost prevention
    
    FIXED: Uses position_id and state file to prevent ghost positions
    """
    if not PAPER_TRADES_FILE.exists():
        return []
    
    # Load position state
    state = load_position_state()
    
    # Load all positions from log
    all_positions = []
    with open(PAPER_TRADES_FILE) as f:
        for line in f:
            if line.strip():
                trade = json.loads(line)
                all_positions.append(trade)
    
    # Filter to truly open positions using state file
    open_positions = []
    for pos in all_positions:
        # Skip malformed records
        if not pos.get('signal') or 'asset' not in pos.get('signal', {}):
            continue
        if 'entry_price' not in pos or 'entry_time' not in pos:
            continue
        
        position_id = pos.get('position_id')
        
        if not position_id:
            # Legacy position without ID - check status field
            if pos.get('status') == 'OPEN':
                open_positions.append(pos)
        else:
            # New position with ID - check state file
            if state.get(position_id) == 'OPEN':
                open_positions.append(pos)
    
    return open_positions


def load_latest_signals(limit: int = 10) -> list:
    """Load latest signals from log"""
    if not SIGNALS_FILE.exists():
        return []
    
    signals = []
    with open(SIGNALS_FILE) as f:
        for line in f:
            if line.strip():
                signals.append(json.loads(line))
    
    return signals[-limit:]


def filter_unconsumed_signals(signals: list) -> list:
    """
    Filter out signals that have already been consumed
    A signal is consumed if a position (open or closed) exists with matching signal timestamp
    """
    if not PAPER_TRADES_FILE.exists():
        return signals
    
    # Collect all consumed signal timestamps
    consumed_timestamps = set()
    with open(PAPER_TRADES_FILE) as f:
        for line in f:
            if line.strip():
                trade = json.loads(line)
                sig_timestamp = trade.get('signal', {}).get('timestamp')
                if sig_timestamp:
                    consumed_timestamps.add(sig_timestamp)
    
    # Filter to unconsumed only
    unconsumed = [s for s in signals if s.get('timestamp') not in consumed_timestamps]
    
    return unconsumed


def calculate_performance() -> dict:
    """
    Calculate strategy performance metrics
    
    FIXED: Actually writes to file (was missing f.write())
    """
    if not PAPER_TRADES_FILE.exists():
        return {}
    
    # Load all closed trades
    closed_trades = []
    with open(PAPER_TRADES_FILE) as f:
        for line in f:
            if line.strip():
                trade = json.loads(line)
                if trade.get('status') == 'CLOSED':
                    closed_trades.append(trade)
    
    if not closed_trades:
        return {'total_trades': 0}
    
    # Calculate metrics
    winners = [t for t in closed_trades if t.get('realized_pnl_usd', 0) > 0]
    losers = [t for t in closed_trades if t.get('realized_pnl_usd', 0) <= 0]
    
    total_pnl = sum(t.get('realized_pnl_usd', 0) for t in closed_trades)
    win_rate = len(winners) / len(closed_trades) * 100 if closed_trades else 0
    
    performance = {
        'total_trades': len(closed_trades),
        'winners': len(winners),
        'losers': len(losers),
        'win_rate': win_rate,
        'total_pnl_usd': total_pnl,
        'last_updated': datetime.now(timezone.utc).isoformat()
    }
    
    # FIXED: Actually write to file
    PERFORMANCE_FILE.parent.mkdir(exist_ok=True)
    with open(PERFORMANCE_FILE, 'w') as f:
        json.dump(performance, f, indent=2)
    
    return performance


def log_trade(trade: dict):
    """Append trade to log"""
    PAPER_TRADES_FILE.parent.mkdir(exist_ok=True)
    with open(PAPER_TRADES_FILE, 'a') as f:
        f.write(json.dumps(trade) + '\n')
    
    # Update position state
    position_id = trade.get('position_id')
    if position_id:
        state = load_position_state()
        state[position_id] = trade['status']
        save_position_state(state)


def close_position(position: dict, exit_price: float, exit_reason: str):
    """Close an open position"""
    asset = position['signal']['asset']
    entry_price = position['entry_price']
    direction = position.get('direction', 'LONG')
    
    # Calculate final P&L with correct formula
    pnl_usd, pnl_pct = calculate_pnl(entry_price, exit_price, position['position_size'], direction)
    
    closed_trade = {
        **position,
        'status': 'CLOSED',
        'exit_time': datetime.now(timezone.utc).isoformat(),
        'exit_price': exit_price,
        'exit_reason': exit_reason,
        'realized_pnl_usd': pnl_usd,
        'realized_pnl_pct': pnl_pct
    }
    
    log_trade(closed_trade)
    print(f"  🔴 Closed {direction} {asset}: {exit_reason} | P&L: ${pnl_usd:+.2f} ({pnl_pct:+.1f}%)")


def main():
    """Main paper trading loop"""
    print("="*80)
    print("PHASE 1 PAPER TRADER (FIXED)")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M EDT')}")
    print("="*80)
    print()
    
    # Load current state
    open_positions = load_open_positions()
    signals = load_latest_signals()
    
    print(f"📊 Status:")
    print(f"   Open positions: {len(open_positions)}/{MAX_OPEN_POSITIONS}")
    print(f"   Latest signals: {len(signals)}")
    print()
    
    # Check exits for open positions
    if open_positions:
        print("🔍 Checking exits...")
        for position in open_positions:
            asset = position['signal']['asset']
            should_exit, reason = check_exit(position)
            
            if should_exit:
                current_price = get_current_price(asset)
                close_position(position, current_price, reason)
        print()
    
    # Check if we can open new positions
    open_positions = load_open_positions()  # Reload after closes
    
    if len(open_positions) >= MAX_OPEN_POSITIONS:
        print(f"⚠️  At capacity ({len(open_positions)}/{MAX_OPEN_POSITIONS})")
        print("   No new entries until positions close")
    else:
        print("📈 Evaluating new signals...")
        
        # Filter out already-consumed signals
        unconsumed = filter_unconsumed_signals(signals)
        
        # Filter to high-quality signals
        good_signals = [s for s in unconsumed 
                       if s.get('ev_score', 0) >= MIN_EV_SCORE
                       and s.get('timestamp')]
        
        if good_signals:
            # Take highest EV signal
            best_signal = max(good_signals, key=lambda x: x.get('ev_score', 0))
            
            # Check if we already have a position in this asset
            open_assets = [p['signal']['asset'] for p in open_positions if 'asset' in p['signal']]
            signal_asset = best_signal.get('asset')
            
            if signal_asset and signal_asset in open_assets:
                print(f"  ⚠️ Already have open position in {signal_asset}")
            else:
                # Execute trade
                trader = PaperTrader(best_signal)
                trade = trader.execute()
                
                if trade:
                    log_trade(trade)
        else:
            print("  No signals above EV threshold")
    
    print()
    
    # Update performance
    performance = calculate_performance()
    
    if performance.get('total_trades', 0) > 0:
        print(f"📊 Performance:")
        print(f"   Total trades: {performance['total_trades']}")
        print(f"   Win rate: {performance['win_rate']:.1f}%")
        print(f"   Total P&L: ${performance['total_pnl_usd']:+.2f}")
    
    print()
    print("✅ Paper trader complete")


if __name__ == "__main__":
    main()
