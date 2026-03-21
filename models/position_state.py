from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import warnings

from models.trade_schema import (
    CANONICAL_OPEN_POSITION_FIELDS,
    normalize_trade_record,
    validate_trade_record,
    warn_on_status_transition,
)
from utils.json_utils import safe_read_json, write_json_atomic


def _warn(message: str) -> None:
    warnings.warn(message, stacklevel=2)


EMPTY_POSITION_STATE = {
    "schema_version": "2.0",
    "updated_at": None,
    "positions": {},
}


def _canonical_open_position(record: dict[str, Any] | None, context: str) -> dict[str, Any] | None:
    source = dict(record or {})
    normalized = normalize_trade_record(source)
    if normalized.get("status") != "OPEN":
        _warn(f"{context}: non-open record cannot be stored in position-state.json")
        return None
    if not validate_trade_record(normalized, context=context):
        return None
    canonical = {field: normalized.get(field) for field in CANONICAL_OPEN_POSITION_FIELDS}
    canonical.update({
        'position_id': normalized.get('trade_id'),
        'direction': normalized.get('side'),
        'entry_time': normalized.get('entry_timestamp'),
    })
    for extra_field in [
        'signal',
        'exchange',
        'strategy',
        'stop_loss_pct',
        'take_profit_pct',
        'timeout_hours',
        'market_id',
        'market_question',
        'token_id',
        'paper_only',
        'experimental',
        'raw',
    ]:
        if source.get(extra_field) is not None:
            canonical[extra_field] = source.get(extra_field)
    canonical['status'] = 'OPEN'
    return canonical


def load_position_state(path: Path | str) -> dict[str, Any]:
    payload = safe_read_json(path)
    if not isinstance(payload, dict):
        return dict(EMPTY_POSITION_STATE)

    raw_positions: dict[str, Any] = {}
    if isinstance(payload.get("positions"), dict):
        raw_positions = payload.get("positions", {})
    elif payload and all(isinstance(value, dict) for value in payload.values()):
        raw_positions = payload
    elif payload and all(not isinstance(value, dict) for value in payload.values()):
        _warn("Legacy position-state.json status map detected; open positions unavailable until trader rewrites canonical state")

    positions: dict[str, dict[str, Any]] = {}
    for trade_id, position in raw_positions.items():
        canonical = _canonical_open_position(position, context=f"position-state[{trade_id}]")
        if canonical is None:
            continue
        canonical_trade_id = canonical.get("trade_id") or trade_id
        if canonical_trade_id != trade_id:
            _warn(f"position-state[{trade_id}]: inconsistent trade_id {canonical_trade_id!r}")
        positions[canonical_trade_id] = canonical

    return {
        "schema_version": payload.get("schema_version", "2.0"),
        "updated_at": payload.get("updated_at"),
        "positions": positions,
    }


def save_position_state(path: Path | str, positions: list[dict[str, Any]] | dict[str, dict[str, Any]]) -> dict[str, Any]:
    canonical_positions: dict[str, dict[str, Any]] = {}
    iterable = positions.values() if isinstance(positions, dict) else positions
    for index, position in enumerate(iterable):
        canonical = _canonical_open_position(position, context=f"position-state-write[{index}]")
        if canonical is None:
            continue
        canonical_positions[canonical["trade_id"]] = canonical

    state = {
        "schema_version": "2.0",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "positions": canonical_positions,
    }
    write_json_atomic(path, state)
    return state


def get_open_positions(path: Path | str) -> list[dict[str, Any]]:
    state = load_position_state(path)
    return list(state.get("positions", {}).values())


def apply_trade_to_position_state(path: Path | str, trade_record: dict[str, Any] | None) -> dict[str, Any]:
    state = load_position_state(path)
    positions = dict(state.get("positions", {}))
    normalized = normalize_trade_record(trade_record)
    trade_id = normalized.get("trade_id")

    if not trade_id:
        _warn("trade-state-update: missing trade_id, skipping state update")
        return state

    previous_status = positions.get(trade_id, {}).get("status") if trade_id in positions else None
    current_status = normalized.get("status")
    warn_on_status_transition(previous_status, current_status, context=f"position-state[{trade_id}]")

    if current_status == "OPEN":
        canonical = _canonical_open_position(trade_record, context=f"position-state[{trade_id}]")
        if canonical is not None:
            positions[trade_id] = canonical
    elif current_status == "CLOSED":
        if trade_id not in positions:
            _warn(f"position-state[{trade_id}]: close received for non-open position")
        positions.pop(trade_id, None)
    else:
        _warn(f"position-state[{trade_id}]: invalid status {current_status!r}, skipping update")

    return save_position_state(path, positions)
