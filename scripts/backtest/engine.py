#!/usr/bin/env python3
"""
Event-driven backtesting engine.

Iterates hourly timestamps. At each bar:
1. Check exits on open positions (stop-loss, take-profit, trailing, timeout)
2. Check for new entries from the strategy

Exit logic matches the live trading_engine.py exactly.

Usage:
    python scripts/backtest/engine.py --strategy funding_arb --days 90
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.risk_params import (
    STOP_LOSS_ROE,
    TAKE_PROFIT_ROE,
    TIMEOUT_HOURS,
    TRAILING_STOP_ACTIVATE,
    TRAILING_STOP_DISTANCE,
    BACKTEST_INITIAL_CAPITAL,
    calculate_position_size,
)
from scripts.backtest.cost_model import CostModel


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Trade:
    asset: str
    direction: str          # "long" or "short"
    entry_price: float
    exit_price: float
    size_usd: float
    entry_time: int         # epoch ms
    exit_time: int          # epoch ms
    exit_reason: str
    gross_pnl: float
    fees: float
    funding: float
    net_pnl: float


@dataclass
class OpenPosition:
    asset: str
    direction: str
    entry_price: float
    size_usd: float
    entry_time: int         # epoch ms
    peak_roe: float = 0.0


@dataclass
class BacktestResult:
    closed_trades: list[Trade]
    final_capital: float
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    gross_pnl: float
    net_pnl: float
    net_expectancy_per_trade: float
    max_drawdown_pct: float
    sharpe_ratio: float
    profit_factor: float


@dataclass
class MarketState:
    """Snapshot of market state at a single hourly timestamp."""
    timestamp: int                          # epoch ms
    prices: dict[str, dict]                 # asset -> {open, high, low, close, volume}
    funding_rates: dict[str, float]         # asset -> latest 8h funding rate
    volumes_24h: dict[str, float]           # asset -> rolling 24h volume estimate


# ---------------------------------------------------------------------------
# Backtest engine
# ---------------------------------------------------------------------------

class BacktestEngine:
    """Event-driven hourly backtester."""

    def __init__(
        self,
        strategy: Callable[[MarketState], dict | None],
        initial_capital: float = BACKTEST_INITIAL_CAPITAL,
        cost_model: CostModel | None = None,
        # Allow overriding risk params for sweep
        stop_loss_roe: float = STOP_LOSS_ROE,
        take_profit_roe: float = TAKE_PROFIT_ROE,
        timeout_hours: float = TIMEOUT_HOURS,
        trailing_activate: float = TRAILING_STOP_ACTIVATE,
        trailing_distance: float = TRAILING_STOP_DISTANCE,
    ):
        self.strategy = strategy
        self.capital = initial_capital
        self.initial_capital = initial_capital
        self.cost_model = cost_model or CostModel()

        # Risk params (may be overridden for sweep)
        self.stop_loss_roe = stop_loss_roe
        self.take_profit_roe = take_profit_roe
        self.timeout_hours = timeout_hours
        self.trailing_activate = trailing_activate
        self.trailing_distance = trailing_distance

        # State
        self.positions: dict[str, OpenPosition] = {}
        self.closed_trades: list[Trade] = []
        self.equity_curve: list[tuple[int, float]] = []  # (timestamp, capital)
        self.peak_capital = initial_capital

    def run(self, timestamps: list[int], market_data: dict[str, dict[int, dict]],
            funding_data: dict[str, dict[int, float]],
            volume_data: dict[str, float]) -> BacktestResult:
        """
        Run backtest over sorted hourly timestamps.

        Args:
            timestamps: sorted list of epoch_ms timestamps (hourly)
            market_data: {asset: {timestamp_ms: {open, high, low, close, volume}}}
            funding_data: {asset: {timestamp_ms: funding_rate_8h}}
            volume_data: {asset: estimated_24h_volume}
        """
        for ts in timestamps:
            # Build market state for this timestamp
            prices = {}
            funding_rates = {}
            for asset in market_data:
                if ts in market_data[asset]:
                    prices[asset] = market_data[asset][ts]
                # Find most recent funding rate at or before this timestamp
                if asset in funding_data:
                    best_fts = None
                    for fts in funding_data[asset]:
                        if fts <= ts:
                            if best_fts is None or fts > best_fts:
                                best_fts = fts
                    if best_fts is not None:
                        funding_rates[asset] = funding_data[asset][best_fts]

            state = MarketState(
                timestamp=ts,
                prices=prices,
                funding_rates=funding_rates,
                volumes_24h=volume_data,
            )

            # 1. Check exits on open positions
            self._check_exits(state)

            # 2. Check for new entries
            self._check_entries(state)

        # Force-close any remaining positions at last timestamp
        if timestamps:
            last_ts = timestamps[-1]
            last_state = MarketState(
                timestamp=last_ts,
                prices={a: market_data[a].get(last_ts, {}) for a in market_data},
                funding_rates={},
                volumes_24h=volume_data,
            )
            for asset in list(self.positions.keys()):
                pos = self.positions[asset]
                candle = last_state.prices.get(asset)
                if candle and candle.get("close"):
                    self._close_position(pos, candle["close"], last_ts, "END_OF_BACKTEST", 0.0)

        return self._compute_result()

    def _check_exits(self, state: MarketState) -> None:
        """Check all open positions for exit triggers."""
        for asset in list(self.positions.keys()):
            pos = self.positions[asset]
            candle = state.prices.get(asset)
            if not candle or not candle.get("close"):
                continue

            close_price = candle["close"]
            high_price = candle["high"]
            low_price = candle["low"]

            # Calculate ROE
            if pos.direction == "long":
                roe = (close_price - pos.entry_price) / pos.entry_price
                roe_high = (high_price - pos.entry_price) / pos.entry_price
                roe_low = (low_price - pos.entry_price) / pos.entry_price
            else:  # short
                roe = (pos.entry_price - close_price) / pos.entry_price
                roe_high = (pos.entry_price - low_price) / pos.entry_price  # best for short
                roe_low = (pos.entry_price - high_price) / pos.entry_price  # worst for short

            # Update peak ROE (using intra-bar high)
            pos.peak_roe = max(pos.peak_roe, roe_high)

            # Hours held
            hours_held = (state.timestamp - pos.entry_time) / (3600 * 1000)

            # Funding earned this hour
            funding_rate = state.funding_rates.get(asset, 0.0)
            if pos.direction == "short":
                # Short earns when rate is positive (longs pay shorts)
                hour_funding = self.cost_model.funding_earned(pos.size_usd, funding_rate, 1.0)
            else:
                # Long earns when rate is negative
                hour_funding = self.cost_model.funding_earned(pos.size_usd, -funding_rate, 1.0)

            # --- Exit checks (matching live engine priority) ---

            # 1. Stop-loss (check worst intra-bar ROE)
            if roe_low <= self.stop_loss_roe:
                # Exit at stop-loss level, not close price
                sl_price = self._roe_to_price(pos, self.stop_loss_roe)
                self._close_position(pos, sl_price, state.timestamp, "STOP_LOSS", hour_funding)
                continue

            # 2. Timeout
            if hours_held >= self.timeout_hours:
                self._close_position(pos, close_price, state.timestamp, "TIMEOUT", hour_funding)
                continue

            # 3. Take-profit (check best intra-bar ROE)
            if roe_high >= self.take_profit_roe:
                tp_price = self._roe_to_price(pos, self.take_profit_roe)
                self._close_position(pos, tp_price, state.timestamp, "TAKE_PROFIT", hour_funding)
                continue

            # 4. Trailing stop
            if pos.peak_roe >= self.trailing_activate:
                trail_threshold = pos.peak_roe - self.trailing_distance
                if roe_low <= trail_threshold:
                    trail_price = self._roe_to_price(pos, trail_threshold)
                    self._close_position(pos, trail_price, state.timestamp, "TRAILING_STOP", hour_funding)
                    continue

            # Position stays open — accrue funding to equity
            self.capital += hour_funding

    def _roe_to_price(self, pos: OpenPosition, target_roe: float) -> float:
        """Convert a target ROE back to a price level."""
        if pos.direction == "long":
            return pos.entry_price * (1 + target_roe)
        else:  # short
            return pos.entry_price * (1 - target_roe)

    def _close_position(self, pos: OpenPosition, exit_price: float, exit_time: int,
                        reason: str, last_hour_funding: float) -> None:
        """Close a position and record the trade."""
        # Gross PnL
        if pos.direction == "long":
            gross_pnl = (exit_price - pos.entry_price) / pos.entry_price * pos.size_usd
        else:
            gross_pnl = (pos.entry_price - exit_price) / pos.entry_price * pos.size_usd

        # Costs
        entry_cost = self.cost_model.entry_cost(pos.size_usd)
        exit_cost = self.cost_model.exit_cost(pos.size_usd)
        total_fees = entry_cost + exit_cost

        # Net PnL (funding was already accrued hourly except last hour)
        net_pnl = gross_pnl - total_fees + last_hour_funding

        trade = Trade(
            asset=pos.asset,
            direction=pos.direction,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            size_usd=pos.size_usd,
            entry_time=pos.entry_time,
            exit_time=exit_time,
            exit_reason=reason,
            gross_pnl=gross_pnl,
            fees=total_fees,
            funding=last_hour_funding,  # just last hour; rest accrued live
            net_pnl=net_pnl,
        )

        self.closed_trades.append(trade)
        self.capital += net_pnl
        self.equity_curve.append((exit_time, self.capital))

        # Track peak for drawdown
        if self.capital > self.peak_capital:
            self.peak_capital = self.capital

        del self.positions[pos.asset]

    def _check_entries(self, state: MarketState) -> None:
        """Ask strategy for signals and open new positions."""
        signal = self.strategy(state)
        if signal is None:
            return

        asset = signal.get("asset")
        if not asset or asset in self.positions:
            return

        candle = state.prices.get(asset)
        if not candle or not candle.get("close"):
            return

        size_usd = signal.get("position_size_usd", calculate_position_size(self.capital, 2))
        direction = signal.get("direction", "short")
        entry_price = candle["close"]

        # Deduct entry cost
        entry_cost = self.cost_model.entry_cost(size_usd)
        self.capital -= entry_cost

        self.positions[asset] = OpenPosition(
            asset=asset,
            direction=direction,
            entry_price=entry_price,
            size_usd=size_usd,
            entry_time=state.timestamp,
        )

    def _compute_result(self) -> BacktestResult:
        """Compute aggregate metrics from closed trades."""
        trades = self.closed_trades
        total = len(trades)

        if total == 0:
            return BacktestResult(
                closed_trades=[],
                final_capital=self.capital,
                total_trades=0,
                wins=0,
                losses=0,
                win_rate=0.0,
                gross_pnl=0.0,
                net_pnl=0.0,
                net_expectancy_per_trade=0.0,
                max_drawdown_pct=0.0,
                sharpe_ratio=0.0,
                profit_factor=0.0,
            )

        wins = sum(1 for t in trades if t.net_pnl > 0)
        losses = total - wins
        win_rate = wins / total if total > 0 else 0.0

        gross_pnl = sum(t.gross_pnl for t in trades)
        net_pnl = sum(t.net_pnl for t in trades)
        net_expectancy = net_pnl / total

        # Max drawdown from equity curve
        max_dd = self._max_drawdown()

        # Sharpe ratio (annualized, from per-trade returns)
        sharpe = self._sharpe_ratio()

        # Profit factor
        gross_wins = sum(t.net_pnl for t in trades if t.net_pnl > 0)
        gross_losses = abs(sum(t.net_pnl for t in trades if t.net_pnl <= 0))
        profit_factor = gross_wins / gross_losses if gross_losses > 0 else float("inf")

        return BacktestResult(
            closed_trades=trades,
            final_capital=self.capital,
            total_trades=total,
            wins=wins,
            losses=losses,
            win_rate=win_rate,
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            net_expectancy_per_trade=net_expectancy,
            max_drawdown_pct=max_dd,
            sharpe_ratio=sharpe,
            profit_factor=profit_factor,
        )

    def _max_drawdown(self) -> float:
        """Calculate max drawdown percentage from equity curve."""
        if not self.equity_curve:
            return 0.0

        peak = self.initial_capital
        max_dd = 0.0

        for _, equity in self.equity_curve:
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak if peak > 0 else 0.0
            max_dd = max(max_dd, dd)

        return max_dd

    def _sharpe_ratio(self) -> float:
        """Annualized Sharpe ratio from per-trade net PnL."""
        if len(self.closed_trades) < 2:
            return 0.0

        returns = [t.net_pnl for t in self.closed_trades]
        avg = sum(returns) / len(returns)
        var = sum((r - avg) ** 2 for r in returns) / (len(returns) - 1)
        std = math.sqrt(var) if var > 0 else 0.0

        if std == 0:
            return 0.0

        # Assume ~3 trades/day average, annualize
        trades_per_year = 3 * 365
        return (avg / std) * math.sqrt(trades_per_year)

    def _profit_factor(self) -> float:
        """Ratio of gross wins to gross losses."""
        wins = sum(t.net_pnl for t in self.closed_trades if t.net_pnl > 0)
        losses = abs(sum(t.net_pnl for t in self.closed_trades if t.net_pnl <= 0))
        return wins / losses if losses > 0 else float("inf")


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_candles(data_dir: Path, days: int | None = None) -> tuple[dict, list[int]]:
    """
    Load candle CSVs.

    Returns:
        market_data: {asset: {timestamp_ms: {open, high, low, close, volume}}}
        timestamps: sorted list of unique hourly timestamps
    """
    candle_dir = data_dir / "candles"
    if not candle_dir.exists():
        print(f"No candle data found at {candle_dir}")
        return {}, []

    market_data: dict[str, dict[int, dict]] = {}
    all_timestamps: set[int] = set()

    cutoff_ms = None
    if days:
        import time as _time
        now_ms = int(_time.time() * 1000)
        cutoff_ms = now_ms - (days * 24 * 3600 * 1000)

    for csv_file in sorted(candle_dir.glob("*_1h.csv")):
        asset = csv_file.stem.replace("_1h", "")
        asset_data: dict[int, dict] = {}

        with open(csv_file) as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts = int(row["timestamp"])
                if cutoff_ms and ts < cutoff_ms:
                    continue
                asset_data[ts] = {
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                }
                all_timestamps.add(ts)

        if asset_data:
            market_data[asset] = asset_data

    timestamps = sorted(all_timestamps)
    return market_data, timestamps


def load_funding(data_dir: Path, days: int | None = None) -> dict[str, dict[int, float]]:
    """
    Load funding rate CSV.

    Returns:
        {asset: {timestamp_ms: funding_rate_8h}}
    """
    funding_file = data_dir / "funding_rates.csv"
    if not funding_file.exists():
        print(f"No funding data found at {funding_file}")
        return {}

    cutoff_ms = None
    if days:
        import time as _time
        now_ms = int(_time.time() * 1000)
        cutoff_ms = now_ms - (days * 24 * 3600 * 1000)

    funding_data: dict[str, dict[int, float]] = {}

    with open(funding_file) as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = int(row["timestamp"])
            if cutoff_ms and ts < cutoff_ms:
                continue
            asset = row["asset"]
            rate = float(row["funding_rate_8h"])
            if asset not in funding_data:
                funding_data[asset] = {}
            funding_data[asset][ts] = rate

    return funding_data


def estimate_volumes(market_data: dict[str, dict[int, dict]]) -> dict[str, float]:
    """Estimate 24h volume per asset from candle data (sum last 24 1h candles)."""
    volumes: dict[str, float] = {}
    for asset, candles in market_data.items():
        sorted_ts = sorted(candles.keys())
        # Use last 24 candles as proxy
        recent = sorted_ts[-24:] if len(sorted_ts) >= 24 else sorted_ts
        vol = sum(candles[ts]["volume"] for ts in recent)
        volumes[asset] = vol
    return volumes


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Run backtest")
    parser.add_argument("--strategy", default="funding_arb", help="Strategy name")
    parser.add_argument("--days", type=int, default=90, help="Days to backtest")
    parser.add_argument("--capital", type=float, default=BACKTEST_INITIAL_CAPITAL)
    args = parser.parse_args()

    data_dir = REPO_ROOT / "data" / "historical"

    print(f"Loading data from {data_dir}...")
    market_data, timestamps = load_candles(data_dir, args.days)
    funding_data = load_funding(data_dir, args.days)
    volume_data = estimate_volumes(market_data)

    if not timestamps:
        print("No data found. Run scripts/data/download_hl_history.py first.")
        sys.exit(1)

    print(f"Loaded {len(market_data)} assets, {len(timestamps)} hourly bars")

    # Load strategy
    if args.strategy == "funding_arb":
        from scripts.backtest.strategies.funding_arb import FundingArbStrategy
        strategy_fn = FundingArbStrategy()
    elif args.strategy == "mean_reversion":
        from scripts.backtest.strategies.mean_reversion import MeanReversionStrategy
        strategy_fn = MeanReversionStrategy(market_data=market_data)
    else:
        print(f"Unknown strategy: {args.strategy}")
        sys.exit(1)

    engine = BacktestEngine(
        strategy=strategy_fn,
        initial_capital=args.capital,
    )

    print(f"Running backtest ({args.days} days, ${args.capital:.0f} capital)...")
    result = engine.run(timestamps, market_data, funding_data, volume_data)

    print(f"\n{'='*50}")
    print(f"BACKTEST RESULTS — {args.strategy}")
    print(f"{'='*50}")
    print(f"Total trades:    {result.total_trades}")
    print(f"Wins / Losses:   {result.wins} / {result.losses}")
    print(f"Win rate:        {result.win_rate:.1%}")
    print(f"Gross PnL:       ${result.gross_pnl:.2f}")
    print(f"Net PnL:         ${result.net_pnl:.2f}")
    print(f"Net expectancy:  ${result.net_expectancy_per_trade:.4f} / trade")
    print(f"Max drawdown:    {result.max_drawdown_pct:.2%}")
    print(f"Sharpe ratio:    {result.sharpe_ratio:.2f}")
    print(f"Profit factor:   {result.profit_factor:.2f}")
    print(f"Final capital:   ${result.final_capital:.2f}")


if __name__ == "__main__":
    main()
