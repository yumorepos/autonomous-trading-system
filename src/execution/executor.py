"""
Execution Bridge — Routes scored signals from the signal filter pipeline
to real Hyperliquid orders through the trading engine's execution path.

SAFETY DEFAULTS:
  - EXECUTION_ENABLED = False  (master switch, must be manually enabled)
  - EXECUTION_DRY_RUN = True   (logs what it WOULD do, no real orders)
  - HALT file at /opt/trading/HALT blocks all execution immediately
  - Max single trade: $15 (hardcoded, not configurable)
  - Daily loss limit: $10

This module is ADDITIVE to paper trading — it never replaces it.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, date, timezone
from pathlib import Path

from src.models import ScoredSignal, RegimeTier

logger = logging.getLogger(__name__)

# Hardcoded safety ceiling — not configurable, not overridable
_ABSOLUTE_MAX_TRADE_USD = 15.0

# HALT file path — if this file exists, all execution is refused
HALT_FILE = Path("/opt/trading/HALT")

# Execution log
_EXECUTION_LOG = Path("data/execution_log.jsonl")


class ExecutionResult:
    """Result of an execution attempt."""

    def __init__(
        self,
        action: str,
        asset: str,
        reason: str,
        signal_score: float,
        dry_run: bool,
        details: dict | None = None,
    ):
        self.action = action  # "executed", "dry_run", "rejected"
        self.asset = asset
        self.reason = reason
        self.signal_score = signal_score
        self.dry_run = dry_run
        self.details = details or {}
        self.timestamp = datetime.now(timezone.utc)

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "asset": self.asset,
            "reason": self.reason,
            "signal_score": self.signal_score,
            "dry_run": self.dry_run,
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
        }


class Executor:
    """Bridges scored signals from the pipeline to Hyperliquid execution.

    All gates must pass before any order is placed. When in doubt, refuse.
    """

    def __init__(
        self,
        hl_exchange=None,
        hl_info=None,
        hl_address: str | None = None,
        telegram_send_fn=None,
    ):
        """
        Args:
            hl_exchange: hyperliquid.exchange.Exchange instance (or mock)
            hl_info: hyperliquid.info.Info instance (or mock)
            hl_address: wallet address for account queries
            telegram_send_fn: callable(message: str) -> bool for alerts
        """
        from config.risk_params import (
            EXECUTION_ENABLED,
            EXECUTION_DRY_RUN,
            EXECUTION_MIN_SCORE,
            EXECUTION_MAX_TRADE_USD,
            EXECUTION_DAILY_LOSS_LIMIT,
            EXECUTION_MIN_BALANCE,
            MAX_CONCURRENT,
            LEVERAGE,
            CIRCUIT_BREAKER_LOSSES,
        )

        self.hl_exchange = hl_exchange
        self.hl_info = hl_info
        self.hl_address = hl_address
        self._send_telegram = telegram_send_fn

        self.enabled = EXECUTION_ENABLED
        self.dry_run = EXECUTION_DRY_RUN
        self.min_score = EXECUTION_MIN_SCORE
        self.max_trade_usd = min(EXECUTION_MAX_TRADE_USD, _ABSOLUTE_MAX_TRADE_USD)
        self.daily_loss_limit = EXECUTION_DAILY_LOSS_LIMIT
        self.min_balance = EXECUTION_MIN_BALANCE
        self.max_concurrent = MAX_CONCURRENT
        self.leverage = LEVERAGE
        self.circuit_breaker_max_losses = CIRCUIT_BREAKER_LOSSES

        # Daily tracking (reset each calendar day)
        self._today: date = date.today()
        self._daily_loss_usd: float = 0.0
        self._daily_halted: bool = False

        # Execution tracking
        self._executed_assets: set[str] = set()
        self._consecutive_losses: int = 0

        # Asset metadata cache
        self._asset_metadata: dict[str, dict] = {}

        _EXECUTION_LOG.parent.mkdir(parents=True, exist_ok=True)

    def _reset_daily_if_needed(self):
        """Reset daily counters if the calendar day has changed."""
        today = date.today()
        if today != self._today:
            self._today = today
            self._daily_loss_usd = 0.0
            self._daily_halted = False

    def _log_execution(self, result: ExecutionResult):
        """Append execution attempt to JSONL log."""
        try:
            with open(_EXECUTION_LOG, "a") as f:
                f.write(json.dumps(result.to_dict(), default=str) + "\n")
        except OSError as e:
            logger.error("Failed to write execution log: %s", e)

    def _alert(self, message: str):
        """Send Telegram alert if configured."""
        if self._send_telegram:
            try:
                self._send_telegram(message)
            except Exception as e:
                logger.warning("Telegram alert failed: %s", e)

    def _get_account_balance(self) -> float:
        """Query Hyperliquid for current account balance."""
        if not self.hl_info or not self.hl_address:
            return 0.0
        try:
            state = self.hl_info.user_state(self.hl_address)
            margin = state.get("marginSummary", {})
            perp_value = float(margin.get("accountValue", 0))

            # Also check spot
            spot_usd = 0.0
            try:
                spot = self.hl_info.spot_user_state(self.hl_address)
                for b in spot.get("balances", []):
                    if b.get("coin") in ("USDC", "USDT", "USDE"):
                        spot_usd += float(b.get("total", 0))
            except Exception:
                pass

            return perp_value + spot_usd
        except Exception as e:
            logger.error("Failed to get account balance: %s", e)
            return 0.0

    def _get_open_positions(self) -> list[dict]:
        """Query Hyperliquid for open positions."""
        if not self.hl_info or not self.hl_address:
            return []
        try:
            state = self.hl_info.user_state(self.hl_address)
            positions = []
            for ap in state.get("assetPositions", []):
                p = ap.get("position", {})
                szi = float(p.get("szi", 0))
                if szi != 0:
                    positions.append({"coin": p["coin"], "szi": szi})
            return positions
        except Exception as e:
            logger.error("Failed to get positions: %s", e)
            return []

    def _fetch_asset_metadata(self):
        """Cache asset szDecimals from HL metadata."""
        if self._asset_metadata or not self.hl_info:
            return
        try:
            meta = self.hl_info.meta()
            for asset in meta.get("universe", []):
                self._asset_metadata[asset["name"]] = {
                    "szDecimals": asset.get("szDecimals", 8),
                }
        except Exception as e:
            logger.warning("Failed to fetch asset metadata: %s", e)

    def validate(self, signal: ScoredSignal) -> tuple[bool, str]:
        """Run all validation gates. Returns (passed, reason).

        Every gate is logged. ALL must pass for execution.
        """
        self._reset_daily_if_needed()

        # Gate 0: Master switch
        if not self.enabled:
            return False, "EXECUTION_ENABLED is False"

        # Gate 1: HALT file (kill switch)
        if HALT_FILE.exists():
            return False, f"HALT file exists at {HALT_FILE}"

        # Gate 2: Daily loss halt
        if self._daily_halted:
            return False, f"Daily loss limit reached (${self._daily_loss_usd:.2f} lost today)"

        # Gate 3: Signal must be actionable (passed all 5 composite scorer gates)
        if not signal.is_actionable:
            return False, f"Signal not actionable: {signal.rejection_reason}"

        # Gate 4: Minimum composite score (score is 0-100, threshold is 0-1)
        score_normalized = signal.composite_score / 100.0
        if score_normalized < self.min_score:
            return False, f"Score {score_normalized:.3f} < threshold {self.min_score}"

        # Gate 5: Regime must be HIGH_FUNDING
        if signal.event.new_regime not in (RegimeTier.HIGH_FUNDING,):
            return False, f"Regime is {signal.event.new_regime.value}, need HIGH_FUNDING"

        # Gate 6: No existing position in same asset
        open_positions = self._get_open_positions()
        open_coins = {p["coin"] for p in open_positions}
        if signal.event.asset in open_coins:
            return False, f"Already have open position in {signal.event.asset}"

        # Gate 7: Max concurrent positions
        if len(open_positions) >= self.max_concurrent:
            return False, f"At max concurrent positions ({len(open_positions)}/{self.max_concurrent})"

        # Gate 8: Circuit breaker (consecutive losses)
        if self._consecutive_losses >= self.circuit_breaker_max_losses:
            return False, f"Circuit breaker: {self._consecutive_losses} consecutive losses"

        # Gate 9: Minimum account balance
        balance = self._get_account_balance()
        if balance < self.min_balance:
            return False, f"Balance ${balance:.2f} < minimum ${self.min_balance:.2f}"

        return True, "ALL_GATES_PASSED"

    def execute(self, signal: ScoredSignal) -> ExecutionResult:
        """Attempt to execute a trade for a scored signal.

        Returns an ExecutionResult describing what happened and why.
        """
        asset = signal.event.asset
        score_normalized = signal.composite_score / 100.0

        # Validate all gates
        passed, reason = self.validate(signal)

        context = {
            "asset": asset,
            "exchange": signal.event.exchange,
            "regime": signal.event.new_regime.value,
            "composite_score": signal.composite_score,
            "score_normalized": round(score_normalized, 4),
            "net_apy": signal.net_expected_apy,
            "is_actionable": signal.is_actionable,
            "duration_survival_prob": signal.duration_survival_prob,
            "liquidity_score": signal.liquidity_score,
        }

        if not passed:
            result = ExecutionResult(
                action="rejected",
                asset=asset,
                reason=reason,
                signal_score=signal.composite_score,
                dry_run=self.dry_run,
                details=context,
            )
            self._log_execution(result)
            logger.info("EXECUTION REJECTED: %s — %s", asset, reason)
            return result

        # Calculate position size
        balance = self._get_account_balance()
        from config.risk_params import calculate_position_size

        # Use tier 1 sizing (highest conviction — signal already passed all gates)
        size_usd = calculate_position_size(balance, tier=1)

        # Enforce hard ceiling
        size_usd = min(size_usd, self.max_trade_usd, _ABSOLUTE_MAX_TRADE_USD)

        context["position_size_usd"] = size_usd
        context["account_balance"] = balance

        # DRY RUN mode
        if self.dry_run:
            result = ExecutionResult(
                action="dry_run",
                asset=asset,
                reason="DRY_RUN mode — would have executed",
                signal_score=signal.composite_score,
                dry_run=True,
                details=context,
            )
            self._log_execution(result)
            logger.info(
                "EXECUTION DRY_RUN: %s — $%.2f (score=%.1f, apy=%.1f%%)",
                asset, size_usd, signal.composite_score, signal.net_expected_apy,
            )
            self._alert(
                f"DRY RUN: Would execute {asset} — "
                f"${size_usd:.2f}, score={signal.composite_score:.0f}, "
                f"APY={signal.net_expected_apy:.1f}%"
            )
            return result

        # === LIVE EXECUTION ===
        if not self.hl_exchange or not self.hl_info:
            result = ExecutionResult(
                action="rejected",
                asset=asset,
                reason="No HL exchange/info client configured",
                signal_score=signal.composite_score,
                dry_run=False,
                details=context,
            )
            self._log_execution(result)
            return result

        # Get mid price
        try:
            all_mids = self.hl_info.all_mids()
            price = float(all_mids.get(asset, 0))
        except Exception as e:
            result = ExecutionResult(
                action="rejected",
                asset=asset,
                reason=f"Failed to get price: {e}",
                signal_score=signal.composite_score,
                dry_run=False,
                details=context,
            )
            self._log_execution(result)
            return result

        if price <= 0:
            result = ExecutionResult(
                action="rejected",
                asset=asset,
                reason=f"Invalid price: {price}",
                signal_score=signal.composite_score,
                dry_run=False,
                details=context,
            )
            self._log_execution(result)
            return result

        # Calculate size in coins
        size_coins = (size_usd * self.leverage) / price

        # Round to correct decimals
        self._fetch_asset_metadata()
        sz_decimals = self._asset_metadata.get(asset, {}).get("szDecimals", 8)
        size_coins = round(size_coins, sz_decimals)

        context["price"] = price
        context["size_coins"] = size_coins
        context["leverage"] = self.leverage

        # Place market order
        try:
            response = self.hl_exchange.market_open(asset, True, size_coins)
        except Exception as e:
            result = ExecutionResult(
                action="rejected",
                asset=asset,
                reason=f"Order failed: {e}",
                signal_score=signal.composite_score,
                dry_run=False,
                details=context,
            )
            self._log_execution(result)
            self._alert(f"EXECUTION FAILED: {asset} — {e}")
            return result

        # Check response
        if response.get("status") != "ok":
            result = ExecutionResult(
                action="rejected",
                asset=asset,
                reason=f"API returned non-ok: {response}",
                signal_score=signal.composite_score,
                dry_run=False,
                details={**context, "response": str(response)},
            )
            self._log_execution(result)
            return result

        # Check for order-level errors
        statuses = response.get("response", {}).get("data", {}).get("statuses", [])
        if statuses and statuses[0].get("error"):
            error_msg = statuses[0]["error"]
            result = ExecutionResult(
                action="rejected",
                asset=asset,
                reason=f"Order rejected by exchange: {error_msg}",
                signal_score=signal.composite_score,
                dry_run=False,
                details={**context, "exchange_error": error_msg},
            )
            self._log_execution(result)
            return result

        # Success
        self._executed_assets.add(asset)
        result = ExecutionResult(
            action="executed",
            asset=asset,
            reason="Order placed successfully",
            signal_score=signal.composite_score,
            dry_run=False,
            details={**context, "response": str(response)},
        )
        self._log_execution(result)
        logger.info(
            "EXECUTION SUCCESS: %s — $%.2f @ %.6f (%d coins), score=%.0f",
            asset, size_usd, price, size_coins, signal.composite_score,
        )
        self._alert(
            f"EXECUTED: {asset} LONG ${size_usd:.2f} @ {price:.4f} "
            f"(score={signal.composite_score:.0f}, APY={signal.net_expected_apy:.1f}%)"
        )
        return result

    def record_loss(self, loss_usd: float):
        """Record a loss for daily limit and circuit breaker tracking."""
        self._reset_daily_if_needed()
        self._daily_loss_usd += abs(loss_usd)
        self._consecutive_losses += 1

        if self._daily_loss_usd >= self.daily_loss_limit:
            self._daily_halted = True
            logger.warning(
                "DAILY LOSS LIMIT REACHED: $%.2f lost (limit: $%.2f)",
                self._daily_loss_usd, self.daily_loss_limit,
            )
            self._alert(
                f"DAILY LOSS LIMIT: ${self._daily_loss_usd:.2f} lost — "
                f"execution halted for today"
            )

    def record_win(self):
        """Record a win — resets consecutive loss counter."""
        self._consecutive_losses = 0
