"""
PaperTrader — Simulates delta-neutral funding rate positions.

Tracks simulated positions, accumulates funding payments, applies fees/slippage,
and produces performance statistics. No real orders are placed.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from src.config import get_config
from src.models import (
    PaperTradeStats,
    RegimeTier,
    ScoredSignal,
    SimulatedPosition,
)

logger = logging.getLogger(__name__)


class PaperTrader:
    """Paper trading simulator for delta-neutral funding rate arbitrage."""

    def __init__(
        self,
        notional_per_trade: float = 1000.0,
        max_open_positions: int = 5,
        entry_fee_bps: float = 4.0,
        exit_fee_bps: float = 4.0,
        slippage_bps: float = 2.0,
        log_path: str | Path | None = None,
    ):
        self.notional_per_trade = notional_per_trade
        self.max_open_positions = max_open_positions
        self.entry_fee_bps = entry_fee_bps
        self.exit_fee_bps = exit_fee_bps
        self.slippage_bps = slippage_bps

        cfg = get_config()
        self.log_path = Path(log_path or cfg.get("simulator", {}).get(
            "log_path", "data/paper_trades.jsonl"
        ))
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

        self.positions: list[SimulatedPosition] = []
        self.closed_positions: list[SimulatedPosition] = []

    @property
    def open_positions(self) -> list[SimulatedPosition]:
        return [p for p in self.positions if p.is_open]

    @property
    def all_positions(self) -> list[SimulatedPosition]:
        return self.positions + self.closed_positions

    def _compute_entry_fees(self, notional: float) -> float:
        """Compute total entry cost (fee + slippage) in USD."""
        fee = notional * self.entry_fee_bps / 10_000
        slippage = notional * self.slippage_bps / 10_000
        return fee + slippage

    def _compute_exit_fees(self, notional: float) -> float:
        """Compute total exit cost (fee + slippage) in USD."""
        fee = notional * self.exit_fee_bps / 10_000
        slippage = notional * self.slippage_bps / 10_000
        return fee + slippage

    def _log_trade(self, action: str, position: SimulatedPosition):
        """Append trade event to JSONL log."""
        record = {
            "action": action,
            "position_id": position.position_id,
            "asset": position.asset,
            "exchange": position.exchange,
            "notional_usd": position.notional_usd,
            "entry_funding_apy": position.entry_funding_apy,
            "accumulated_funding_usd": position.accumulated_funding_usd,
            "accumulated_fees_usd": position.accumulated_fees_usd,
            "funding_payments": position.funding_payments,
            "net_pnl_usd": position.net_pnl_usd,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if position.exit_reason:
            record["exit_reason"] = position.exit_reason

        try:
            with open(self.log_path, "a") as f:
                f.write(json.dumps(record) + "\n")
        except OSError as e:
            logger.warning("Failed to log trade: %s", e)

    def open_position(self, signal: ScoredSignal) -> SimulatedPosition | None:
        """Open a new paper position based on an actionable signal.

        Returns the SimulatedPosition or None if at capacity.
        """
        if len(self.open_positions) >= self.max_open_positions:
            logger.info(
                "At max open positions (%d), skipping %s",
                self.max_open_positions, signal.event.asset,
            )
            return None

        # Check for duplicate — don't open same asset+exchange twice
        for p in self.open_positions:
            if p.asset == signal.event.asset and p.exchange == signal.event.exchange:
                logger.info(
                    "Already have open position for %s on %s, skipping",
                    signal.event.asset, signal.event.exchange,
                )
                return None

        entry_fees = self._compute_entry_fees(self.notional_per_trade)

        position = SimulatedPosition(
            position_id=str(uuid.uuid4())[:8],
            asset=signal.event.asset,
            exchange=signal.event.exchange,
            entry_time_utc=signal.event.timestamp_utc,
            entry_regime=signal.event.new_regime,
            notional_usd=self.notional_per_trade,
            entry_funding_apy=signal.net_expected_apy,
            accumulated_fees_usd=entry_fees,
        )

        self.positions.append(position)
        self._log_trade("OPEN", position)

        logger.info(
            "PAPER OPEN: %s on %s — $%.0f notional, %.1f%% APY, fees=$%.2f",
            position.asset, position.exchange, position.notional_usd,
            position.entry_funding_apy, entry_fees,
        )

        return position

    def close_position(
        self,
        position: SimulatedPosition,
        reason: str = "regime_change",
    ) -> SimulatedPosition:
        """Close an open paper position."""
        if not position.is_open:
            return position

        exit_fees = self._compute_exit_fees(position.notional_usd)
        position.accumulated_fees_usd += exit_fees
        position.exit_time_utc = datetime.now(timezone.utc)
        position.exit_reason = reason
        position.pnl_usd = position.net_pnl_usd
        position.is_open = False

        # Move to closed list
        if position in self.positions:
            self.positions.remove(position)
        self.closed_positions.append(position)

        self._log_trade("CLOSE", position)

        logger.info(
            "PAPER CLOSE: %s on %s — PnL=$%.2f, reason=%s",
            position.asset, position.exchange, position.pnl_usd, reason,
        )

        return position

    def close_positions_for_asset(
        self,
        asset: str,
        exchange: str | None = None,
        reason: str = "regime_change",
    ) -> list[SimulatedPosition]:
        """Close all open positions for an asset (optionally filtered by exchange)."""
        to_close = [
            p for p in self.open_positions
            if p.asset == asset and (exchange is None or p.exchange == exchange)
        ]
        return [self.close_position(p, reason) for p in to_close]

    def accrue_funding(
        self,
        asset: str,
        exchange: str,
        funding_rate_annualized: float,
        interval_hours: float = 8.0,
    ):
        """Accrue a funding payment to all matching open positions.

        funding_rate_annualized: APY as percentage (e.g. 150.0 = 150%)
        interval_hours: funding interval in hours (8 for CEX, 1 for Hyperliquid)
        """
        intervals_per_year = (365 * 24) / interval_hours
        per_interval_rate = funding_rate_annualized / 100 / intervals_per_year

        for p in self.open_positions:
            if p.asset == asset and p.exchange == exchange:
                payment = p.notional_usd * per_interval_rate
                p.accumulated_funding_usd += payment
                p.funding_payments += 1
                logger.debug(
                    "Funding accrual: %s +$%.4f (total $%.2f, %d payments)",
                    p.asset, payment, p.accumulated_funding_usd, p.funding_payments,
                )

    def get_stats(self) -> PaperTradeStats:
        """Compute aggregate paper trading statistics."""
        all_pos = self.all_positions
        closed = self.closed_positions
        open_pos = self.open_positions

        if not all_pos:
            return PaperTradeStats()

        total_funding = sum(p.accumulated_funding_usd for p in all_pos)
        total_fees = sum(p.accumulated_fees_usd for p in all_pos)
        total_pnl = sum(p.net_pnl_usd for p in all_pos)

        # Win rate from closed positions
        wins = sum(1 for p in closed if p.pnl_usd > 0) if closed else 0
        win_rate = wins / len(closed) if closed else 0.0

        # Average holding duration (closed only)
        if closed:
            avg_holding_secs = sum(p.holding_duration_seconds for p in closed) / len(closed)
            avg_holding_hours = avg_holding_secs / 3600
        else:
            avg_holding_hours = 0.0

        pnls = [p.pnl_usd for p in closed] if closed else [0.0]

        return PaperTradeStats(
            total_trades=len(all_pos),
            open_positions=len(open_pos),
            closed_positions=len(closed),
            total_pnl_usd=round(total_pnl, 4),
            total_funding_collected_usd=round(total_funding, 4),
            total_fees_paid_usd=round(total_fees, 4),
            win_rate=round(win_rate, 4),
            avg_holding_hours=round(avg_holding_hours, 2),
            best_trade_pnl=round(max(pnls), 4),
            worst_trade_pnl=round(min(pnls), 4),
        )

    def get_open_positions_summary(self) -> list[dict]:
        """Return summary of all open positions for API consumption."""
        return [
            {
                "position_id": p.position_id,
                "asset": p.asset,
                "exchange": p.exchange,
                "notional_usd": p.notional_usd,
                "entry_funding_apy": p.entry_funding_apy,
                "accumulated_funding_usd": round(p.accumulated_funding_usd, 4),
                "accumulated_fees_usd": round(p.accumulated_fees_usd, 4),
                "net_pnl_usd": round(p.net_pnl_usd, 4),
                "funding_payments": p.funding_payments,
                "holding_hours": round(p.holding_duration_seconds / 3600, 2),
                "entry_time": p.entry_time_utc.isoformat(),
            }
            for p in self.open_positions
        ]
