#!/usr/bin/env python3
"""
Phase 1 paper trading engine.
Supports canonical Hyperliquid and Polymarket paper trades through the same
shared execution architecture. Mixed mode remains a limited deterministic
one-entry-per-cycle evaluation path.
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.runtime import LOGS_DIR, TRADING_MODE, mode_includes_hyperliquid, mode_includes_polymarket
from models.exchange_metadata import (
    mixed_mode_max_new_entries_per_cycle,
    mixed_mode_selection_note,
    paper_exchange_priority,
    paper_exchange_status,
)
from utils.paper_exchange_adapters import get_paper_exchange_adapter, paper_position_identifier
from models.position_state import apply_trade_to_position_state, get_open_positions
from models.trade_schema import normalize_trade_record, validate_trade_record
from utils.json_utils import safe_read_jsonl, write_json_atomic
from utils.runtime_logging import append_runtime_event

PAPER_TRADES_FILE = LOGS_DIR / "phase1-paper-trades.jsonl"
PERFORMANCE_FILE = LOGS_DIR / "phase1-performance.json"
SIGNALS_FILE = LOGS_DIR / "phase1-signals.jsonl"
POSITION_STATE_FILE = LOGS_DIR / "position-state.json"

PAPER_BALANCE = 97.80
MAX_OPEN_POSITIONS = 3
MIN_EV_SCORE = 4

def log_non_canonical_signal(signal: dict | None, reason: str) -> None:
    signal_type = (signal or {}).get('signal_type', 'unknown')
    identifier = (signal or {}).get('asset') or (signal or {}).get('market_id') or 'unknown'
    print(f"  [SKIP] SKIPPED_NON_CANONICAL_SIGNAL: {identifier} ({signal_type}) - {reason}")
    append_runtime_event(
        stage='paper_trader',
        exchange=(signal or {}).get('exchange', (signal or {}).get('source', 'unknown')),
        lifecycle_stage='validation_skipped',
        status='WARN',
        message=f"Non-canonical paper-trading signal skipped: {reason}",
        metadata={'identifier': identifier, 'signal_type': signal_type},
    )



def validate_canonical_signal(signal: dict | None) -> tuple[bool, str]:
    if not isinstance(signal, dict):
        return False, "signal payload is not a dict"

    exchange = signal.get('exchange', signal.get('source'))
    adapter = get_paper_exchange_adapter(exchange)
    if adapter is None:
        return False, f"unsupported exchange={exchange!r}"
    return adapter.validate_signal(signal)



def _position_identifier(signal_or_position: dict) -> str | None:
    return paper_position_identifier(signal_or_position)


class PaperTrader:
    """Paper trading engine for supported paper-trade signals."""

    def __init__(self, signal: dict):
        self.signal = signal
        self.position_id = str(uuid.uuid4())[:8]

    def execute(self) -> dict | None:
        valid, reason = validate_canonical_signal(self.signal)
        if not valid:
            log_non_canonical_signal(self.signal, reason)
            return None

        exchange = self.signal.get('exchange', self.signal.get('source'))
        adapter = get_paper_exchange_adapter(exchange)
        if adapter is None:
            log_non_canonical_signal(self.signal, f"unsupported exchange={exchange!r}")
            return None

        trade = adapter.build_trade(self.signal, self.position_id)
        if exchange == 'Polymarket':
            print(f"  [OK] Polymarket paper trade: {trade['side']} {trade['market_id']} ({trade['position_size']:.4f} shares) @ ${trade['entry_price']:.4f}")
            metadata = {'trade_id': self.position_id, 'market_id': trade['market_id'], 'side': trade['side'], 'entry_price': trade['entry_price']}
        else:
            print(f"  [OK] Hyperliquid paper trade: {trade['side']} {trade['position_size']:.4f} {trade['symbol']} @ ${trade['entry_price']:.4f}")
            metadata = {'trade_id': self.position_id, 'symbol': trade['symbol'], 'side': trade['side'], 'entry_price': trade['entry_price']}
        append_runtime_event(
            stage='paper_trader',
            exchange=exchange,
            lifecycle_stage='entry_planned',
            status='INFO',
            message=f'{exchange} paper trade planned',
            metadata=metadata,
        )
        return trade



def get_position_current_price(position: dict) -> float:
    exchange = position.get('exchange') or position.get('signal', {}).get('exchange') or position.get('signal', {}).get('source')
    adapter = get_paper_exchange_adapter(exchange)
    if adapter is None:
        return 0
    try:
        return adapter.get_current_price(position, requests)
    except Exception:
        return 0



def calculate_pnl(entry_price: float, current_price: float, position_size: float, direction: str, exchange: str = 'Hyperliquid') -> tuple[float, float]:
    adapter = get_paper_exchange_adapter(exchange)
    if adapter is None:
        return 0, 0
    return adapter.calculate_pnl(entry_price, current_price, position_size, direction)



def check_exit(position: dict) -> tuple[bool, str | None]:
    if 'symbol' not in position or 'entry_price' not in position or 'entry_timestamp' not in position:
        return False, None

    exchange = position.get('exchange', 'Hyperliquid')
    current_price = get_position_current_price(position)
    if not current_price:
        return False, None

    adapter = get_paper_exchange_adapter(exchange)
    if adapter is None:
        return False, None
    direction = position.get('side', position.get('direction', 'LONG'))
    _, pnl_pct = calculate_pnl(position['entry_price'], current_price, position['position_size'], direction, exchange=exchange)

    if pnl_pct >= adapter.take_profit_pct:
        return True, 'take_profit'
    if pnl_pct <= adapter.stop_loss_pct:
        return True, 'stop_loss'

    age_hours = (datetime.now(timezone.utc) - datetime.fromisoformat(position['entry_timestamp'])).total_seconds() / 3600
    if age_hours >= adapter.timeout_hours:
        return True, 'timeout'
    return False, None



def load_open_positions() -> list[dict]:
    return get_open_positions(POSITION_STATE_FILE)



def load_latest_signals(limit: int = 20) -> list[dict]:
    return safe_read_jsonl(SIGNALS_FILE)[-limit:]



def filter_unconsumed_signals(signals: list[dict]) -> list[dict]:
    consumed_timestamps = set()
    for trade in safe_read_jsonl(PAPER_TRADES_FILE):
        sig_timestamp = trade.get('signal', {}).get('timestamp')
        if sig_timestamp:
            consumed_timestamps.add(sig_timestamp)
    return [signal for signal in signals if signal.get('timestamp') not in consumed_timestamps]



def calculate_performance() -> dict:
    closed_trades = []
    exchange_breakdown: dict[str, dict[str, float | int]] = {}
    for trade in safe_read_jsonl(PAPER_TRADES_FILE):
        normalized = normalize_trade_record(trade)
        if not validate_trade_record(normalized, context='phase1-paper-trader.calculate_performance'):
            continue
        if normalized.get('status') != 'CLOSED':
            continue
        closed_trades.append(normalized)
        exchange = normalized.get('exchange', 'Unknown')
        breakdown = exchange_breakdown.setdefault(exchange, {'total_trades': 0, 'total_pnl_usd': 0.0})
        breakdown['total_trades'] += 1
        breakdown['total_pnl_usd'] += float(normalized.get('realized_pnl_usd') or 0)

    if not closed_trades:
        performance = {'total_trades': 0, 'exchange_breakdown': exchange_breakdown}
        write_json_atomic(PERFORMANCE_FILE, performance)
        return performance

    winners = [t for t in closed_trades if (t.get('realized_pnl_usd') or 0) > 0]
    losers = [t for t in closed_trades if (t.get('realized_pnl_usd') or 0) <= 0]
    total_pnl = sum((t.get('realized_pnl_usd') or 0) for t in closed_trades)
    performance = {
        'total_trades': len(closed_trades),
        'winners': len(winners),
        'losers': len(losers),
        'win_rate': len(winners) / len(closed_trades) * 100 if closed_trades else 0,
        'total_pnl_usd': total_pnl,
        'exchange_breakdown': exchange_breakdown,
        'last_updated': datetime.now(timezone.utc).isoformat(),
    }
    write_json_atomic(PERFORMANCE_FILE, performance)
    return performance



def log_trade(trade: dict) -> None:
    PAPER_TRADES_FILE.parent.mkdir(exist_ok=True)
    with open(PAPER_TRADES_FILE, 'a') as f:
        f.write(json.dumps(trade) + '\n')
    append_runtime_event(
        stage='paper_trader',
        exchange=trade.get('exchange', 'unknown'),
        lifecycle_stage='trade_persisted',
        status='INFO',
        message='Paper-trading trade record persisted',
        metadata={
            'trade_id': trade.get('trade_id'),
            'symbol': trade.get('symbol'),
            'status': trade.get('status'),
            'paper_only': trade.get('paper_only', True),
        },
    )
    apply_trade_to_position_state(POSITION_STATE_FILE, trade)



def evaluate_exit_trades(open_positions: list[dict]) -> list[dict]:
    planned_closes = []
    for position in open_positions:
        should_exit, reason = check_exit(position)
        if not should_exit:
            continue
        current_price = get_position_current_price(position)
        if not current_price:
            print(f"  [WARN] Exit skipped for {_position_identifier(position)}: current price unavailable")
            continue
        exchange = position.get('exchange', 'Hyperliquid')
        direction = position.get('side', position.get('direction', 'LONG'))
        pnl_usd, pnl_pct = calculate_pnl(position['entry_price'], current_price, position['position_size'], direction, exchange=exchange)
        exit_timestamp = datetime.now(timezone.utc).isoformat()
        planned_closes.append({
            **position,
            'trade_id': position.get('trade_id'),
            'position_id': position.get('trade_id', position.get('position_id')),
            'status': 'CLOSED',
            'exit_timestamp': exit_timestamp,
            'exit_time': exit_timestamp,
            'exit_price': current_price,
            'exit_reason': reason,
            'realized_pnl_usd': pnl_usd,
            'realized_pnl_pct': pnl_pct,
        })
        append_runtime_event(
            stage='paper_trader',
            exchange=exchange,
            lifecycle_stage='exit_planned',
            status='INFO',
            message='Paper-trading exit planned',
            metadata={'trade_id': position.get('trade_id'), 'symbol': position.get('symbol'), 'exit_reason': reason},
        )
    return planned_closes



def select_trade_candidate(signals: list[dict], open_positions: list[dict], allowed_signal_timestamp: str | None = None, allow_new_entries: bool = True) -> tuple[dict | None, str]:
    if not allow_new_entries:
        return None, 'New entries disabled for this cycle'
    if len(open_positions) >= MAX_OPEN_POSITIONS:
        return None, f"At capacity ({len(open_positions)}/{MAX_OPEN_POSITIONS})"

    good_signals = []
    unconsumed = filter_unconsumed_signals(signals)
    open_identifiers = {_position_identifier(position) for position in open_positions}
    for signal in unconsumed:
        if signal.get('ev_score', 0) < MIN_EV_SCORE or not signal.get('timestamp'):
            continue
        exchange = signal.get('exchange', signal.get('source'))
        if exchange == 'Hyperliquid' and not mode_includes_hyperliquid(TRADING_MODE):
            continue
        if exchange == 'Polymarket' and not mode_includes_polymarket(TRADING_MODE):
            continue
        valid, reason = validate_canonical_signal(signal)
        if not valid:
            log_non_canonical_signal(signal, reason)
            continue
        identifier = _position_identifier(signal)
        if identifier and identifier in open_identifiers:
            continue
        good_signals.append(signal)

    if allowed_signal_timestamp is not None:
        good_signals = [signal for signal in good_signals if signal.get('timestamp') == allowed_signal_timestamp]
        if not good_signals:
            return None, f"Allowed signal {allowed_signal_timestamp} not available"

    if not good_signals:
        return None, 'No signals above EV threshold'

    ranked_signals = sorted(
        good_signals,
        key=lambda signal: (
            paper_exchange_priority(signal.get('exchange', signal.get('source'))),
            -(signal.get('ev_score', 0)),
            signal.get('timestamp', ''),
        ),
    )
    best_signal = ranked_signals[0]
    exchange = best_signal.get('exchange', best_signal.get('source'))
    status = paper_exchange_status(exchange).replace('_', ' ')
    canonical_note = (
        f"{mixed_mode_selection_note(exchange)}; max_new_entries_per_cycle={mixed_mode_max_new_entries_per_cycle()}"
        if TRADING_MODE == 'mixed'
        else status
    )
    return best_signal, (
        f"Selected {_position_identifier(best_signal) or 'unknown'} on {exchange} @ EV {best_signal.get('ev_score', 0):.2f} "
        f"({canonical_note})"
    )



def build_execution_plan(allowed_signal_timestamp: str | None = None, allow_new_entries: bool = True) -> dict:
    open_positions = load_open_positions()
    signals = load_latest_signals()
    planned_closes = evaluate_exit_trades(open_positions)
    refreshed_open_positions = [position for position in open_positions if position.get('trade_id') not in {trade.get('trade_id') for trade in planned_closes}]
    candidate_signal, entry_reason = select_trade_candidate(
        signals=signals,
        open_positions=refreshed_open_positions,
        allowed_signal_timestamp=allowed_signal_timestamp,
        allow_new_entries=allow_new_entries,
    )
    planned_entry = None
    if candidate_signal is not None:
        planned_entry = PaperTrader(candidate_signal).execute()
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
    persisted = 0
    for trade in trades:
        log_trade(trade)
        persisted += 1
    return persisted



def main() -> None:
    print("=" * 80)
    print("PHASE 1 PAPER TRADER")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"Trading Mode: {TRADING_MODE}")
    print("=" * 80)
    print()

    plan = build_execution_plan()
    open_positions = plan['open_positions']
    signals = plan['signals']

    print("[STATS] Status:")
    print(f"   Open positions: {len(open_positions)}/{MAX_OPEN_POSITIONS}")
    print(f"   Latest signals: {len(signals)}")
    print()

    if open_positions:
        print("[SCAN] Checking exits...")
        for trade in plan['planned_closes']:
            print(
                f"  [RED] Closed [{trade.get('exchange')}] {trade.get('symbol')}: {trade['exit_reason']} | "
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
    performance = calculate_performance()
    if performance.get('total_trades', 0) > 0:
        print("[STATS] Performance:")
        print(f"   Total trades: {performance['total_trades']}")
        print(f"   Win rate: {performance['win_rate']:.1f}%")
        print(f"   Total P&L: ${performance['total_pnl_usd']:+.2f}")
        for exchange, breakdown in sorted(performance.get('exchange_breakdown', {}).items()):
            print(f"   - {exchange}: {breakdown['total_trades']} closed trades, ${breakdown['total_pnl_usd']:+.2f}")

    print()
    print("[OK] Paper trader complete")


if __name__ == "__main__":
    main()
