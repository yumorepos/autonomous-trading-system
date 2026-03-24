from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import warnings

from models.paper_contracts import canonical_position_state_record
from models.trade_schema import (
    normalize_trade_record,
    validate_trade_record,
    warn_on_status_transition,
)
from utils.json_utils import safe_read_json, safe_read_jsonl, write_json_atomic
from utils.runtime_logging import append_runtime_event


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
    return canonical_position_state_record(normalized, source=source)


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


def _expected_open_positions_from_trade_history_records(records: list[Any]) -> dict[str, dict[str, Any]]:
    positions: dict[str, dict[str, Any]] = {}
    for index, trade_record in enumerate(records):
        normalized = normalize_trade_record(trade_record)
        if not validate_trade_record(normalized, context=f"position-state-trade-history[{index}]"):
            continue

        trade_id = normalized.get("trade_id")
        if not trade_id:
            _warn(f"position-state-trade-history[{index}]: missing trade_id, skipping")
            continue

        if normalized.get("status") == "OPEN":
            canonical = _canonical_open_position(trade_record, context=f"position-state-trade-history[{trade_id}]")
            if canonical is not None:
                positions[trade_id] = canonical
        elif normalized.get("status") == "CLOSED":
            positions.pop(trade_id, None)

    return positions


def expected_open_positions_from_trade_history(trade_history_path: Path | str) -> dict[str, dict[str, Any]]:
    return _expected_open_positions_from_trade_history_records(safe_read_jsonl(trade_history_path))


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


def synchronize_position_state(path: Path | str, trade_history_path: Path | str) -> dict[str, Any]:
    file_path = Path(path)
    raw_payload = safe_read_json(file_path)
    current_state = load_position_state(file_path)
    trade_history_records = safe_read_jsonl(trade_history_path)
    expected_positions = _expected_open_positions_from_trade_history_records(trade_history_records)

    repair_reasons: list[str] = []
    if not file_path.exists():
        repair_reasons.append("missing_position_state")
    elif raw_payload is None:
        repair_reasons.append("malformed_or_unreadable_position_state")
    elif not isinstance(raw_payload, dict):
        repair_reasons.append("non_dict_position_state")

    if current_state.get("schema_version") != "2.0":
        repair_reasons.append("schema_version_mismatch")

    current_positions = current_state.get("positions", {})
    if not trade_history_records and current_positions:
        return current_state
    if current_positions != expected_positions:
        repair_reasons.append("trade_history_replay_mismatch")

    if not repair_reasons:
        current_state["repair_reasons"] = []
        return current_state

    repaired_state = save_position_state(file_path, expected_positions)
    append_runtime_event(
        stage="position_state",
        exchange="system",
        lifecycle_stage="state_recovered",
        status="WARN",
        message="Canonical position state synchronized from append-only trade history",
        metadata={
            "repair_reasons": repair_reasons,
            "expected_open_positions": len(expected_positions),
            "previous_open_positions": len(current_positions),
        },
    )
    repaired_state["repair_reasons"] = repair_reasons
    return repaired_state


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
            append_runtime_event(
                stage="position_state",
                exchange=canonical.get("exchange", "unknown"),
                lifecycle_stage="position_open",
                status="INFO",
                message="Canonical paper-trading position opened/updated",
                metadata={"trade_id": trade_id, "symbol": canonical.get("symbol"), "status": canonical.get("status")},
            )
    elif current_status == "CLOSED":
        if trade_id not in positions:
            _warn(f"position-state[{trade_id}]: close received for non-open position")
        positions.pop(trade_id, None)
        append_runtime_event(
            stage="position_state",
            exchange=(trade_record or {}).get("exchange", "unknown"),
            lifecycle_stage="position_closed",
            status="INFO",
            message="Canonical paper-trading position removed from open state",
            metadata={"trade_id": trade_id, "symbol": normalized.get("symbol"), "status": current_status},
        )
    else:
        _warn(f"position-state[{trade_id}]: invalid status {current_status!r}, skipping update")

    return save_position_state(path, positions)
