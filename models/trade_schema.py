from __future__ import annotations

from copy import deepcopy
from typing import Any
import warnings

from models.exchange_metadata import SUPPORTED_PAPER_EXCHANGES

CANONICAL_CLOSED_TRADE_FIELDS = [
    "trade_id",
    "exchange",
    "symbol",
    "side",
    "entry_price",
    "exit_price",
    "position_size",
    "position_size_usd",
    "realized_pnl_usd",
    "realized_pnl_pct",
    "status",
    "exit_reason",
    "entry_timestamp",
    "exit_timestamp",
]

CANONICAL_OPEN_POSITION_FIELDS = [
    "trade_id",
    "exchange",
    "symbol",
    "side",
    "entry_price",
    "position_size",
    "position_size_usd",
    "status",
    "entry_timestamp",
]

_CANONICAL_FIELDS = {
    field: None for field in sorted(
        set(CANONICAL_CLOSED_TRADE_FIELDS + CANONICAL_OPEN_POSITION_FIELDS)
    )
}

_ALLOWED_STATUSES = {"OPEN", "CLOSED"}
_VALID_TRANSITIONS = {
    None: {"OPEN", "CLOSED"},
    "OPEN": {"OPEN", "CLOSED"},
    "CLOSED": {"CLOSED"},
}


def _warn(message: str) -> None:
    warnings.warn(message, stacklevel=2)


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _normalize_status(value: Any) -> Any:
    if isinstance(value, str):
        normalized = value.upper()
        if normalized in _ALLOWED_STATUSES:
            return normalized
    return value


def _infer_symbol(source: dict[str, Any], signal: dict[str, Any]) -> Any:
    return _coalesce(
        source.get("symbol"),
        source.get("asset"),
        signal.get("asset"),
        source.get("market"),
        source.get("market_id"),
    )


def _infer_side(source: dict[str, Any], signal: dict[str, Any]) -> Any:
    return _coalesce(
        source.get("side"),
        source.get("direction"),
        signal.get("direction"),
    )


def _infer_exchange(source: dict[str, Any], signal: dict[str, Any]) -> Any:
    return _coalesce(
        source.get("exchange"),
        source.get("source"),
        signal.get("exchange"),
        signal.get("source"),
    )


def _infer_strategy(source: dict[str, Any], signal: dict[str, Any]) -> Any:
    return _coalesce(
        source.get("strategy"),
        signal.get("strategy"),
        signal.get("signal_type"),
    )


def _infer_market_id(source: dict[str, Any], signal: dict[str, Any]) -> Any:
    return _coalesce(
        source.get("market_id"),
        source.get("asset") if _infer_exchange(source, signal) == "Polymarket" else None,
        signal.get("market_id"),
    )


def normalize_trade_record(record: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize legacy and canonical trade records to the canonical flat schema."""
    source = deepcopy(record or {})
    signal = source.get("signal") or {}
    status = _normalize_status(source.get("status"))

    entry_timestamp = _coalesce(
        source.get("entry_timestamp"),
        source.get("entry_time"),
        source.get("timestamp"),
        source.get("created_at"),
    )
    exit_timestamp = _coalesce(
        source.get("exit_timestamp"),
        source.get("exit_time"),
        source.get("closed_at"),
    )

    position_size = _coalesce(
        source.get("position_size"),
        source.get("quantity"),
        source.get("size"),
    )
    position_size_usd = _coalesce(
        source.get("position_size_usd"),
        source.get("entry_value"),
        source.get("notional_usd"),
        position_size,
    )

    normalized = deepcopy(_CANONICAL_FIELDS)
    normalized.update(
        {
            "trade_id": _coalesce(source.get("trade_id"), source.get("position_id"), source.get("id")),
            "exchange": _infer_exchange(source, signal),
            "strategy": _infer_strategy(source, signal),
            "symbol": _infer_symbol(source, signal),
            "side": _infer_side(source, signal),
            "entry_price": source.get("entry_price"),
            "exit_price": _coalesce(source.get("exit_price"), source.get("close_price")),
            "position_size": position_size,
            "position_size_usd": position_size_usd,
            "realized_pnl_usd": _coalesce(
                source.get("realized_pnl_usd"),
                source.get("pnl_usd"),
                source.get("pnl"),
            ),
            "realized_pnl_pct": _coalesce(
                source.get("realized_pnl_pct"),
                source.get("pnl_pct"),
                source.get("return_pct"),
            ),
            "status": status,
            "exit_reason": _coalesce(source.get("exit_reason"), source.get("close_reason"), source.get("reason")),
            "entry_timestamp": entry_timestamp,
            "exit_timestamp": exit_timestamp,
            "market_id": _infer_market_id(source, signal),
            "market_question": _coalesce(source.get("market_question"), signal.get("market_question")),
            "token_id": _coalesce(source.get("token_id"), signal.get("token_id")),
            "paper_only": _coalesce(source.get("paper_only"), signal.get("paper_only")),
            "experimental": _coalesce(source.get("experimental"), signal.get("experimental")),
        }
    )
    normalized["raw"] = source
    return normalized


def validate_trade_record(record: dict[str, Any] | None, context: str = "trade") -> bool:
    normalized = normalize_trade_record(record)
    status = normalized.get("status")

    if status not in _ALLOWED_STATUSES:
        _warn(f"{context}: invalid status {status!r}, skipping")
        return False

    required_fields = (
        CANONICAL_OPEN_POSITION_FIELDS
        if status == "OPEN"
        else CANONICAL_CLOSED_TRADE_FIELDS
    )
    missing = [field for field in required_fields if normalized.get(field) is None]
    if missing:
        _warn(f"{context}: missing required fields {missing}, skipping")
        return False

    if normalized.get("exchange") not in SUPPORTED_PAPER_EXCHANGES:
        _warn(f"{context}: unsupported exchange {normalized.get('exchange')!r}, skipping")
        return False

    if normalized.get("exchange") == "Polymarket" and normalized.get("market_id") is None:
        _warn(f"{context}: Polymarket record missing market_id, skipping")
        return False

    if status == "OPEN":
        if normalized.get("exit_price") is not None or normalized.get("exit_timestamp") is not None:
            _warn(f"{context}: OPEN record contains exit fields; using state cautiously")
    elif status == "CLOSED":
        if normalized.get("exit_price") is None or normalized.get("exit_timestamp") is None:
            _warn(f"{context}: CLOSED record missing exit details, skipping")
            return False

    return True


def warn_on_status_transition(previous_status: Any, new_status: Any, context: str = "trade") -> bool:
    previous = _normalize_status(previous_status)
    current = _normalize_status(new_status)
    allowed = _VALID_TRANSITIONS.get(previous, set())
    if current not in allowed:
        _warn(f"{context}: invalid status transition {previous!r} -> {current!r}")
        return False
    return True
