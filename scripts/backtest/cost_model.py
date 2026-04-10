"""
Cost model for Hyperliquid backtesting.

Models taker fees, estimated slippage, and funding income/expense.
"""

from __future__ import annotations


class CostModel:
    """Hyperliquid fee and slippage model."""

    TAKER_FEE = 0.00035   # 0.035% (Hyperliquid taker fee)
    SLIPPAGE = 0.00050     # 0.05% estimated for small positions

    def entry_cost(self, size_usd: float) -> float:
        """Total cost to open a position (fees + slippage)."""
        return size_usd * (self.TAKER_FEE + self.SLIPPAGE)

    def exit_cost(self, size_usd: float) -> float:
        """Total cost to close a position (fees + slippage)."""
        return size_usd * (self.TAKER_FEE + self.SLIPPAGE)

    def funding_earned(self, size_usd: float, rate_8h: float, hours_held: float) -> float:
        """
        Net funding earned (positive = received, negative = paid).

        For a short position earning positive funding:
            rate_8h > 0 means longs pay shorts -> short earns
            We multiply by (hours_held / 8) to prorate the 8h rate.

        For a long position:
            rate_8h > 0 means longs pay -> long pays (negative)
            rate_8h < 0 means shorts pay longs -> long earns (positive)

        The caller is responsible for sign convention:
            short position: funding_earned(size, +rate, hours) -> positive (earning)
            long position:  funding_earned(size, -rate, hours) -> positive (earning)

        So the caller should pass: direction_sign * rate_8h
        where direction_sign = -1 for short (earns when rate positive),
                               +1 for long (earns when rate negative, which is already negative).

        Simplified: pass -rate_8h for shorts, +rate_8h for longs.
        Then negative result = paying funding, positive = earning.
        """
        periods = hours_held / 8.0
        return size_usd * rate_8h * periods
