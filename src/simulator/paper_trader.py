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

from config.risk_params import (
    MAX_CONCURRENT,
    STOP_LOSS_ROE,
    TAKE_PROFIT_ROE,
    TIMEOUT_HOURS,
    TRAILING_STOP_ACTIVATE,
    TRAILING_STOP_DISTANCE,
)
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
        max_open_positions: int | None = None,
        entry_fee_bps: float = 4.0,
        exit_fee_bps: float = 4.0,
        slippage_bps: float = 2.0,
        log_path: str | Path | None = None,
    ):
        self.notional_per_trade = notional_per_trade
        # Source of truth: config/risk_params.py:MAX_CONCURRENT. A prior
        # yaml key (simulator.max_open_positions: 5) silently overrode this
        # constant in production; removing the yaml read prevents that drift.
        self.max_open_positions = (
            max_open_positions if max_open_positions is not None else MAX_CONCURRENT
        )
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

        # Reload prior open positions from JSONL log so that a process
        # restart doesn't drop state and open duplicate positions.
        self._reload_open_positions_from_log()

    @property
    def open_positions(self) -> list[SimulatedPosition]:
        return [p for p in self.positions if p.is_open]

    def has_open_position(self, asset: str, exchange: str | None = None) -> bool:
        """True if there's an open position for this asset (+ optional exchange)."""
        for p in self.open_positions:
            if p.asset == asset and (exchange is None or p.exchange == exchange):
                return True
        return False

    def _reload_open_positions_from_log(self) -> None:
        """Reconstruct positions from the JSONL log on startup.

        Loads both still-open positions (for continued monitoring) and
        historically closed positions (for accurate lifetime stats via
        ``get_stats()``). Without loading closed history, every restart
        resets win_rate/expectancy to zero and we lose validation data.

        Any rebuilt open position missing entry_price (legacy records)
        is closed as 'stale_cleanup' so it cannot linger unmonitored.
        """
        if not self.log_path.exists():
            return

        open_records: dict[str, dict] = {}
        close_records: dict[str, dict] = {}
        try:
            with open(self.log_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    pid = rec.get("position_id")
                    if not pid:
                        continue
                    action = rec.get("action")
                    if action == "OPEN":
                        open_records[pid] = rec
                    elif action == "CLOSE":
                        close_records[pid] = rec
        except OSError as e:
            logger.warning("Failed to reload paper trades log: %s", e)
            return

        # --- Rebuild closed positions for accurate historical stats ---
        closed_loaded = 0
        for pid, crec in close_records.items():
            try:
                entry_time_str = crec.get("entry_time") or crec.get("timestamp")
                entry_time = datetime.fromisoformat(entry_time_str)
                if entry_time.tzinfo is None:
                    entry_time = entry_time.replace(tzinfo=timezone.utc)
                exit_time_str = crec.get("exit_time") or crec.get("timestamp")
                exit_time = datetime.fromisoformat(exit_time_str)
                if exit_time.tzinfo is None:
                    exit_time = exit_time.replace(tzinfo=timezone.utc)
                regime_str = crec.get("entry_regime") or "HIGH_FUNDING"
                try:
                    entry_regime = RegimeTier(regime_str)
                except ValueError:
                    entry_regime = RegimeTier.HIGH_FUNDING
                pos = SimulatedPosition(
                    position_id=pid,
                    asset=crec["asset"],
                    exchange=crec["exchange"],
                    entry_time_utc=entry_time,
                    entry_regime=entry_regime,
                    notional_usd=float(crec.get("notional_usd", 0.0)),
                    entry_funding_apy=float(crec.get("entry_funding_apy", 0.0)),
                    entry_price=float(crec.get("entry_price", 0.0)),
                    direction=crec.get("direction", "long"),
                    peak_roe=float(crec.get("peak_roe", 0.0)),
                    current_roe=float(crec.get("current_roe", 0.0)),
                    price_pnl_usd=float(crec.get("price_pnl_usd", 0.0)),
                    accumulated_funding_usd=float(crec.get("accumulated_funding_usd", 0.0)),
                    accumulated_fees_usd=float(crec.get("accumulated_fees_usd", 0.0)),
                    funding_payments=int(crec.get("funding_payments", 0)),
                    is_open=False,
                    exit_reason=crec.get("exit_reason"),
                    exit_price=float(crec["exit_price"]) if crec.get("exit_price") else None,
                    exit_time_utc=exit_time,
                )
                pos.pnl_usd = float(crec.get("net_pnl_usd", 0.0))
                self.closed_positions.append(pos)
                closed_loaded += 1
            except (KeyError, ValueError, TypeError) as e:
                logger.warning(
                    "Skipping malformed CLOSE record %s: %s", pid, e,
                )
                continue

        # --- Rebuild still-open positions ---
        still_open = [
            rec for pid, rec in open_records.items() if pid not in close_records
        ]

        reloaded = 0
        stale: list[SimulatedPosition] = []
        for rec in still_open:
            try:
                entry_time = datetime.fromisoformat(
                    rec.get("entry_time") or rec.get("timestamp")
                )
                if entry_time.tzinfo is None:
                    entry_time = entry_time.replace(tzinfo=timezone.utc)
                regime_str = rec.get("entry_regime") or "HIGH_FUNDING"
                try:
                    entry_regime = RegimeTier(regime_str)
                except ValueError:
                    entry_regime = RegimeTier.HIGH_FUNDING
                pos = SimulatedPosition(
                    position_id=rec["position_id"],
                    asset=rec["asset"],
                    exchange=rec["exchange"],
                    entry_time_utc=entry_time,
                    entry_regime=entry_regime,
                    notional_usd=float(rec.get("notional_usd", 0.0)),
                    entry_funding_apy=float(rec.get("entry_funding_apy", 0.0)),
                    entry_price=float(rec.get("entry_price", 0.0)),
                    direction=rec.get("direction", "long"),
                    peak_roe=float(rec.get("peak_roe", 0.0)),
                    current_roe=float(rec.get("current_roe", 0.0)),
                    price_pnl_usd=float(rec.get("price_pnl_usd", 0.0)),
                    accumulated_funding_usd=float(rec.get("accumulated_funding_usd", 0.0)),
                    accumulated_fees_usd=float(rec.get("accumulated_fees_usd", 0.0)),
                    funding_payments=int(rec.get("funding_payments", 0)),
                    is_open=True,
                )
            except (KeyError, ValueError, TypeError) as e:
                logger.warning(
                    "Skipping malformed OPEN record %s: %s",
                    rec.get("position_id"), e,
                )
                continue
            self.positions.append(pos)
            reloaded += 1
            if pos.entry_price <= 0:
                stale.append(pos)

        logger.info(
            "Reloaded %d open + %d closed paper position(s) from log (%d stale)",
            reloaded, closed_loaded, len(stale),
        )
        if closed_loaded > 0:
            stats = self.get_stats()
            logger.info(
                "Historical stats: %d closed, win_rate=%.0f%%, total_pnl=$%.2f, "
                "best=$%.2f, worst=$%.2f",
                stats.closed_positions, stats.win_rate * 100,
                stats.total_pnl_usd, stats.best_trade_pnl, stats.worst_trade_pnl,
            )
        for pos in stale:
            logger.warning(
                "Stale position %s (%s) has no entry_price — closing as stale_cleanup",
                pos.position_id, pos.asset,
            )
            self.close_position(pos, reason="stale_cleanup")

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
            "entry_price": position.entry_price,
            "direction": position.direction,
            "peak_roe": position.peak_roe,
            "current_roe": position.current_roe,
            "price_pnl_usd": position.price_pnl_usd,
            "accumulated_funding_usd": position.accumulated_funding_usd,
            "accumulated_fees_usd": position.accumulated_fees_usd,
            "funding_payments": position.funding_payments,
            "net_pnl_usd": position.net_pnl_usd,
            "entry_time": position.entry_time_utc.isoformat(),
            "entry_regime": position.entry_regime.value
                if hasattr(position.entry_regime, "value") else str(position.entry_regime),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if position.exit_reason:
            record["exit_reason"] = position.exit_reason
        if position.exit_price is not None:
            record["exit_price"] = position.exit_price
        if position.exit_time_utc is not None:
            record["exit_time"] = position.exit_time_utc.isoformat()

        try:
            with open(self.log_path, "a") as f:
                f.write(json.dumps(record) + "\n")
        except OSError as e:
            logger.warning("Failed to log trade: %s", e)

    def open_position(
        self,
        signal: ScoredSignal,
        entry_price: float,
        direction: str = "short",
    ) -> SimulatedPosition | None:
        """Open a new paper position based on an actionable signal.

        Args:
            signal: scored signal from the pipeline
            entry_price: mid price at entry (used for ROE-based exits).
                Must be > 0 — a position without a valid entry price can
                never be exit-checked (SL/TP/trailing all compute ROE vs
                entry), and ends up swept as stale_cleanup on restart.
            direction: "short" (earn positive funding) or "long"

        Returns the SimulatedPosition or None if at capacity.

        Raises:
            ValueError: if entry_price is None or <= 0. This is the
                belt-and-suspenders guard backing the orchestrator's
                pre-call check (_get_mid_prices can silently return {}
                when the HL SDK import fails on the VPS).
        """
        if entry_price is None or entry_price <= 0:
            raise ValueError(
                f"open_position requires entry_price > 0, got {entry_price!r} "
                f"for {signal.event.asset} on {signal.event.exchange}"
            )
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
            entry_price=entry_price,
            direction=direction,
            last_funding_update=signal.event.timestamp_utc,
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
        exit_price: float | None = None,
    ) -> SimulatedPosition:
        """Close an open paper position.

        If ``exit_price`` is supplied and the position has a valid
        ``entry_price``, a directional price PnL is recorded
        (``notional_usd * roe``) in addition to any accrued funding.
        """
        if not position.is_open:
            return position

        # Directional price PnL (matches backtester / engine ROE math)
        if exit_price is not None and position.entry_price > 0:
            roe = position.compute_roe(exit_price)
            position.exit_price = exit_price
            position.current_roe = roe
            position.price_pnl_usd = position.notional_usd * roe

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

        # Log running aggregate stats after every non-admin close
        if not self._is_admin_close(position):
            stats = self.get_stats()
            logger.info(
                "RUNNING STATS: closed=%d win_rate=%.0f%% total_pnl=$%.2f "
                "avg_hold=%.1fh best=$%.2f worst=$%.2f",
                stats.closed_positions, stats.win_rate * 100,
                stats.total_pnl_usd, stats.avg_holding_hours,
                stats.best_trade_pnl, stats.worst_trade_pnl,
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

    def accrue_hourly_funding(
        self,
        funding_rates: dict[str, float],
        now: datetime | None = None,
    ) -> None:
        """Accrue funding based on current per-hour funding rates.

        ``funding_rates`` maps asset symbol → 1-hour funding rate (fraction,
        not percent — e.g. 0.0001 for 0.01%/hr). For each matching open
        position, funding accrues over the elapsed wall-clock time since
        its ``last_funding_update`` (or ``entry_time_utc`` if unset).

        SHORT positions RECEIVE positive funding (income); LONG positions
        PAY positive funding (expense).
        """
        if not funding_rates:
            return
        now = now or datetime.now(timezone.utc)
        for p in self.open_positions:
            rate = funding_rates.get(p.asset)
            if rate is None:
                continue
            last = p.last_funding_update or p.entry_time_utc
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            hours = (now - last).total_seconds() / 3600.0
            if hours <= 0:
                continue
            sign = 1.0 if p.direction == "short" else -1.0
            payment = sign * rate * p.notional_usd * hours
            p.accumulated_funding_usd += payment
            p.funding_payments += 1
            p.last_funding_update = now
            logger.debug(
                "Hourly funding: %s %s %.6f/hr × %.3fh → $%.4f (total $%.2f)",
                p.asset, p.direction, rate, hours, payment,
                p.accumulated_funding_usd,
            )

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

    def check_exits(
        self, current_prices: dict[str, float]
    ) -> list[SimulatedPosition]:
        """Evaluate all open positions against SL/TP/TIMEOUT/TRAILING triggers.

        Mirrors the exit-priority order used by the backtester
        (``scripts/backtest/engine.py::_check_exits``) and the live
        trading engine (``scripts/trading_engine.py::evaluate_triggers``):
        STOP_LOSS → TIMEOUT → TAKE_PROFIT → TRAILING_STOP.

        Parameters come from ``config/risk_params.py`` — never hardcoded.

        Args:
            current_prices: mapping of asset symbol → current mid price.
                Positions with no entry_price or missing current price
                are skipped.

        Returns:
            List of positions that were closed this call.
        """
        now = datetime.now(timezone.utc)
        closed: list[SimulatedPosition] = []

        for pos in list(self.open_positions):
            if pos.entry_price <= 0:
                continue  # legacy / unpriced — cannot evaluate ROE
            price = current_prices.get(pos.asset)
            if price is None or price <= 0:
                continue  # no price this cycle — try again later

            roe = pos.compute_roe(price)
            pos.current_roe = roe
            if roe > pos.peak_roe:
                pos.peak_roe = roe

            age_hours = (now - pos.entry_time_utc).total_seconds() / 3600.0

            # 1. Stop-loss (highest priority)
            if roe <= STOP_LOSS_ROE:
                self.close_position(pos, reason="STOP_LOSS", exit_price=price)
                closed.append(pos)
                continue

            # 2. Timeout
            if age_hours >= TIMEOUT_HOURS:
                self.close_position(pos, reason="TIMEOUT", exit_price=price)
                closed.append(pos)
                continue

            # 3. Take-profit
            if roe >= TAKE_PROFIT_ROE:
                self.close_position(pos, reason="TAKE_PROFIT", exit_price=price)
                closed.append(pos)
                continue

            # 4. Trailing stop (only after peak_roe exceeds activation)
            if pos.peak_roe >= TRAILING_STOP_ACTIVATE:
                trail_threshold = pos.peak_roe - TRAILING_STOP_DISTANCE
                if roe <= trail_threshold:
                    self.close_position(
                        pos, reason="TRAILING_STOP", exit_price=price
                    )
                    closed.append(pos)
                    continue

        return closed

    @staticmethod
    def _is_admin_close(position: SimulatedPosition) -> bool:
        """Admin-close positions are excluded from Gate 1 strategy stats.

        An exit_reason starting with ``admin_`` marks a one-time
        operational intervention (e.g. closing a bug-direction position
        after a fix). These are NOT strategy samples — including them
        would permanently contaminate win_rate / pnl aggregates with
        legacy bug losses. Only automated exits (STOP_LOSS, TAKE_PROFIT,
        TRAILING_STOP, TIMEOUT, stale_cleanup, regime_change) count.
        """
        reason = position.exit_reason or ""
        return reason.startswith("admin_")

    def get_stats(self) -> PaperTradeStats:
        """Compute aggregate paper trading statistics.

        Positions closed with an ``admin_*`` exit_reason are excluded from
        every aggregate — see ``_is_admin_close``.

        **total_pnl_usd** includes open positions' accrued funding minus
        fees, but NOT their unrealized price PnL (``price_pnl_usd`` is
        only set at close time). This means total_pnl_usd understates
        losses on underwater open positions and understates gains on
        profitable ones. Win rate, best/worst, and avg_holding are
        computed from closed positions only.
        """
        # Open positions always count (they reflect live exposure). Closed
        # positions only count if they weren't admin-closed.
        open_pos = self.open_positions
        closed = [p for p in self.closed_positions if not self._is_admin_close(p)]
        all_pos = open_pos + closed

        if not all_pos:
            return PaperTradeStats()

        total_funding = sum(p.accumulated_funding_usd for p in all_pos)
        total_fees = sum(p.accumulated_fees_usd for p in all_pos)
        total_pnl = sum(p.net_pnl_usd for p in all_pos)

        # Win rate from closed (non-admin) positions
        wins = sum(1 for p in closed if p.pnl_usd > 0) if closed else 0
        win_rate = wins / len(closed) if closed else 0.0

        # Average holding duration (closed non-admin only)
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
