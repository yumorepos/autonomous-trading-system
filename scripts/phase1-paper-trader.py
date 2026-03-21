#!/usr/bin/env python3
"""
Phase 1 paper trading engine.
Supports canonical Hyperliquid paper trades and optional/experimental Polymarket
paper trades while persisting both through the same canonical trade/state model.
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

EXIT_THRESHOLDS = {
    'Hyperliquid': {'take_profit_pct': 10.0, 'stop_loss_pct': -10.0, 'timeout_hours': 24.0},
    'Polymarket': {'take_profit_pct': 8.0, 'stop_loss_pct': -8.0, 'timeout_hours': 24.0},
}


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
    if exchange == 'Hyperliquid':
        if signal.get('signal_type') != 'funding_arbitrage':
            return False, f"signal_type={signal.get('signal_type')!r} is not canonical Hyperliquid funding_arbitrage"
        missing = [field for field in ('asset', 'direction', 'entry_price') if signal.get(field) is None]
        if missing:
            return False, f"missing required Hyperliquid fields: {missing}"
        return True, 'canonical Hyperliquid signal'

    if exchange == 'Polymarket':
        if signal.get('signal_type') != 'polymarket_binary_market':
            return False, f"signal_type={signal.get('signal_type')!r} is not canonical Polymarket paper signal"
        missing = [field for field in ('market_id', 'market_question', 'side', 'entry_price') if signal.get(field) is None]
        if missing:
            return False, f"missing required Polymarket fields: {missing}"
        return True, 'canonical Polymarket paper signal'

    return False, f"unsupported exchange={exchange!r}"



def _position_identifier(signal_or_position: dict) -> str | None:
    exchange = signal_or_position.get('exchange', signal_or_position.get('source'))
    if exchange == 'Polymarket':
        return signal_or_position.get('market_id') or signal_or_position.get('symbol')
    return signal_or_position.get('asset') or signal_or_position.get('symbol')


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
        if exchange == 'Polymarket':
            return self.execute_polymarket()
        return self.execute_hyperliquid()

    def execute_hyperliquid(self) -> dict:
        asset = self.signal['asset']
        direction = self.signal['direction']
        entry_price = float(self.signal['entry_price'])
        position_size_usd = float(self.signal.get('recommended_position_size_usd', PAPER_BALANCE * 0.02))
        position_size = position_size_usd / entry_price
        entry_timestamp = datetime.now(timezone.utc).isoformat()
        thresholds = EXIT_THRESHOLDS['Hyperliquid']
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
            'stop_loss_pct': thresholds['stop_loss_pct'],
            'take_profit_pct': thresholds['take_profit_pct'],
            'timeout_hours': thresholds['timeout_hours'],
            'paper_only': True,
        }
        print(f"  [OK] Hyperliquid paper trade: {direction} {position_size:.4f} {asset} @ ${entry_price:.4f}")
        append_runtime_event(
            stage='paper_trader',
            exchange='Hyperliquid',
            lifecycle_stage='entry_planned',
            status='INFO',
            message='Hyperliquid paper trade planned',
            metadata={'trade_id': self.position_id, 'symbol': asset, 'side': direction, 'entry_price': entry_price},
        )
        return trade

    def execute_polymarket(self) -> dict:
        market_id = self.signal['market_id']
        side = self.signal['side']
        entry_price = float(self.signal['entry_price'])
        position_size_usd = float(self.signal.get('recommended_position_size_usd', 5.0))
        quantity = position_size_usd / entry_price
        entry_timestamp = datetime.now(timezone.utc).isoformat()
        thresholds = EXIT_THRESHOLDS['Polymarket']
        trade = {
            'trade_id': self.position_id,
            'position_id': self.position_id,
            'timestamp': entry_timestamp,
            'entry_timestamp': entry_timestamp,
            'entry_time': entry_timestamp,
            'signal': self.signal,
            'exchange': 'Polymarket',
            'strategy': 'polymarket_spread',
            'symbol': market_id,
            'asset': market_id,
            'market_id': market_id,
            'market_question': self.signal['market_question'],
            'token_id': self.signal.get('token_id'),
            'side': side,
            'direction': side,
            'entry_price': entry_price,
            'position_size': quantity,
            'position_size_usd': position_size_usd,
            'status': 'OPEN',
            'stop_loss_pct': thresholds['stop_loss_pct'],
            'take_profit_pct': thresholds['take_profit_pct'],
            'timeout_hours': thresholds['timeout_hours'],
            'paper_only': True,
            'experimental': True,
        }
        print(f"  [OK] Polymarket paper trade: {side} {market_id} ({quantity:.4f} shares) @ ${entry_price:.4f}")
        append_runtime_event(
            stage='paper_trader',
            exchange='Polymarket',
            lifecycle_stage='entry_planned',
            status='INFO',
            message='Polymarket paper trade planned',
            metadata={'trade_id': self.position_id, 'market_id': market_id, 'side': side, 'entry_price': entry_price},
        )
        return trade



def get_current_price(asset: str) -> float:
    """Get current Hyperliquid price for the given asset."""
    try:
        r = requests.post("https://api.hyperliquid.xyz/info", json={'type': 'allMids'}, timeout=5)
        if r.status_code == 200:
            return float(r.json().get(asset, 0))
    except Exception:
        pass
    return 0



def get_polymarket_current_price(position: dict) -> float:
    market_id = position.get('market_id') or position.get('symbol')
    side = position.get('side', 'YES')
    token_id = position.get('token_id')
    if not market_id:
        return 0
    try:
        r = requests.get(
            "https://gamma-api.polymarket.com/markets",
            params={'condition_id': market_id},
            timeout=5,
        )
        r.raise_for_status()
        markets = r.json()
        if not markets:
            return 0
        market = markets[0]
        for token in market.get('tokens', []):
            outcome = str(token.get('outcome') or '').upper()
            candidate_token_id = str(token.get('token_id') or token.get('tokenId') or token.get('id') or '')
            if outcome == side or (token_id and token_id == candidate_token_id):
                return float(token.get('price') or token.get('bestAsk') or token.get('ask') or token.get('bestBid') or token.get('bid') or 0)
    except Exception:
        pass
    return 0



def get_position_current_price(position: dict) -> float:
    exchange = position.get('exchange') or position.get('signal', {}).get('exchange') or position.get('signal', {}).get('source')
    if exchange == 'Polymarket':
        return get_polymarket_current_price(position)
    return get_current_price(position['symbol'])



def calculate_pnl(entry_price: float, current_price: float, position_size: float, direction: str, exchange: str = 'Hyperliquid') -> tuple[float, float]:
    if exchange == 'Hyperliquid':
        if direction == 'LONG':
            pnl_usd = (current_price - entry_price) * position_size
            pnl_pct = ((current_price - entry_price) / entry_price) * 100
        else:
            pnl_usd = (entry_price - current_price) * position_size
            pnl_pct = ((entry_price - current_price) / entry_price) * 100
    else:
        pnl_usd = (current_price - entry_price) * position_size
        pnl_pct = ((current_price - entry_price) / entry_price) * 100 if entry_price else 0
    return pnl_usd, pnl_pct



def check_exit(position: dict) -> tuple[bool, str | None]:
    if 'symbol' not in position or 'entry_price' not in position or 'entry_timestamp' not in position:
        return False, None

    exchange = position.get('exchange', 'Hyperliquid')
    current_price = get_position_current_price(position)
    if not current_price:
        return False, None

    thresholds = EXIT_THRESHOLDS['Polymarket' if exchange == 'Polymarket' else 'Hyperliquid']
    direction = position.get('side', position.get('direction', 'LONG'))
    _, pnl_pct = calculate_pnl(position['entry_price'], current_price, position['position_size'], direction, exchange=exchange)

    if pnl_pct >= thresholds['take_profit_pct']:
        return True, 'take_profit'
    if pnl_pct <= thresholds['stop_loss_pct']:
        return True, 'stop_loss'

    age_hours = (datetime.now(timezone.utc) - datetime.fromisoformat(position['entry_timestamp'])).total_seconds() / 3600
    if age_hours >= thresholds['timeout_hours']:
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
        exchange = trade.get('exchange', 'Unknown')
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

    best_signal = max(good_signals, key=lambda signal: signal.get('ev_score', 0))
    return best_signal, f"Selected {_position_identifier(best_signal) or 'unknown'} on {best_signal.get('exchange')} @ EV {best_signal.get('ev_score', 0):.2f}"



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
