"""Canonical paper account state derived from append-only paper trade history."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from models.trade_schema import normalize_trade_record, validate_trade_record, is_trade_closed
from utils.json_utils import safe_read_json, safe_read_jsonl, write_json_atomic

DEFAULT_STARTING_BALANCE_USD = 97.80
SCHEMA_VERSION = 1


def default_account_state(starting_balance_usd: float = DEFAULT_STARTING_BALANCE_USD) -> dict:
    return {
        'schema_version': SCHEMA_VERSION,
        'starting_balance_usd': round(float(starting_balance_usd), 8),
        'balance_usd': round(float(starting_balance_usd), 8),
        'peak_balance_usd': round(float(starting_balance_usd), 8),
        'realized_pnl_usd': 0.0,
        'closed_trades_count': 0,
        'last_trade_timestamp': None,
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'accounting_source': 'canonical_trade_history',
    }


def account_state_from_trade_history(trades_path: Path, starting_balance_usd: float = DEFAULT_STARTING_BALANCE_USD) -> dict:
    state = default_account_state(starting_balance_usd=starting_balance_usd)
    closed_trades = []
    for raw_trade in safe_read_jsonl(trades_path):
        trade = normalize_trade_record(raw_trade)
        if not validate_trade_record(trade, context='paper-account-history'):
            continue
        if is_trade_closed(trade):
            closed_trades.append(trade)

    closed_trades.sort(key=lambda trade: trade.get('exit_timestamp') or trade.get('entry_timestamp') or '')

    balance = state['starting_balance_usd']
    peak = state['starting_balance_usd']
    realized = 0.0
    last_trade_timestamp = None

    for trade in closed_trades:
        pnl = float(trade.get('realized_pnl_usd') or 0.0)
        realized += pnl
        balance += pnl
        peak = max(peak, balance)
        last_trade_timestamp = trade.get('exit_timestamp') or trade.get('entry_timestamp')

    state.update(
        {
            'balance_usd': round(balance, 8),
            'peak_balance_usd': round(peak, 8),
            'realized_pnl_usd': round(realized, 8),
            'closed_trades_count': len(closed_trades),
            'last_trade_timestamp': last_trade_timestamp,
            'updated_at': datetime.now(timezone.utc).isoformat(),
        }
    )
    return state


def synchronize_paper_account_state(account_path: Path, trades_path: Path, starting_balance_usd: float = DEFAULT_STARTING_BALANCE_USD) -> dict:
    computed = account_state_from_trade_history(trades_path, starting_balance_usd=starting_balance_usd)

    current = safe_read_json(account_path)
    if not isinstance(current, dict):
        current = {}

    needs_write = any(
        current.get(key) != computed.get(key)
        for key in (
            'schema_version',
            'starting_balance_usd',
            'balance_usd',
            'peak_balance_usd',
            'realized_pnl_usd',
            'closed_trades_count',
            'last_trade_timestamp',
            'accounting_source',
        )
    )

    if needs_write or not account_path.exists():
        write_json_atomic(account_path, computed)
        return computed

    current['updated_at'] = datetime.now(timezone.utc).isoformat()
    write_json_atomic(account_path, current)
    return current
