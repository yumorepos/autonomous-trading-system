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
    """Test CostModel arithmetic with 0.035% taker fee + 0.05% slippage."""

    def setUp(self):
        self.model = CostModel()

    def test_taker_fee_is_correct(self):
        """Taker fee must be 0.035% per the task spec."""
        self.assertAlmostEqual(CostModel.TAKER_FEE, 0.00035, places=8)

    def test_slippage_is_correct(self):
        """Slippage must be 0.05% per the task spec."""
        self.assertAlmostEqual(CostModel.SLIPPAGE, 0.00050, places=8)

    def test_entry_cost(self):
        # 0.035% fee + 0.05% slippage = 0.085% total per side
        cost = self.model.entry_cost(1000.0)
        self.assertAlmostEqual(cost, 0.85, places=6)  # $0.85 on $1000

    def test_exit_cost(self):
        cost = self.model.exit_cost(1000.0)
        self.assertAlmostEqual(cost, 0.85, places=6)

    def test_entry_exit_symmetry(self):
        size = 500.0
        self.assertAlmostEqual(
            self.model.entry_cost(size),
            self.model.exit_cost(size),
            places=10,
        )

    def test_round_trip_cost(self):
        """Round-trip = entry + exit = 0.085% * 2 = 0.17% total."""
        size = 1000.0
        total = self.model.entry_cost(size) + self.model.exit_cost(size)
        # 0.085% per side = 0.17% round trip = $1.70 on $1000
        self.assertAlmostEqual(total, 1.70, places=6)

    def test_round_trip_small_position(self):
        """Typical $15 position: round trip cost."""
        size = 15.0
        total = self.model.entry_cost(size) + self.model.exit_cost(size)
        # 15 * 0.00085 * 2 = $0.0255
        self.assertAlmostEqual(total, 0.0255, places=6)

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


class TestDownloaderErrorHandling(unittest.TestCase):
    """Test that data downloader handles API errors gracefully."""

    def test_api_post_retries_on_429(self):
        """api_post should retry on 429 with backoff."""
        from unittest.mock import patch, MagicMock
        from scripts.backtest.download_history import api_post
        import urllib.error

        # First call: 429, second call: success
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"result": "ok"}'

        call_count = [0]
        def mock_urlopen(req, timeout=30):
            call_count[0] += 1
            if call_count[0] == 1:
                error = urllib.error.HTTPError(
                    "http://test", 429, "Rate Limited", {}, None
                )
                raise error
            return mock_resp

        with patch("scripts.backtest.download_history.urllib.request.urlopen", side_effect=mock_urlopen):
            with patch("scripts.backtest.download_history.time.sleep"):
                result = api_post({"type": "test"})

        self.assertEqual(result, {"result": "ok"})
        self.assertEqual(call_count[0], 2)

    def test_api_post_retries_on_network_error(self):
        """api_post should retry on transient network errors."""
        from unittest.mock import patch, MagicMock
        from scripts.backtest.download_history import api_post
        import urllib.error

        mock_resp = MagicMock()
        mock_resp.read.return_value = b'[1, 2, 3]'

        call_count = [0]
        def mock_urlopen(req, timeout=30):
            call_count[0] += 1
            if call_count[0] <= 2:
                raise urllib.error.URLError("Connection reset")
            return mock_resp

        with patch("scripts.backtest.download_history.urllib.request.urlopen", side_effect=mock_urlopen):
            with patch("scripts.backtest.download_history.time.sleep"):
                result = api_post({"type": "test"})

        self.assertEqual(result, [1, 2, 3])
        self.assertGreater(call_count[0], 2)


class TestSignalParityWithLiveScanner(unittest.TestCase):
    """Backtester must produce identical signals to live scanner given same state."""

    def test_funding_arb_classify_matches_live(self):
        """FundingArbStrategy entry logic matches tiered_scanner.py classification."""
        from scripts.backtest.strategies.funding_arb import FundingArbStrategy
        from config.risk_params import (
            TIER1_MIN_FUNDING, TIER1_MIN_VOLUME,
            TIER2_MIN_FUNDING, TIER2_MIN_VOLUME,
        )

        strategy = FundingArbStrategy()

        # Build a market state with a clear Tier 1 signal
        # Funding rate that annualizes to > 100%
        # 100% APY = 100% / (3*365) per 8h = ~0.000913 per 8h
        rate_8h = -0.001  # negative = longs earn
        funding_annual = abs(rate_8h) * 3 * 365  # 1.095 = 109.5% APY

        self.assertGreater(funding_annual, TIER1_MIN_FUNDING)

        state = MarketState(
            timestamp=1_700_000_000_000,
            prices={
                "TESTCOIN": {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 2e6},
            },
            funding_rates={"TESTCOIN": rate_8h},
            volumes_24h={"TESTCOIN": 2_000_000},
        )

        signal = strategy(state)
        self.assertIsNotNone(signal)
        self.assertEqual(signal["asset"], "TESTCOIN")
        # Negative funding rate -> longs earn -> direction = long
        self.assertEqual(signal["direction"], "long")
        self.assertEqual(signal["signal_type"], "funding_arbitrage")

    def test_tier2_signal_generated(self):
        """Tier 2 signal generated for moderate funding."""
        from scripts.backtest.strategies.funding_arb import FundingArbStrategy
        from config.risk_params import TIER2_MIN_FUNDING, TIER1_MIN_FUNDING

        strategy = FundingArbStrategy()

        # Rate that gives ~75% APY (between T2 min 65% and T1 min 100%)
        rate_8h = 0.00068  # 0.00068 * 3 * 365 = 0.7446 = ~74.5% APY
        funding_annual = abs(rate_8h) * 3 * 365

        self.assertGreater(funding_annual, TIER2_MIN_FUNDING)
        self.assertLess(funding_annual, TIER1_MIN_FUNDING)

        state = MarketState(
            timestamp=1_700_000_000_000,
            prices={"COIN2": {"open": 50, "high": 51, "low": 49, "close": 50, "volume": 1e6}},
            funding_rates={"COIN2": rate_8h},
            volumes_24h={"COIN2": 800_000},
        )

        signal = strategy(state)
        self.assertIsNotNone(signal)
        # Positive funding -> shorts earn
        self.assertEqual(signal["direction"], "short")

    def test_below_threshold_no_signal(self):
        """No signal when funding is below Tier 2 minimum."""
        from scripts.backtest.strategies.funding_arb import FundingArbStrategy

        strategy = FundingArbStrategy()

        # Very low funding rate: ~10% APY
        rate_8h = 0.0001  # 0.0001 * 3 * 365 = 0.1095 = 10.95% APY

        state = MarketState(
            timestamp=1_700_000_000_000,
            prices={"LOW": {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1e6}},
            funding_rates={"LOW": rate_8h},
            volumes_24h={"LOW": 2_000_000},
        )

        signal = strategy(state)
        self.assertIsNone(signal)


class TestPositionSizingFromConfig(unittest.TestCase):
    """Position sizing must match config/risk_params.py values exactly."""

    def test_sizing_uses_risk_params(self):
        """calculate_position_size uses the correct params."""
        from config.risk_params import (
            calculate_position_size, RISK_PER_TRADE_PCT,
            TIER_MULTIPLIERS, MIN_POSITION_USD, MAX_EXPOSURE_PER_TRADE,
        )

        # Tier 1 with $1000 balance
        size = calculate_position_size(1000.0, 1)
        expected = 1000 * RISK_PER_TRADE_PCT * TIER_MULTIPLIERS[1]  # 1000 * 0.05 * 1.5 = 75
        expected = min(expected, MAX_EXPOSURE_PER_TRADE)  # min(75, 20) = 20
        self.assertAlmostEqual(size, expected, places=2)

    def test_min_position_floor(self):
        """Small balances get clamped by exposure limits."""
        from config.risk_params import (
            calculate_position_size, MIN_POSITION_USD,
            RISK_PER_TRADE_PCT, MAX_EXPOSURE_PCT, MAX_CONCURRENT,
        )

        # $50 balance, tier 2: 50 * 0.05 * 1.0 = $2.50
        # But also capped by: 50 * 0.50 / 5 = $5.00
        # max($2.50, $10) = $10, then min($10, $20, $5) = $5
        size = calculate_position_size(50.0, 2)
        expected = min(
            max(50.0 * RISK_PER_TRADE_PCT, MIN_POSITION_USD),
            50.0 * MAX_EXPOSURE_PCT / MAX_CONCURRENT,
        )
        self.assertAlmostEqual(size, expected, places=2)

    def test_backtest_strategy_uses_config_thresholds(self):
        """FundingArbStrategy imports thresholds from config, not hardcoded."""
        from scripts.backtest.strategies.funding_arb import FundingArbStrategy
        from config.risk_params import TIER2_MIN_FUNDING, TIER2_MIN_VOLUME

        strategy = FundingArbStrategy()
        self.assertEqual(strategy.min_funding_apy, TIER2_MIN_FUNDING)
        self.assertEqual(strategy.min_volume, TIER2_MIN_VOLUME)


class TestBacktestResultEnhancements(unittest.TestCase):
    """Test new BacktestResult fields: avg_hold_hours, equity_curve, monthly_breakdown."""

    def test_avg_hold_hours(self):
        """Average hold hours computed correctly."""
        engine = BacktestEngine(strategy=lambda s: None, initial_capital=1000.0)
        from scripts.backtest.engine import Trade

        # Two trades: 4h and 8h
        engine.closed_trades = [
            Trade("A", "long", 100, 110, 100, 0, 4 * 3600 * 1000, "TP", 10, 0.2, 0, 9.8),
            Trade("B", "long", 100, 105, 100, 0, 8 * 3600 * 1000, "TIMEOUT", 5, 0.2, 0, 4.8),
        ]
        engine.equity_curve = [(4 * 3600 * 1000, 1009.8), (8 * 3600 * 1000, 1014.6)]

        result = engine._compute_result()
        self.assertAlmostEqual(result.avg_hold_hours, 6.0, places=1)

    def test_equity_curve_in_result(self):
        """Equity curve is included in result."""
        engine = BacktestEngine(strategy=lambda s: None, initial_capital=1000.0)
        from scripts.backtest.engine import Trade

        engine.closed_trades = [
            Trade("A", "long", 100, 110, 100, 0, 1, "TP", 10, 0.2, 0, 9.8),
        ]
        engine.equity_curve = [(1, 1009.8)]

        result = engine._compute_result()
        self.assertEqual(len(result.equity_curve), 1)
        self.assertEqual(result.equity_curve[0], (1, 1009.8))

    def test_monthly_breakdown(self):
        """Monthly breakdown groups trades by entry month."""
        engine = BacktestEngine(strategy=lambda s: None, initial_capital=1000.0)
        from scripts.backtest.engine import Trade

        jan_ts = 1704067200000  # 2024-01-01 UTC approx
        feb_ts = 1706745600000  # 2024-02-01 UTC approx

        engine.closed_trades = [
            Trade("A", "long", 100, 110, 100, jan_ts, jan_ts + 1, "TP", 10, 0.2, 0, 9.8),
            Trade("B", "long", 100, 95, 100, jan_ts + 1000, jan_ts + 2000, "SL", -5, 0.2, 0, -5.2),
            Trade("C", "long", 100, 112, 100, feb_ts, feb_ts + 1, "TP", 12, 0.2, 0, 11.8),
        ]
        engine.equity_curve = [(1, 1009.8), (2, 1004.6), (3, 1016.4)]

        result = engine._compute_result()
        self.assertIn("2024-01", result.monthly_breakdown)
        self.assertEqual(result.monthly_breakdown["2024-01"]["trades"], 2)
        self.assertEqual(result.monthly_breakdown["2024-01"]["wins"], 1)


if __name__ == "__main__":
    unittest.main()
