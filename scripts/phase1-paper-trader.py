#!/usr/bin/env python3
"""
Phase 1 Paper Trading Engine - FIXED VERSION
Simulates Hyperliquid paper trades based on scanner signals, tracks performance,
and updates authoritative position state only when trade records are persisted.
"""

import json
import sys
import os
import requests
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.runtime import WORKSPACE_ROOT as WORKSPACE, LOGS_DIR, DATA_DIR
from models.position_state import apply_trade_to_position_state, get_open_positions
from models.trade_schema import normalize_trade_record, validate_trade_record
from utils.json_utils import safe_read_json, safe_read_jsonl, write_json_atomic
PAPER_TRADES_FILE = LOGS_DIR / "phase1-paper-trades.jsonl"
PERFORMANCE_FILE = LOGS_DIR / "phase1-performance.json"
SIGNALS_FILE = LOGS_DIR / "phase1-signals.jsonl"
POSITION_STATE_FILE = LOGS_DIR / "position-state.json"

PAPER_BALANCE = 97.80  # Starting paper balance
MAX_OPEN_POSITIONS = 3  # Hard cap
MIN_EV_SCORE = 40  # Only paper trade signals with EV > 40

# Exit thresholds
TAKE_PROFIT_PCT = 10.0
STOP_LOSS_PCT = -10.0
TIMEOUT_HOURS = 24.0


def log_non_canonical_signal(signal: dict | None, reason: str) -> None:
    signal_type = (signal or {}).get('signal_type', 'unknown')
    identifier = (signal or {}).get('asset') or (signal or {}).get('market') or 'unknown'
    print(f"  [SKIP] SKIPPED_NON_CANONICAL_SIGNAL: {identifier} ({signal_type}) - {reason}")


def validate_canonical_signal(signal: dict | None) -> tuple[bool, str]:
    if not isinstance(signal, dict):
        return False, "signal payload is not a dict"

    if signal.get('signal_type') != 'funding_arbitrage':
        return False, f"signal_type={signal.get('signal_type')!r} is not canonical funding_arbitrage"

    missing_fields = [
        field for field in ('asset', 'direction', 'entry_price')
        if signal.get(field) is None
    ]
    if missing_fields:
        return False, f"missing required fields: {missing_fields}"

    return True, "canonical hyperliquid signal"


class PaperTrader:
    """Paper trading engine for supported Phase 1 paper-trade signals."""
    
    def __init__(self, signal):
        self.signal = signal
        self.position_id = str(uuid.uuid4())[:8]
        
    def execute(self):
        """Execute paper trade for any strategy type"""
        valid, reason = validate_canonical_signal(self.signal)
        if not valid:
            log_non_canonical_signal(self.signal, reason)
            return None

        return self.execute_hyperliquid()
    
    def execute_hyperliquid(self):
        """Execute Hyperliquid funding arbitrage"""
        asset = self.signal['asset']
        direction = self.signal['direction']
        entry_price = self.signal['entry_price']
        
        # Calculate position size (2% of account for MEDIUM conviction)
        position_size_usd = PAPER_BALANCE * 0.02
        position_size = position_size_usd / entry_price
        
        entry_timestamp = datetime.now(timezone.utc).isoformat()
        trade = {
            'trade_id': self.position_id,
            'position_id': self.position_id,
            'timestamp': entry_timestamp,
            'entry_timestamp': entry_timestamp,
            'entry_time': entry_timestamp,
            'signal': self.signal,
            'exchange': 'Hyperliquid',
            'strategy': 'funding_arbitrage',
            'symbol': asset,
            'asset': asset,
            'side': direction,
            'direction': direction,
            'entry_price': entry_price,
            'position_size': position_size,
            'position_size_usd': position_size_usd,
            'status': 'OPEN',
            'stop_loss_pct': STOP_LOSS_PCT,
            'take_profit_pct': TAKE_PROFIT_PCT,
            'timeout_hours': TIMEOUT_HOURS
        }
        
        print(f"  [OK] Paper trade: {direction} {position_size:.4f} {asset} @ ${entry_price:.4f}")
        return trade
    
    # Polymarket is NOT ACTIVE here - scanner output lacks the execution fields required
    # for authoritative paper-trade records.


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
    if 'symbol' not in position or 'entry_price' not in position or 'entry_timestamp' not in position:
        return False, None

    asset = position['symbol']
    entry_price = position['entry_price']
    direction = position.get('side', position.get('direction', 'LONG'))
    
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
    entry_time = datetime.fromisoformat(position['entry_timestamp'])
    now = datetime.now(timezone.utc)
    age_hours = (now - entry_time).total_seconds() / 3600
    
    if age_hours >= TIMEOUT_HOURS:
        return True, 'timeout'
    
    return False, None


def load_open_positions() -> list:
    """Load open positions from authoritative position-state.json only."""
    return get_open_positions(POSITION_STATE_FILE)


def load_latest_signals(limit: int = 10) -> list:
    """Load latest signals from log"""
    return safe_read_jsonl(SIGNALS_FILE)[-limit:]


def filter_unconsumed_signals(signals: list) -> list:
    """
    Filter out signals that have already been consumed
    A signal is consumed if a position (open or closed) exists with matching signal timestamp
    """
    # Collect all consumed signal timestamps
    consumed_timestamps = set()
    for trade in safe_read_jsonl(PAPER_TRADES_FILE):
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
    # Load all closed trades
    closed_trades = []
    for trade in safe_read_jsonl(PAPER_TRADES_FILE):
        normalized = normalize_trade_record(trade)
        if not validate_trade_record(normalized, context='phase1-paper-trader.calculate_performance'):
            continue
        if normalized.get('status') == 'CLOSED':
            closed_trades.append(normalized)
    
    if not closed_trades:
        return {'total_trades': 0}
    
    # Calculate metrics
    winners = [t for t in closed_trades if (t.get('realized_pnl_usd') or 0) > 0]
    losers = [t for t in closed_trades if (t.get('realized_pnl_usd') or 0) <= 0]
    
    total_pnl = sum((t.get('realized_pnl_usd') or 0) for t in closed_trades)
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
    write_json_atomic(PERFORMANCE_FILE, performance)
    
    return performance


def log_trade(trade: dict):
    """Append trade to log and update authoritative position state."""
    PAPER_TRADES_FILE.parent.mkdir(exist_ok=True)
    with open(PAPER_TRADES_FILE, 'a') as f:
        f.write(json.dumps(trade) + '\n')

    apply_trade_to_position_state(POSITION_STATE_FILE, trade)


def close_position(position: dict, exit_price: float, exit_reason: str):
    """Close an open position"""
    asset = position['symbol']
    entry_price = position['entry_price']
    direction = position.get('side', position.get('direction', 'LONG'))
    
    # Calculate final P&L with correct formula
    pnl_usd, pnl_pct = calculate_pnl(entry_price, exit_price, position['position_size'], direction)
    
    exit_timestamp = datetime.now(timezone.utc).isoformat()
    closed_trade = {
        **position,
        'trade_id': position.get('trade_id'),
        'position_id': position.get('trade_id', position.get('position_id')),
        'symbol': position.get('symbol', asset),
        'asset': asset,
        'side': position.get('side', direction),
        'direction': direction,
        'status': 'CLOSED',
        'exit_timestamp': exit_timestamp,
        'exit_time': exit_timestamp,
        'exit_price': exit_price,
        'exit_reason': exit_reason,
        'realized_pnl_usd': pnl_usd,
        'realized_pnl_pct': pnl_pct
    }
    
    log_trade(closed_trade)
    print(f"  [RED] Closed {direction} {asset}: {exit_reason} | P&L: ${pnl_usd:+.2f} ({pnl_pct:+.1f}%)")


def evaluate_exit_trades(open_positions: list) -> list[dict]:
    """Build close trades for positions that should exit."""
    planned_closes = []
    for position in open_positions:
        asset = position['symbol']
        should_exit, reason = check_exit(position)
        if not should_exit:
            continue

        current_price = get_current_price(asset)
        if not current_price:
            print(f"  [WARN] Exit skipped for {asset}: current price unavailable")
            continue

        entry_price = position['entry_price']
        direction = position.get('side', position.get('direction', 'LONG'))
        pnl_usd, pnl_pct = calculate_pnl(entry_price, current_price, position['position_size'], direction)
        exit_timestamp = datetime.now(timezone.utc).isoformat()
        planned_closes.append({
            **position,
            'trade_id': position.get('trade_id'),
            'position_id': position.get('trade_id', position.get('position_id')),
            'symbol': position.get('symbol', asset),
            'asset': asset,
            'side': position.get('side', direction),
            'direction': direction,
            'status': 'CLOSED',
            'exit_timestamp': exit_timestamp,
            'exit_time': exit_timestamp,
            'exit_price': current_price,
            'exit_reason': reason,
            'realized_pnl_usd': pnl_usd,
            'realized_pnl_pct': pnl_pct
        })

    return planned_closes


def select_trade_candidate(
    signals: list,
    open_positions: list,
    allowed_signal_timestamp: str | None = None,
    allow_new_entries: bool = True,
) -> tuple[dict | None, str]:
    """Select the next eligible entry signal using the existing paper-trader rules."""
    if not allow_new_entries:
        return None, "New entries disabled for this cycle"

    if len(open_positions) >= MAX_OPEN_POSITIONS:
        return None, f"At capacity ({len(open_positions)}/{MAX_OPEN_POSITIONS})"

    unconsumed = filter_unconsumed_signals(signals)
    good_signals = []
    for signal in unconsumed:
        if signal.get('ev_score', 0) < MIN_EV_SCORE or not signal.get('timestamp'):
            continue

        valid, reason = validate_canonical_signal(signal)
        if not valid:
            log_non_canonical_signal(signal, reason)
            continue

        good_signals.append(signal)

    if allowed_signal_timestamp is not None:
        good_signals = [s for s in good_signals if s.get('timestamp') == allowed_signal_timestamp]
        if not good_signals:
            return None, f"Allowed signal {allowed_signal_timestamp} not available"

    if not good_signals:
        return None, "No signals above EV threshold"

    best_signal = max(good_signals, key=lambda x: x.get('ev_score', 0))
    open_assets = [p['symbol'] for p in open_positions if p.get('symbol')]
    signal_asset = best_signal.get('asset')

    if signal_asset and signal_asset in open_assets:
        return None, f"Already have open position in {signal_asset}"

    return best_signal, f"Selected {signal_asset or 'unknown'} @ EV {best_signal.get('ev_score', 0):.2f}"


def build_execution_plan(
    allowed_signal_timestamp: str | None = None,
    allow_new_entries: bool = True,
) -> dict:
    """Build a deterministic set of trade records for this cycle without persisting them."""
    open_positions = load_open_positions()
    signals = load_latest_signals()

    planned_closes = evaluate_exit_trades(open_positions)
    refreshed_open_positions = [
        position for position in open_positions
        if position.get('trade_id') not in {trade.get('trade_id') for trade in planned_closes}
    ]

    candidate_signal, entry_reason = select_trade_candidate(
        signals=signals,
        open_positions=refreshed_open_positions,
        allowed_signal_timestamp=allowed_signal_timestamp,
        allow_new_entries=allow_new_entries,
    )

    planned_entry = None
    if candidate_signal is not None:
        trader = PaperTrader(candidate_signal)
        planned_entry = trader.execute()

    planned_trades = [*planned_closes, *([planned_entry] if planned_entry else [])]
    return {
        'open_positions': open_positions,
        'signals': signals,
        'planned_trades': planned_trades,
        'planned_closes': planned_closes,
        'planned_entry': planned_entry,
        'entry_reason': entry_reason,
    }


def persist_trade_records(trades: list[dict]) -> int:
    """Persist trade records and update authoritative state in append order."""
    persisted = 0
    for trade in trades:
        log_trade(trade)
        persisted += 1
    return persisted


def main():
    """Main paper trading loop"""
    print("="*80)
    print("PHASE 1 PAPER TRADER (FIXED)")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M EDT')}")
    print("="*80)
    print()
    
    plan = build_execution_plan()
    open_positions = plan['open_positions']
    signals = plan['signals']
    
    print(f"[STATS] Status:")
    print(f"   Open positions: {len(open_positions)}/{MAX_OPEN_POSITIONS}")
    print(f"   Latest signals: {len(signals)}")
    print()
    
    # Check exits for open positions
    if open_positions:
        print("[SCAN] Checking exits...")
        for trade in plan['planned_closes']:
            print(
                f"  [RED] Closed {trade['direction']} {trade['asset']}: {trade['exit_reason']} | "
                f"P&L: ${trade['realized_pnl_usd']:+.2f} ({trade['realized_pnl_pct']:+.1f}%)"
            )
        if not plan['planned_closes']:
            print("  No exits triggered")
        print()

    print("[TREND] Evaluating new signals...")
    if plan['planned_entry'] is not None:
        persist_trade_records(plan['planned_closes'])
        persist_trade_records([plan['planned_entry']])
    else:
        persist_trade_records(plan['planned_closes'])
        print(f"  {plan['entry_reason']}")
    
    print()
    
    # Update performance
    performance = calculate_performance()
    
    if performance.get('total_trades', 0) > 0:
        print(f"[STATS] Performance:")
        print(f"   Total trades: {performance['total_trades']}")
        print(f"   Win rate: {performance['win_rate']:.1f}%")
        print(f"   Total P&L: ${performance['total_pnl_usd']:+.2f}")
    
    print()
    print("[OK] Paper trader complete")


if __name__ == "__main__":
    main()
