from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SignalContract:
    exchange: str
    strategy: str
    signal_type: str
    required_signal_fields: tuple[str, ...]
    position_identifier_fields: tuple[str, ...]
    default_position_size_usd: float
    take_profit_pct: float
    stop_loss_pct: float
    timeout_hours: float


HYPERLIQUID_SIGNAL_CONTRACT = SignalContract(
    exchange='Hyperliquid',
    strategy='funding_arbitrage',
    signal_type='funding_arbitrage',
    required_signal_fields=('asset', 'direction', 'entry_price'),
    position_identifier_fields=('asset', 'symbol'),
    default_position_size_usd=1.96,
    take_profit_pct=2.0,
    stop_loss_pct=-2.0,
    timeout_hours=1.5,
)

POLYMARKET_SIGNAL_CONTRACT = SignalContract(
    exchange='Polymarket',
    strategy='polymarket_spread',
    signal_type='polymarket_binary_market',
    required_signal_fields=('market_id', 'market_question', 'side', 'entry_price'),
    position_identifier_fields=('market_id', 'symbol', 'asset'),
    default_position_size_usd=5.0,
    take_profit_pct=2.0,
    stop_loss_pct=-2.0,
    timeout_hours=1.5,
)

SIGNAL_CONTRACTS: dict[str, SignalContract] = {
    contract.exchange: contract
    for contract in (HYPERLIQUID_SIGNAL_CONTRACT, POLYMARKET_SIGNAL_CONTRACT)
}

CANONICAL_CLOSED_TRADE_FIELDS = (
    'trade_id',
    'exchange',
    'symbol',
    'side',
    'entry_price',
    'exit_price',
    'position_size',
    'position_size_usd',
    'realized_pnl_usd',
    'realized_pnl_pct',
    'status',
    'exit_reason',
    'entry_timestamp',
    'exit_timestamp',
)

CANONICAL_OPEN_POSITION_FIELDS = (
    'trade_id',
    'exchange',
    'symbol',
    'side',
    'entry_price',
    'position_size',
    'position_size_usd',
    'status',
    'entry_timestamp',
)

CANONICAL_TRADE_OPTIONAL_FIELDS = (
    'strategy',
    'market_id',
    'market_question',
    'token_id',
    'paper_only',
    'experimental',
)

POSITION_STATE_PASSTHROUGH_FIELDS = (
    'signal',
    'stop_loss_pct',
    'take_profit_pct',
    'timeout_hours',
    'raw',
)

POSITION_STATE_ALIAS_FIELDS = {
    'position_id': 'trade_id',
    'direction': 'side',
    'entry_time': 'entry_timestamp',
}

EXCHANGE_TRADE_REQUIRED_FIELDS: dict[str, dict[str, tuple[str, ...]]] = {
    'Hyperliquid': {
        'OPEN': (),
        'CLOSED': (),
    },
    'Polymarket': {
        'OPEN': ('market_id',),
        'CLOSED': ('market_id',),
    },
}


def canonical_trade_required_fields(status: str | None, exchange: str | None = None) -> tuple[str, ...]:
    normalized_status = str(status or '').upper()
    if normalized_status == 'OPEN':
        base_fields = CANONICAL_OPEN_POSITION_FIELDS
    elif normalized_status == 'CLOSED':
        base_fields = CANONICAL_CLOSED_TRADE_FIELDS
    else:
        return ()

    exchange_fields = EXCHANGE_TRADE_REQUIRED_FIELDS.get(exchange or '', {}).get(normalized_status, ())
    return tuple(base_fields) + tuple(field for field in exchange_fields if field not in base_fields)


def canonical_trade_optional_fields() -> tuple[str, ...]:
    return CANONICAL_TRADE_OPTIONAL_FIELDS


def get_signal_contract(exchange: str | None) -> SignalContract | None:
    if not exchange:
        return None
    return SIGNAL_CONTRACTS.get(exchange)


def validate_signal_contract(signal: dict[str, Any] | None, exchange: str | None = None) -> tuple[bool, str, SignalContract | None]:
    if not isinstance(signal, dict):
        return False, 'signal payload is not a dict', None

    resolved_exchange = exchange or signal.get('exchange') or signal.get('source')
    contract = get_signal_contract(resolved_exchange)
    if contract is None:
        return False, f'unsupported exchange={resolved_exchange!r}', None

    if signal.get('signal_type') != contract.signal_type:
        return False, f"signal_type={signal.get('signal_type')!r} is not canonical for {contract.exchange}", contract

    missing = [field for field in contract.required_signal_fields if signal.get(field) is None]
    if missing:
        return False, f'missing required {contract.exchange} fields: {missing}', contract

    return True, f'canonical {contract.exchange} signal', contract


def paper_position_identifier(record: dict[str, Any] | None, exchange: str | None = None) -> str | None:
    payload = record or {}
    resolved_exchange = exchange or payload.get('exchange') or payload.get('source')
    contract = get_signal_contract(resolved_exchange)
    if contract is not None:
        for field in contract.position_identifier_fields:
            value = payload.get(field)
            if value is not None:
                return value
    return payload.get('asset') or payload.get('symbol') or payload.get('market_id')


def canonical_position_state_record(normalized: dict[str, Any], source: dict[str, Any] | None = None) -> dict[str, Any]:
    source = dict(source or {})
    canonical = {field: normalized.get(field) for field in CANONICAL_OPEN_POSITION_FIELDS}

    for alias, source_field in POSITION_STATE_ALIAS_FIELDS.items():
        canonical[alias] = normalized.get(source_field)

    for field in CANONICAL_TRADE_OPTIONAL_FIELDS:
        if normalized.get(field) is not None:
            canonical[field] = normalized.get(field)

    for field in POSITION_STATE_PASSTHROUGH_FIELDS:
        if source.get(field) is not None:
            canonical[field] = source.get(field)

    canonical['status'] = 'OPEN'
    return canonical


def is_trade_status(record: dict[str, Any] | None, status: str) -> bool:
    return str((record or {}).get('status') or '').upper() == status.upper()
