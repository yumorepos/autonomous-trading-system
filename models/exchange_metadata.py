from __future__ import annotations

SUPPORTED_PAPER_EXCHANGES = ("Hyperliquid", "Polymarket")
DEFAULT_PAPER_EXCHANGE = "Hyperliquid"
PRIMARY_MIXED_MODE_EXCHANGE = "Hyperliquid"
MIXED_MODE_MAX_NEW_ENTRIES_PER_CYCLE = 1
MIXED_MODE_SECONDARY_HEALTH_IS_ADVISORY = True

EXCHANGE_RUNTIME_METADATA = {
    "Hyperliquid": {
        "paper_status": "canonical",
        "experimental": False,
        "entry_priority": 0,
        "take_profit_pct": 10.0,
        "stop_loss_pct": -10.0,
        "timeout_hours": 24.0,
    },
    "Polymarket": {
        "paper_status": "canonical",
        "experimental": True,
        "entry_priority": 1,
        "take_profit_pct": 8.0,
        "stop_loss_pct": -8.0,
        "timeout_hours": 24.0,
    },
}

MIXED_MODE_POLICY = {
    "primary_exchange": PRIMARY_MIXED_MODE_EXCHANGE,
    "max_new_entries_per_cycle": MIXED_MODE_MAX_NEW_ENTRIES_PER_CYCLE,
    "secondary_health_is_advisory": MIXED_MODE_SECONDARY_HEALTH_IS_ADVISORY,
}


def paper_exchange_thresholds(exchange: str | None) -> dict[str, float]:
    return dict(EXCHANGE_RUNTIME_METADATA.get(exchange or DEFAULT_PAPER_EXCHANGE, EXCHANGE_RUNTIME_METADATA[DEFAULT_PAPER_EXCHANGE]))


def paper_exchange_priority(exchange: str | None) -> int:
    return int(EXCHANGE_RUNTIME_METADATA.get(exchange or DEFAULT_PAPER_EXCHANGE, EXCHANGE_RUNTIME_METADATA[DEFAULT_PAPER_EXCHANGE])["entry_priority"])


def paper_exchange_status(exchange: str | None) -> str:
    return str(EXCHANGE_RUNTIME_METADATA.get(exchange or DEFAULT_PAPER_EXCHANGE, EXCHANGE_RUNTIME_METADATA[DEFAULT_PAPER_EXCHANGE])["paper_status"])


def paper_exchange_is_experimental(exchange: str | None) -> bool:
    return bool(EXCHANGE_RUNTIME_METADATA.get(exchange or DEFAULT_PAPER_EXCHANGE, EXCHANGE_RUNTIME_METADATA[DEFAULT_PAPER_EXCHANGE])["experimental"])


def mixed_mode_policy() -> dict[str, str | int | bool]:
    return dict(MIXED_MODE_POLICY)


def mixed_mode_primary_exchange() -> str:
    return str(MIXED_MODE_POLICY["primary_exchange"])


def mixed_mode_max_new_entries_per_cycle() -> int:
    return int(MIXED_MODE_POLICY["max_new_entries_per_cycle"])


def mixed_mode_secondary_health_is_advisory() -> bool:
    return bool(MIXED_MODE_POLICY["secondary_health_is_advisory"])


def mixed_mode_selection_note(exchange: str | None) -> str:
    if exchange == mixed_mode_primary_exchange():
        return "current deterministic mixed-mode priority winner"
    return "mixed-mode eligible but lower priority than the primary exchange"
