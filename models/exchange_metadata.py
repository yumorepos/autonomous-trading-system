from __future__ import annotations

SUPPORTED_PAPER_EXCHANGES = ("Hyperliquid", "Polymarket")
DEFAULT_PAPER_EXCHANGE = "Hyperliquid"
PRIMARY_MIXED_MODE_EXCHANGE = "Hyperliquid"

EXCHANGE_RUNTIME_METADATA = {
    "Hyperliquid": {
        "paper_status": "canonical",
        "entry_priority": 0,
        "take_profit_pct": 10.0,
        "stop_loss_pct": -10.0,
        "timeout_hours": 24.0,
    },
    "Polymarket": {
        "paper_status": "canonical",
        "entry_priority": 1,
        "take_profit_pct": 8.0,
        "stop_loss_pct": -8.0,
        "timeout_hours": 24.0,
    },
}


def paper_exchange_thresholds(exchange: str | None) -> dict[str, float]:
    return dict(EXCHANGE_RUNTIME_METADATA.get(exchange or DEFAULT_PAPER_EXCHANGE, EXCHANGE_RUNTIME_METADATA[DEFAULT_PAPER_EXCHANGE]))


def paper_exchange_priority(exchange: str | None) -> int:
    return int(EXCHANGE_RUNTIME_METADATA.get(exchange or DEFAULT_PAPER_EXCHANGE, EXCHANGE_RUNTIME_METADATA[DEFAULT_PAPER_EXCHANGE])["entry_priority"])


def paper_exchange_status(exchange: str | None) -> str:
    return str(EXCHANGE_RUNTIME_METADATA.get(exchange or DEFAULT_PAPER_EXCHANGE, EXCHANGE_RUNTIME_METADATA[DEFAULT_PAPER_EXCHANGE])["paper_status"])
