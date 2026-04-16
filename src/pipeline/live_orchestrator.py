"""
LiveOrchestrator — Wires ATSConnector → SignalFilterPipeline → PaperTrader.

Consumes live regime transitions from the ATS engine, scores them through
the signal filter pipeline, and routes actionable signals to the paper trader.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import requests

from src.bridge.ats_connector import ATSConnector
from src.execution.executor import Executor
from src.models import RegimeTransitionEvent, RegimeTier, ScoredSignal
from src.pipeline.signal_filter import SignalFilterPipeline
from src.simulator.paper_trader import PaperTrader

logger = logging.getLogger(__name__)


class LiveOrchestrator:
    """Orchestrates the live paper trading loop.

    1. ATSConnector yields regime transition events
    2. SignalFilterPipeline scores and gates them
    3. PaperTrader opens/closes simulated positions
    """

    def __init__(
        self,
        connector: ATSConnector,
        pipeline: SignalFilterPipeline,
        paper_trader: PaperTrader,
        executor: Executor | None = None,
    ):
        self.connector = connector
        self.pipeline = pipeline
        self.paper_trader = paper_trader
        self.executor = executor
        self._events_processed = 0
        self._signals_actionable = 0
        self._positions_opened = 0
        self._positions_closed = 0
        self._executions_attempted = 0
        self._executions_succeeded = 0
        self._started_at: datetime | None = None
        self._hl_info = None  # lazy HL SDK client for mid-price fetch
        self._price_fetch_failures = 0
        self._funding_fetch_failures = 0
        self._exit_check_iterations = 0
        self._last_exit_check_ts: datetime | None = None

        # Run exit checks on every engine scan cycle (~2 min), not just on
        # regime transitions. Without this, a stable HIGH_FUNDING regime
        # would leave open positions unmonitored for SL/TP/trailing/timeout.
        self.connector.on_tick(self._check_paper_exits)

    def _get_mid_prices(self) -> dict[str, float]:
        """Fetch latest mid prices for all Hyperliquid perps.

        Returns an empty dict on any failure — callers must treat an
        empty result as "skip exit checks this cycle, try next time".
        """
        try:
            if self._hl_info is None:
                from hyperliquid.info import Info  # type: ignore
                # CRITICAL: timeout=10 — without this, the SDK's underlying
                # requests.post() runs with timeout=None and will block the
                # entire asyncio event loop forever on any network hiccup,
                # silently hanging the exit-check loop.
                self._hl_info = Info(skip_ws=True, timeout=10)
            mids = self._hl_info.all_mids()
            if not isinstance(mids, dict):
                return {}
            out: dict[str, float] = {}
            for asset, px in mids.items():
                try:
                    out[asset] = float(px)
                except (TypeError, ValueError):
                    continue
            return out
        except Exception as e:
            self._price_fetch_failures += 1
            logger.warning(
                "Paper exit check: failed to fetch mid prices (%s) — skipping",
                e,
            )
            return {}

    def _get_funding_rates(self) -> dict[str, float]:
        """Fetch current 1-hour funding rates for all Hyperliquid perps.

        Uses requests.post directly (not the hyperliquid SDK — it has
        import issues on the VPS). Returns {asset: rate_per_hour} as a
        float fraction (e.g. 0.0001 = 0.01%/hr). Returns an empty dict on
        any failure — callers must treat an empty result as "skip funding
        accrual this tick" and never crash the exit loop.
        """
        try:
            response = requests.post(
                "https://api.hyperliquid.xyz/info",
                json={"type": "metaAndAssetCtxs"},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            if not (isinstance(data, list) and len(data) >= 2):
                return {}
            universe = data[0].get("universe", [])
            ctxs = data[1]
            out: dict[str, float] = {}
            for asset_meta, ctx in zip(universe, ctxs):
                name = asset_meta.get("name")
                funding = ctx.get("funding") if isinstance(ctx, dict) else None
                if not name or funding is None:
                    continue
                try:
                    out[name] = float(funding)
                except (TypeError, ValueError):
                    continue
            return out
        except Exception as e:
            self._funding_fetch_failures += 1
            logger.warning(
                "Paper exit check: failed to fetch funding rates (%s) — "
                "skipping funding accrual this tick",
                e,
            )
            return {}

    def _check_paper_exits(self) -> None:
        """Run SL/TP/TIMEOUT/TRAILING checks on open paper positions.

        Wrapped in a blanket try/except so NO exception from any step
        (price fetch, logging, check_exits, etc.) can propagate out and
        kill the tick-callback chain. A single bad tick must never
        silence the loop.
        """
        try:
            self._exit_check_iterations += 1
            self._last_exit_check_ts = datetime.now(timezone.utc)

            # Heartbeat every 10 iterations (~20 min at 2-min scan cadence).
            # Gives us a last-known-good timestamp if the loop hangs again.
            if self._exit_check_iterations % 10 == 0:
                uptime_h = 0.0
                if self._started_at:
                    uptime_h = (
                        datetime.now(timezone.utc) - self._started_at
                    ).total_seconds() / 3600.0
                logger.info(
                    "Orchestrator heartbeat: iter=%d open=%d price_fetch_failures=%d uptime=%.2fh",
                    self._exit_check_iterations,
                    len(self.paper_trader.open_positions),
                    self._price_fetch_failures,
                    uptime_h,
                )

            open_before = list(self.paper_trader.open_positions)
            if not open_before:
                return
            prices = self._get_mid_prices()
            if not prices:
                return

            # Accrue funding BEFORE the exit check so that total ROE
            # reflects accrued funding at close time. Optional — a failed
            # fetch logs a warning in _get_funding_rates and returns {},
            # and accrue_hourly_funding is a no-op on an empty dict.
            funding_rates = self._get_funding_rates()
            try:
                self.paper_trader.accrue_hourly_funding(funding_rates)
            except Exception as e:
                logger.warning(
                    "Funding accrual raised (non-fatal, skipping): %s", e,
                )

            # Log current state before check_exits mutates ROE/peak.
            for pos in open_before:
                price_roe_pct = pos.current_roe * 100
                funding_usd = pos.accumulated_funding_usd
                funding_roe_pct = (
                    (funding_usd / pos.notional_usd * 100)
                    if pos.notional_usd > 0 else 0.0
                )
                total_pct = price_roe_pct + funding_roe_pct
                logger.info(
                    "Exit check: %d open position(s), %s ROE=%.2f%% "
                    "funding=$%.2f total=%.2f%% peak=%.2f%%",
                    len(open_before), pos.asset,
                    price_roe_pct, funding_usd, total_pct,
                    pos.peak_roe * 100,
                )
            try:
                closed = self.paper_trader.check_exits(prices)
            except Exception as e:
                logger.error("Paper exit check raised: %s", e, exc_info=True)
                return
            for pos in closed:
                self._positions_closed += 1
                logger.info(
                    "PAPER EXIT: %s %s reason=%s roe=%.2f%% hold=%.2fh pnl=$%.2f",
                    pos.asset, pos.direction, pos.exit_reason,
                    pos.current_roe * 100,
                    pos.holding_duration_seconds / 3600.0,
                    pos.pnl_usd,
                )
                # Send Telegram summary for non-admin closes
                if not self.paper_trader._is_admin_close(pos):
                    self._send_trade_close_telegram(pos)
        except Exception as e:
            logger.error(
                "Exit check loop error (swallowed to keep loop alive): %s",
                e, exc_info=True,
            )

    def _send_trade_close_telegram(self, pos) -> None:
        """Send a Telegram message summarizing a closed trade + running stats.

        Lets us monitor strategy validation progress without SSH-ing into
        the VPS. Runs inside the blanket try/except of _check_paper_exits,
        so a Telegram failure can never crash the exit loop.
        """
        try:
            stats = self.paper_trader.get_stats()
            hold_h = pos.holding_duration_seconds / 3600.0
            pnl_sign = "+" if pos.pnl_usd >= 0 else ""
            roe_pct = pos.current_roe * 100
            funding_usd = pos.accumulated_funding_usd

            # Expectancy = total_pnl / closed_count
            expectancy = (
                stats.total_pnl_usd / stats.closed_positions
                if stats.closed_positions > 0 else 0.0
            )

            msg = (
                f"{'📈' if pos.pnl_usd >= 0 else '📉'} <b>TRADE CLOSED</b>\n"
                f"{pos.asset} {pos.direction.upper()} — {pos.exit_reason}\n"
                f"PnL: <b>{pnl_sign}${pos.pnl_usd:.2f}</b> "
                f"(ROE {roe_pct:+.2f}% + funding ${funding_usd:.2f})\n"
                f"Hold: {hold_h:.1f}h\n"
                f"\n"
                f"📊 <b>Running Stats</b> ({stats.closed_positions} trades)\n"
                f"Win rate: {stats.win_rate * 100:.0f}% | "
                f"Total PnL: ${stats.total_pnl_usd:+.2f}\n"
                f"Expectancy: ${expectancy:+.2f}/trade | "
                f"Best: ${stats.best_trade_pnl:+.2f} | "
                f"Worst: ${stats.worst_trade_pnl:+.2f}"
            )
            self.pipeline._send_telegram(msg)
        except Exception as e:
            logger.warning("Trade close Telegram failed (non-fatal): %s", e)

    async def handle_event(self, event: RegimeTransitionEvent) -> ScoredSignal:
        """Process a single regime transition event through the full chain."""
        self._events_processed += 1

        # Score through the pipeline
        signal = await self.pipeline.process(event)

        if signal.is_actionable:
            self._signals_actionable += 1

            # Skip if we already hold this asset — prevents restart duplicates
            # and repeated transitions from stacking size.
            if self.paper_trader.has_open_position(event.asset, event.exchange):
                logger.info(
                    "Skipping — already holding %s on %s",
                    event.asset, event.exchange,
                )
            else:
                # Open a new paper position (always, regardless of execution).
                # Fetch entry price for directional ROE tracking.
                #
                # Direction: use whatever the signal carries. The scorer now
                # sets direction = "long" because the live engine only emits
                # NEGATIVE-funding signals (regime_detector filters
                # `if funding < 0`; trading_engine scanner filters
                # `if funding >= 0: continue`). On a negative-funding asset,
                # the earning side is LONG. Fallback is "long" for the same
                # reason — inverting this pays funding instead of collecting.
                prices_for_entry = self._get_mid_prices()
                entry_price = float(prices_for_entry.get(event.asset, 0.0) or 0.0)
                if entry_price <= 0:
                    # Do NOT open a position without a valid entry price.
                    # A position missing entry_price can never be exit-checked
                    # (SL/TP/trailing all need ROE vs entry), and on restart
                    # it gets swept as stale_cleanup for a flat -fees loss.
                    # Better to skip this signal entirely and let the next
                    # tick (or next regime event) retry.
                    logger.warning(
                        "Skipping position open for %s: could not fetch "
                        "entry price (prices_available=%d)",
                        event.asset, len(prices_for_entry),
                    )
                else:
                    direction = (
                        getattr(signal, "direction", None) or "long"
                    ).lower()
                    if direction not in ("long", "short"):
                        direction = "long"
                    position = self.paper_trader.open_position(
                        signal, entry_price=entry_price, direction=direction,
                    )
                    if position is not None:
                        self._positions_opened += 1
                        logger.info(
                            "Orchestrator: opened paper position %s for %s on %s "
                            "(entry_price=%.6f)",
                            position.position_id, event.asset, event.exchange,
                            entry_price,
                        )

            # Attempt real execution if executor is configured
            if self.executor is not None:
                try:
                    self._executions_attempted += 1
                    exec_result = self.executor.execute(signal)
                    if exec_result.action == "executed":
                        self._executions_succeeded += 1
                except Exception as e:
                    logger.error(
                        "Executor error for %s: %s", event.asset, e,
                        exc_info=True,
                    )
        else:
            # Regime downgrade no longer force-closes positions. SL/TP/
            # TIMEOUT/TRAILING (evaluated in _check_paper_exits below)
            # manage the exit — matches backtester / trading_engine.
            if event.previous_regime == RegimeTier.HIGH_FUNDING:
                logger.info(
                    "Regime downgrade from HIGH_FUNDING for %s on %s — "
                    "holding position (SL/TP/timeout will manage exit)",
                    event.asset, event.exchange,
                )

        # Evaluate exit triggers on every event cycle (~scan interval).
        self._check_paper_exits()

        return signal

    async def _evaluate_startup_regime(self) -> None:
        """If already in HIGH_FUNDING on startup, synthesize a transition event.

        The orchestrator otherwise only acts on fresh regime_updated events
        in the JSONL. A restart while already in HIGH_FUNDING would sit
        idle until the next transition. Use the cached regime_status from
        ATSConnector.seek_to_end() to evaluate the current top asset
        immediately via the same handle_event() path as a live transition.
        """
        status = self.connector.current_regime_status()
        if not status:
            return
        regime_str = status.get("regime") or status.get("new_regime")
        if regime_str != "HIGH_FUNDING":
            return

        asset, exchange = self.connector._resolve_top_asset()
        if asset == "UNKNOWN":
            logger.info(
                "Startup: current regime is HIGH_FUNDING but no top asset "
                "available — skipping startup evaluation"
            )
            return

        max_apy_pct = float(status.get("max_funding_apy", 0.0)) * 100
        event = RegimeTransitionEvent(
            asset=asset,
            exchange=exchange,
            new_regime=RegimeTier.HIGH_FUNDING,
            previous_regime=RegimeTier.MODERATE,
            max_apy_annualized=max_apy_pct,
            timestamp_utc=datetime.now(timezone.utc),
        )
        logger.info(
            "Startup: current regime is HIGH_FUNDING, evaluating top asset %s",
            asset,
        )
        try:
            await self.handle_event(event)
        except Exception as e:
            logger.error("Startup regime evaluation failed: %s", e, exc_info=True)

    async def run(self):
        """Main loop: watch for events and process them."""
        self._started_at = datetime.now(timezone.utc)

        # Seek to end of log to only process new events
        self.connector.seek_to_end()

        logger.info("LiveOrchestrator started — watching for regime transitions")

        # Startup evaluation: if already in HIGH_FUNDING, act now instead of
        # waiting for the next transition.
        await self._evaluate_startup_regime()

        # Outer while guards the async-for itself: if the connector.watch()
        # generator ever raises (e.g. unrecoverable file error), we log
        # and restart watching rather than letting the exception propagate
        # out to TaskGroup which would tear down uvicorn too.
        while True:
            try:
                async for event in self.connector.watch():
                    try:
                        await self.handle_event(event)
                    except Exception as e:
                        logger.error("Failed to handle event: %s", e, exc_info=True)
                # watch() returned normally (stop()) — exit the run loop.
                break
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(
                    "connector.watch() raised — restarting watch in 5s: %s",
                    e, exc_info=True,
                )
                await asyncio.sleep(5)

    def get_status(self) -> dict:
        """Return orchestrator status for the stats API."""
        paper_stats = self.paper_trader.get_stats()
        uptime_seconds = 0.0
        if self._started_at:
            uptime_seconds = (datetime.now(timezone.utc) - self._started_at).total_seconds()

        status = {
            "orchestrator": {
                "started_at": self._started_at.isoformat() if self._started_at else None,
                "uptime_seconds": round(uptime_seconds, 0),
                "events_processed": self._events_processed,
                "signals_actionable": self._signals_actionable,
                "positions_opened": self._positions_opened,
                "positions_closed": self._positions_closed,
            },
            "paper_trading": paper_stats.model_dump(),
            "open_positions": self.paper_trader.get_open_positions_summary(),
        }

        if self.executor is not None:
            status["execution"] = {
                "enabled": self.executor.enabled,
                "dry_run": self.executor.dry_run,
                "attempted": self._executions_attempted,
                "succeeded": self._executions_succeeded,
            }

        return status
