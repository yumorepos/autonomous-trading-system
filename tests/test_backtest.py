#!/usr/bin/env python3
"""
Tests for backtest infrastructure.

Covers:
- CostModel arithmetic
- BacktestEngine with a mock strategy
- BacktestResult metric calculations
- Edge case: zero trades
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import unittest

from scripts.backtest.cost_model import CostModel
from scripts.backtest.engine import BacktestEngine, BacktestResult, MarketState


class TestCostModel(unittest.TestCase):
    """Test CostModel arithmetic."""

    def setUp(self):
        self.model = CostModel()

    def test_entry_cost(self):
        # 0.05% fee + 0.05% slippage = 0.10% total
        cost = self.model.entry_cost(1000.0)
        self.assertAlmostEqual(cost, 1.0, places=6)  # $1 on $1000

    def test_exit_cost(self):
        cost = self.model.exit_cost(1000.0)
        self.assertAlmostEqual(cost, 1.0, places=6)

    def test_entry_exit_symmetry(self):
        size = 500.0
        self.assertAlmostEqual(
            self.model.entry_cost(size),
            self.model.exit_cost(size),
            places=10,
        )

    def test_funding_earned_positive(self):
        # $1000 position, 0.01% per 8h rate, held for 8 hours = 1 period
        earned = self.model.funding_earned(1000.0, 0.0001, 8.0)
        self.assertAlmostEqual(earned, 0.10, places=6)

    def test_funding_earned_partial_period(self):
        # 4 hours = 0.5 periods
        earned = self.model.funding_earned(1000.0, 0.0001, 4.0)
        self.assertAlmostEqual(earned, 0.05, places=6)

    def test_funding_earned_negative(self):
        # Negative rate = paying funding
        earned = self.model.funding_earned(1000.0, -0.0001, 8.0)
        self.assertAlmostEqual(earned, -0.10, places=6)

    def test_funding_zero_hours(self):
        earned = self.model.funding_earned(1000.0, 0.0001, 0.0)
        self.assertAlmostEqual(earned, 0.0, places=10)

    def test_round_trip_cost(self):
        size = 15.0  # typical position
        total = self.model.entry_cost(size) + self.model.exit_cost(size)
        # 0.1% per side = 0.2% round trip = $0.03 on $15
        self.assertAlmostEqual(total, 0.03, places=6)


class TestBacktestEngineWithMockStrategy(unittest.TestCase):
    """Test BacktestEngine with a simple always-buy-then-exit-at-1% strategy."""

    def _make_candles(self, prices: list[float]) -> tuple[dict, list[int]]:
        """Create candle data from a list of close prices."""
        base_ts = 1_700_000_000_000  # some epoch ms
        market_data = {"TEST": {}}
        timestamps = []

        for i, p in enumerate(prices):
            ts = base_ts + i * 3600_000  # hourly
            timestamps.append(ts)
            market_data["TEST"][ts] = {
                "open": p,
                "high": p * 1.005,  # 0.5% range
                "low": p * 0.995,
                "close": p,
                "volume": 1_000_000,
            }

        return market_data, timestamps

    def test_simple_long_profit(self):
        """Buy at 100, price rises 1% per bar, should take profit."""
        prices = [100.0 + i * 1.0 for i in range(20)]  # 100, 101, ..., 119
        market_data, timestamps = self._make_candles(prices)
        funding_data = {}
        volume_data = {"TEST": 1_000_000}

        # Strategy: always buy TEST on first bar
        entered = [False]
        def mock_strategy(state: MarketState) -> dict | None:
            if not entered[0] and "TEST" in state.prices:
                entered[0] = True
                return {
                    "asset": "TEST",
                    "direction": "long",
                    "position_size_usd": 100.0,
                }
            return None

        engine = BacktestEngine(
            strategy=mock_strategy,
            initial_capital=1000.0,
            take_profit_roe=0.10,  # 10%
            stop_loss_roe=-0.07,
        )

        result = engine.run(timestamps, market_data, funding_data, volume_data)

        self.assertEqual(result.total_trades, 1)
        self.assertEqual(result.wins, 1)
        self.assertEqual(result.losses, 0)
        self.assertGreater(result.net_pnl, 0)
        # Entry at bar 0 close=100. Default timeout=8h fires at bar 8 (close=108)
        # before TP at 10% can be reached. Gross = (108-100)/100 * $100 = $8.
        self.assertAlmostEqual(result.closed_trades[0].gross_pnl, 8.0, places=1)
        self.assertEqual(result.closed_trades[0].exit_reason, "TIMEOUT")

    def test_simple_long_loss(self):
        """Buy at 100, price drops, should stop out."""
        prices = [100.0 - i * 1.5 for i in range(20)]  # 100, 98.5, 97, ...
        market_data, timestamps = self._make_candles(prices)
        funding_data = {}
        volume_data = {"TEST": 1_000_000}

        entered = [False]
        def mock_strategy(state: MarketState) -> dict | None:
            if not entered[0] and "TEST" in state.prices:
                entered[0] = True
                return {"asset": "TEST", "direction": "long", "position_size_usd": 100.0}
            return None

        engine = BacktestEngine(
            strategy=mock_strategy,
            initial_capital=1000.0,
            stop_loss_roe=-0.07,
        )

        result = engine.run(timestamps, market_data, funding_data, volume_data)

        self.assertEqual(result.total_trades, 1)
        self.assertEqual(result.losses, 1)
        self.assertLess(result.net_pnl, 0)
        self.assertEqual(result.closed_trades[0].exit_reason, "STOP_LOSS")

    def test_timeout_exit(self):
        """Price stays flat, should timeout."""
        prices = [100.0] * 20
        market_data, timestamps = self._make_candles(prices)
        funding_data = {}
        volume_data = {"TEST": 1_000_000}

        entered = [False]
        def mock_strategy(state: MarketState) -> dict | None:
            if not entered[0] and "TEST" in state.prices:
                entered[0] = True
                return {"asset": "TEST", "direction": "long", "position_size_usd": 100.0}
            return None

        engine = BacktestEngine(
            strategy=mock_strategy,
            initial_capital=1000.0,
            timeout_hours=8,
        )

        result = engine.run(timestamps, market_data, funding_data, volume_data)

        self.assertEqual(result.total_trades, 1)
        self.assertEqual(result.closed_trades[0].exit_reason, "TIMEOUT")

    def test_short_position(self):
        """Short at 100, price drops to 93, should take profit."""
        prices = [100.0 - i * 1.0 for i in range(20)]  # 100, 99, 98, ...
        market_data, timestamps = self._make_candles(prices)
        funding_data = {}
        volume_data = {"TEST": 1_000_000}

        entered = [False]
        def mock_strategy(state: MarketState) -> dict | None:
            if not entered[0] and "TEST" in state.prices:
                entered[0] = True
                return {"asset": "TEST", "direction": "short", "position_size_usd": 100.0}
            return None

        engine = BacktestEngine(
            strategy=mock_strategy,
            initial_capital=1000.0,
            take_profit_roe=0.05,  # 5% for short
            stop_loss_roe=-0.10,
        )

        result = engine.run(timestamps, market_data, funding_data, volume_data)

        self.assertEqual(result.total_trades, 1)
        self.assertEqual(result.wins, 1)
        self.assertEqual(result.closed_trades[0].exit_reason, "TAKE_PROFIT")
        self.assertGreater(result.closed_trades[0].gross_pnl, 0)


class TestBacktestResultMetrics(unittest.TestCase):
    """Test metric calculations."""

    def test_win_rate_calculation(self):
        """Win rate = wins / total."""
        market_data = {"A": {}}
        timestamps = []

        # Use engine to compute result with known trades
        engine = BacktestEngine(
            strategy=lambda s: None,
            initial_capital=1000.0,
        )

        # Manually inject trades
        from scripts.backtest.engine import Trade

        engine.closed_trades = [
            Trade("A", "long", 100, 110, 100, 0, 1, "TP", 10, 0.2, 0, 9.8),
            Trade("B", "long", 100, 95, 100, 0, 1, "SL", -5, 0.2, 0, -5.2),
            Trade("C", "long", 100, 112, 100, 0, 1, "TP", 12, 0.2, 0, 11.8),
        ]
        engine.equity_curve = [
            (1, 1009.8),
            (2, 1004.6),
            (3, 1016.4),
        ]

        result = engine._compute_result()

        self.assertEqual(result.total_trades, 3)
        self.assertEqual(result.wins, 2)
        self.assertEqual(result.losses, 1)
        self.assertAlmostEqual(result.win_rate, 2 / 3, places=6)

    def test_profit_factor(self):
        """Profit factor = gross wins / gross losses."""
        engine = BacktestEngine(strategy=lambda s: None, initial_capital=1000.0)
        from scripts.backtest.engine import Trade

        engine.closed_trades = [
            Trade("A", "long", 100, 110, 100, 0, 1, "TP", 10, 0.2, 0, 9.8),
            Trade("B", "long", 100, 95, 100, 0, 1, "SL", -5, 0.2, 0, -5.2),
        ]
        engine.equity_curve = [(1, 1009.8), (2, 1004.6)]

        result = engine._compute_result()

        # PF = 9.8 / 5.2 = ~1.884
        self.assertAlmostEqual(result.profit_factor, 9.8 / 5.2, places=2)

    def test_max_drawdown(self):
        """Max drawdown from equity curve."""
        engine = BacktestEngine(strategy=lambda s: None, initial_capital=1000.0)

        engine.equity_curve = [
            (1, 1010.0),   # peak
            (2, 990.0),    # drawdown: (1010-990)/1010 = ~1.98%
            (3, 1005.0),   # recovery
            (4, 980.0),    # drawdown from 1010: (1010-980)/1010 = ~2.97%
        ]

        dd = engine._max_drawdown()
        self.assertAlmostEqual(dd, (1010 - 980) / 1010, places=4)

    def test_net_expectancy(self):
        """Net expectancy = net_pnl / total_trades."""
        engine = BacktestEngine(strategy=lambda s: None, initial_capital=1000.0)
        from scripts.backtest.engine import Trade

        engine.closed_trades = [
            Trade("A", "long", 100, 110, 100, 0, 1, "TP", 10, 0.2, 0, 9.8),
            Trade("B", "long", 100, 95, 100, 0, 1, "SL", -5, 0.2, 0, -5.2),
        ]
        engine.equity_curve = [(1, 1009.8), (2, 1004.6)]

        result = engine._compute_result()

        expected_exp = (9.8 + (-5.2)) / 2  # 2.3
        self.assertAlmostEqual(result.net_expectancy_per_trade, expected_exp, places=4)


class TestZeroTrades(unittest.TestCase):
    """Edge case: zero trades should produce valid result."""

    def test_no_trades(self):
        """Strategy that never signals should produce valid empty result."""
        engine = BacktestEngine(
            strategy=lambda s: None,
            initial_capital=1000.0,
        )

        # Minimal data
        market_data = {
            "BTC": {
                1_700_000_000_000: {"open": 50000, "high": 50100, "low": 49900, "close": 50000, "volume": 1e6},
            }
        }
        timestamps = [1_700_000_000_000]

        result = engine.run(timestamps, market_data, {}, {"BTC": 1e6})

        self.assertEqual(result.total_trades, 0)
        self.assertEqual(result.wins, 0)
        self.assertEqual(result.losses, 0)
        self.assertEqual(result.win_rate, 0.0)
        self.assertEqual(result.gross_pnl, 0.0)
        self.assertEqual(result.net_pnl, 0.0)
        self.assertEqual(result.net_expectancy_per_trade, 0.0)
        self.assertEqual(result.max_drawdown_pct, 0.0)
        self.assertEqual(result.sharpe_ratio, 0.0)
        self.assertEqual(result.profit_factor, 0.0)
        self.assertEqual(result.final_capital, 1000.0)

    def test_no_data(self):
        """Empty data should produce valid result."""
        engine = BacktestEngine(
            strategy=lambda s: None,
            initial_capital=500.0,
        )

        result = engine.run([], {}, {}, {})

        self.assertEqual(result.total_trades, 0)
        self.assertEqual(result.final_capital, 500.0)


class TestTrailingStop(unittest.TestCase):
    """Test trailing stop logic."""

    def test_trailing_stop_triggers(self):
        """Price rises above activate, then falls back — should trail."""
        # Price: 100, 103, 105, 103, 101 — trailing should activate at +2%, trail 2% behind peak
        prices = [100.0, 103.0, 105.0, 103.0, 101.0, 99.0, 97.0]
        base_ts = 1_700_000_000_000

        market_data = {"TEST": {}}
        timestamps = []
        for i, p in enumerate(prices):
            ts = base_ts + i * 3600_000
            timestamps.append(ts)
            market_data["TEST"][ts] = {
                "open": p, "high": p + 0.5, "low": p - 0.5, "close": p, "volume": 1e6,
            }

        entered = [False]
        def mock_strategy(state):
            if not entered[0] and "TEST" in state.prices:
                entered[0] = True
                return {"asset": "TEST", "direction": "long", "position_size_usd": 100.0}
            return None

        engine = BacktestEngine(
            strategy=mock_strategy,
            initial_capital=1000.0,
            trailing_activate=0.02,   # +2%
            trailing_distance=0.02,   # trail 2% behind peak
            take_profit_roe=0.20,     # high TP so it doesn't trigger
            stop_loss_roe=-0.15,      # wide SL
            timeout_hours=100,
        )

        result = engine.run(timestamps, market_data, {}, {"TEST": 1e6})

        self.assertEqual(result.total_trades, 1)
        self.assertEqual(result.closed_trades[0].exit_reason, "TRAILING_STOP")


if __name__ == "__main__":
    unittest.main()
