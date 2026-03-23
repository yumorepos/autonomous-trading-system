from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from models.exchange_metadata import paper_exchange_is_experimental


@dataclass(frozen=True)
class PaperExchangeAdapter:
    exchange: str
    strategy: str
    signal_type: str
    required_signal_fields: tuple[str, ...]
    default_position_size_usd: float
    take_profit_pct: float
    stop_loss_pct: float
    timeout_hours: float

    def validate_signal(self, signal: dict[str, Any] | None) -> tuple[bool, str]:
        if not isinstance(signal, dict):
            return False, "signal payload is not a dict"
        if signal.get('signal_type') != self.signal_type:
            return False, f"signal_type={signal.get('signal_type')!r} is not canonical for {self.exchange}"
        missing = [field for field in self.required_signal_fields if signal.get(field) is None]
        if missing:
            return False, f"missing required {self.exchange} fields: {missing}"
        return True, f'canonical {self.exchange} signal'

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
        for market in data[1]:
            if market['coin'] == asset:
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


@dataclass(frozen=True)
class PolymarketPaperAdapter(PaperExchangeAdapter):
    def build_trade(self, signal: dict[str, Any], position_id: str, entry_timestamp: str | None = None) -> dict[str, Any]:
        entry_timestamp = entry_timestamp or datetime.now(timezone.utc).isoformat()
        entry_price = float(signal['entry_price'])
        position_size_usd = float(signal.get('recommended_position_size_usd', self.default_position_size_usd))
        quantity = position_size_usd / entry_price
        market_id = signal['market_id']
        side = signal['side']
        return {
            'trade_id': position_id,
            'position_id': position_id,
            'timestamp': entry_timestamp,
            'entry_timestamp': entry_timestamp,
            'entry_time': entry_timestamp,
            'signal': signal,
            'exchange': self.exchange,
            'strategy': self.strategy,
            'symbol': market_id,
            'asset': market_id,
            'market_id': market_id,
            'market_question': signal['market_question'],
            'token_id': signal.get('token_id'),
            'side': side,
            'direction': side,
            'entry_price': entry_price,
            'position_size': quantity,
            'position_size_usd': position_size_usd,
            'status': 'OPEN',
            'stop_loss_pct': self.stop_loss_pct,
            'take_profit_pct': self.take_profit_pct,
            'timeout_hours': self.timeout_hours,
            'paper_only': True,
            'experimental': paper_exchange_is_experimental(self.exchange),
        }

    def get_current_price(self, position: dict[str, Any], requests_module: Any) -> float:
        market_id = position.get('market_id') or position.get('symbol')
        side = position.get('side', 'YES')
        token_id = position.get('token_id')
        response = requests_module.get(
            "https://gamma-api.polymarket.com/markets",
            params={'condition_id': market_id},
            timeout=5,
        )
        response.raise_for_status()
        markets = response.json()
        if not markets:
            return 0
        market = markets[0]
        for token in market.get('tokens', []):
            outcome = str(token.get('outcome') or '').upper()
            candidate_token_id = str(token.get('token_id') or token.get('tokenId') or token.get('id') or '')
            if outcome == side or (token_id and token_id == candidate_token_id):
                return float(token.get('price') or token.get('bestAsk') or token.get('ask') or token.get('bestBid') or token.get('bid') or 0)
        return 0

    def calculate_pnl(self, entry_price: float, current_price: float, position_size: float, direction: str) -> tuple[float, float]:
        pnl_usd = (current_price - entry_price) * position_size
        pnl_pct = ((current_price - entry_price) / entry_price) * 100 if entry_price else 0
        return pnl_usd, pnl_pct

    def fetch_health(self, requests_module: Any) -> None:
        response = requests_module.get(
            'https://gamma-api.polymarket.com/markets',
            params={'limit': 5, 'closed': 'false'},
            timeout=5,
        )
        response.raise_for_status()

    def fetch_liquidity(self, asset: str, requests_module: Any) -> float | None:
        response = requests_module.get(
            'https://gamma-api.polymarket.com/markets',
            params={'condition_id': asset},
            timeout=5,
        )
        response.raise_for_status()
        markets = response.json()
        if not markets:
            return None
        market = markets[0]
        return float(market.get('liquidity') or market.get('liquidityNum') or market.get('volume') or 0)

    def fetch_spread(self, asset: str, direction: str, requests_module: Any) -> tuple[float | None, float | None]:
        response = requests_module.get(
            'https://gamma-api.polymarket.com/markets',
            params={'condition_id': asset},
            timeout=5,
        )
        response.raise_for_status()
        markets = response.json()
        if not markets:
            return None, None
        market = markets[0]
        selected_token = None
        for token in market.get('tokens', []):
            if str(token.get('outcome') or '').upper() == str(direction).upper():
                selected_token = token
                break
        if selected_token is None:
            selected_token = (market.get('tokens') or [{}])[0]
        best_bid = float(selected_token.get('bestBid') or selected_token.get('bid') or selected_token.get('price') or 0)
        best_ask = float(selected_token.get('bestAsk') or selected_token.get('ask') or selected_token.get('price') or 0)
        if best_bid <= 0 or best_ask <= 0:
            return None, None
        return best_bid, best_ask


PAPER_EXCHANGE_ADAPTERS: dict[str, PaperExchangeAdapter] = {
    'Hyperliquid': HyperliquidPaperAdapter(
        exchange='Hyperliquid',
        strategy='funding_arbitrage',
        signal_type='funding_arbitrage',
        required_signal_fields=('asset', 'direction', 'entry_price'),
        default_position_size_usd=1.96,
        take_profit_pct=10.0,
        stop_loss_pct=-10.0,
        timeout_hours=24.0,
    ),
    'Polymarket': PolymarketPaperAdapter(
        exchange='Polymarket',
        strategy='polymarket_spread',
        signal_type='polymarket_binary_market',
        required_signal_fields=('market_id', 'market_question', 'side', 'entry_price'),
        default_position_size_usd=5.0,
        take_profit_pct=8.0,
        stop_loss_pct=-8.0,
        timeout_hours=24.0,
    ),
}


def get_paper_exchange_adapter(exchange: str | None) -> PaperExchangeAdapter | None:
    if not exchange:
        return None
    return PAPER_EXCHANGE_ADAPTERS.get(exchange)


def paper_position_identifier(record: dict[str, Any]) -> str | None:
    exchange = record.get('exchange', record.get('source'))
    if exchange == 'Polymarket':
        return record.get('market_id') or record.get('symbol')
    return record.get('asset') or record.get('symbol')
