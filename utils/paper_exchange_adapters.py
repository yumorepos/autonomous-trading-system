from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from models.exchange_metadata import paper_exchange_is_experimental
from models.paper_contracts import SIGNAL_CONTRACTS, SignalContract, paper_position_identifier as contract_position_identifier, validate_signal_contract


@dataclass(frozen=True)
class PaperExchangeAdapter:
    contract: SignalContract

    @property
    def exchange(self) -> str:
        return self.contract.exchange

    @property
    def strategy(self) -> str:
        return self.contract.strategy

    @property
    def signal_type(self) -> str:
        return self.contract.signal_type

    @property
    def required_signal_fields(self) -> tuple[str, ...]:
        return self.contract.required_signal_fields

    @property
    def default_position_size_usd(self) -> float:
        return self.contract.default_position_size_usd

    @property
    def take_profit_pct(self) -> float:
        return self.contract.take_profit_pct

    @property
    def stop_loss_pct(self) -> float:
        return self.contract.stop_loss_pct

    @property
    def timeout_hours(self) -> float:
        return self.contract.timeout_hours

    def validate_signal(self, signal: dict[str, Any] | None) -> tuple[bool, str]:
        passed, reason, _ = validate_signal_contract(signal, exchange=self.exchange)
        return passed, reason

    def build_trade(self, signal: dict[str, Any], position_id: str, entry_timestamp: str | None = None) -> dict[str, Any]:
        raise NotImplementedError

    def get_current_price(self, position: dict[str, Any], requests_module: Any) -> float:
        raise NotImplementedError

    def calculate_pnl(self, entry_price: float, current_price: float, position_size: float, direction: str) -> tuple[float, float]:
        raise NotImplementedError

    def fetch_health(self, requests_module: Any) -> None:
        raise NotImplementedError

    def fetch_liquidity(self, asset: str, requests_module: Any) -> float | None:
        raise NotImplementedError

    def fetch_spread(self, asset: str, direction: str, requests_module: Any) -> tuple[float | None, float | None]:
        raise NotImplementedError


@dataclass(frozen=True)
class HyperliquidPaperAdapter(PaperExchangeAdapter):
    def build_trade(self, signal: dict[str, Any], position_id: str, entry_timestamp: str | None = None) -> dict[str, Any]:
        entry_timestamp = entry_timestamp or datetime.now(timezone.utc).isoformat()
        entry_price = float(signal['entry_price'])
        position_size_usd = float(signal.get('recommended_position_size_usd', self.default_position_size_usd))
        position_size = position_size_usd / entry_price
        asset = signal['asset']
        direction = signal['direction']
        return {
            'trade_id': position_id,
            'position_id': position_id,
            'timestamp': entry_timestamp,
            'entry_timestamp': entry_timestamp,
            'entry_time': entry_timestamp,
            'signal': signal,
            'exchange': self.exchange,
            'strategy': self.strategy,
            'symbol': asset,
            'asset': asset,
            'side': direction,
            'direction': direction,
            'entry_price': entry_price,
            'position_size': position_size,
            'position_size_usd': position_size_usd,
            'status': 'OPEN',
            'stop_loss_pct': self.stop_loss_pct,
            'take_profit_pct': self.take_profit_pct,
            'timeout_hours': self.timeout_hours,
            'paper_only': True,
            'experimental': paper_exchange_is_experimental(self.exchange),
        }

    def get_current_price(self, position: dict[str, Any], requests_module: Any) -> float:
        response = requests_module.post("https://api.hyperliquid.xyz/info", json={'type': 'allMids'}, timeout=5)
        if response.status_code == 200:
            return float(response.json().get(position['symbol'], 0))
        return 0

    def calculate_pnl(self, entry_price: float, current_price: float, position_size: float, direction: str) -> tuple[float, float]:
        if direction == 'LONG':
            pnl_usd = (current_price - entry_price) * position_size
            pnl_pct = ((current_price - entry_price) / entry_price) * 100
        else:
            pnl_usd = (entry_price - current_price) * position_size
            pnl_pct = ((entry_price - current_price) / entry_price) * 100
        return pnl_usd, pnl_pct

    def fetch_health(self, requests_module: Any) -> None:
        response = requests_module.post(
            'https://api.hyperliquid.xyz/info',
            json={'type': 'metaAndAssetCtxs'},
            timeout=5,
        )
        response.raise_for_status()

    def fetch_liquidity(self, asset: str, requests_module: Any) -> float | None:
        response = requests_module.post(
            'https://api.hyperliquid.xyz/info',
            json={'type': 'metaAndAssetCtxs'},
            timeout=5,
        )
        response.raise_for_status()
        data = response.json()
        markets = data[1] if isinstance(data, list) and len(data) > 1 else []
        for market in markets:
            coin = market.get('coin') or market.get('symbol') or market.get('name')
            if not coin:
                continue
            if str(coin).upper() == str(asset).upper():
                return float(market.get('dayNtlVlm', 0))
        return None

    def fetch_spread(self, asset: str, direction: str, requests_module: Any) -> tuple[float | None, float | None]:
        response = requests_module.post(
            'https://api.hyperliquid.xyz/info',
            json={'type': 'l2Book', 'coin': asset},
            timeout=5,
        )
        response.raise_for_status()
        book = response.json()
        if not book.get('levels') or len(book['levels']) < 2:
            return None, None
        return float(book['levels'][0][0]['px']), float(book['levels'][1][0]['px'])


PAPER_EXCHANGE_ADAPTERS: dict[str, PaperExchangeAdapter] = {
    'Hyperliquid': HyperliquidPaperAdapter(contract=SIGNAL_CONTRACTS['Hyperliquid']),
}


def get_paper_exchange_adapter(exchange: str | None) -> PaperExchangeAdapter | None:
    if not exchange:
        return None
    return PAPER_EXCHANGE_ADAPTERS.get(exchange)


def paper_position_identifier(record: dict[str, Any]) -> str | None:
    return contract_position_identifier(record)
