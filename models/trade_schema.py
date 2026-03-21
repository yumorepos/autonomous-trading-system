from __future__ import annotations

from copy import deepcopy
from typing import Any

_CANONICAL_FIELDS = {
    "trade_id": None,
    "symbol": None,
    "side": None,
    "entry_price": None,
    "exit_price": None,
    "position_size": None,
    "position_size_usd": None,
    "realized_pnl_usd": None,
    "realized_pnl_pct": None,
    "status": None,
    "exit_reason": None,
    "timestamps": {
        "created_at": None,
        "entry_time": None,
        "exit_time": None,
        "updated_at": None,
    },
}


def normalize_trade_record(record: dict[str, Any] | None) -> dict[str, Any]:
    source = deepcopy(record or {})
    signal = source.get("signal") or {}
    timestamps = {
        "created_at": source.get("timestamp") or source.get("created_at") or source.get("entry_time"),
        "entry_time": source.get("entry_time") or source.get("timestamp"),
        "exit_time": source.get("exit_time"),
        "updated_at": source.get("updated_at") or source.get("exit_time") or source.get("timestamp"),
    }

    normalized = deepcopy(_CANONICAL_FIELDS)
    normalized.update({
        "trade_id": source.get("trade_id") or source.get("position_id"),
        "symbol": source.get("symbol") or source.get("asset") or signal.get("asset") or source.get("market") or source.get("market_id"),
        "side": source.get("side") or source.get("direction") or signal.get("direction"),
        "entry_price": source.get("entry_price"),
        "exit_price": source.get("exit_price"),
        "position_size": source.get("position_size") or source.get("quantity") or source.get("size"),
        "position_size_usd": source.get("position_size_usd") or source.get("position_size") or source.get("entry_value"),
        "realized_pnl_usd": source.get("realized_pnl_usd", source.get("pnl")),
        "realized_pnl_pct": source.get("realized_pnl_pct", source.get("pnl_pct")),
        "status": source.get("status"),
        "exit_reason": source.get("exit_reason") or source.get("close_reason"),
        "timestamps": timestamps,
    })
    normalized["raw"] = source
    return normalized
