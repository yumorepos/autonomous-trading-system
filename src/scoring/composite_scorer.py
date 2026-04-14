"""
CompositeSignalScorer — Core scoring and gating module.

Takes a RegimeTransitionEvent and produces an actionable ScoredSignal
by combining duration prediction, liquidity scoring, and APY analysis.
"""

from __future__ import annotations

import logging

from src.config import get_config
from src.models import RegimeTransitionEvent, RegimeTier, ScoredSignal, CurrentFundingRate
from src.scoring.duration_predictor import DurationPredictor
from src.scoring.liquidity_scorer import LiquidityScorer
from src.collectors.exchange_adapters.base import ExchangeAdapter

logger = logging.getLogger(__name__)


def _normalize(value: float, min_val: float, max_val: float) -> float:
    """Normalize value to [0.0, 1.0] range."""
    if max_val <= min_val:
        return 0.0
    return max(0.0, min(1.0, (value - min_val) / (max_val - min_val)))


class CompositeSignalScorer:
    """Scores regime transition events and applies gating rules."""

    def __init__(
        self,
        duration_predictor: DurationPredictor,
        liquidity_scorer: LiquidityScorer,
        adapters: dict[str, ExchangeAdapter] | None = None,
    ):
        self.duration_predictor = duration_predictor
        self.liquidity_scorer = liquidity_scorer
        self.adapters = adapters or {}
        self._cfg = get_config()

    async def score(self, event: RegimeTransitionEvent) -> ScoredSignal:
        """Score a regime transition event.

        Returns a ScoredSignal with composite score and actionability decision.
        """
        cfg = self._cfg
        weights = cfg["scoring_weights"]
        exchange_cfg = cfg["exchanges"].get(event.exchange, {})
        fee_rate = exchange_cfg.get("fee_rate_round_trip", 0.0008)
        funding_interval_hours = exchange_cfg.get("funding_interval_hours", 8)

        # --- Component 1: Net APY ---
        # Fee cost annualized: fee_rate per round trip, assume one round trip per funding interval
        intervals_per_year = (365 * 24) / funding_interval_hours
        fee_cost_annualized = fee_rate * intervals_per_year * 100  # as percentage
        # But we only pay fees once for entry+exit, not per interval.
        # Annualized fee cost for a single round-trip over the expected holding period:
        # Simpler: fee_rate as percentage of notional, annualized assuming min 15m hold
        # fee_cost_annualized = fee_rate * 100 represents the one-time cost as percentage
        # For comparison with APY, we express it annualized assuming the position is held
        # for one funding interval at minimum:
        net_apy = event.max_apy_annualized - (fee_rate * 100)

        # --- Component 2: Duration survival probability ---
        min_duration = cfg["duration_filter"]["min_duration_minutes"]
        duration_est = self.duration_predictor.predict(
            asset=event.asset,
            regime=event.new_regime.value,
            min_duration_minutes=min_duration,
        )

        # --- Component 3: Liquidity score ---
        liq_score = await self.liquidity_scorer.score(event.asset, event.exchange)

        # --- Component 4: Cross-exchange spread ---
        cross_spread = await self._compute_cross_exchange_spread(event.asset, event.exchange)

        # --- Composite score ---
        cross_spread_normalized = (
            _normalize(cross_spread, 0, 200) if cross_spread is not None else 0.0
        )

        composite = (
            weights["net_apy"] * _normalize(net_apy, 0, 500)
            + weights["duration_confidence"] * duration_est.survival_probability
            + weights["liquidity"] * liq_score
            + weights["cross_exchange_spread"] * cross_spread_normalized
        ) * 100

        composite = round(max(0.0, min(100.0, composite)), 2)

        # --- Gating ---
        rejection_reasons = []

        if event.new_regime != RegimeTier.HIGH_FUNDING:
            rejection_reasons.append(
                f"Regime is {event.new_regime.value}, not HIGH_FUNDING"
            )

        min_survival = cfg["duration_filter"]["min_survival_probability"]
        if duration_est.survival_probability < min_survival:
            rejection_reasons.append(
                f"Duration survival prob {duration_est.survival_probability:.2f} < {min_survival}"
            )

        min_liq = cfg["liquidity_filter"]["min_liquidity_score"]
        if liq_score < min_liq:
            rejection_reasons.append(
                f"Liquidity score {liq_score:.2f} < {min_liq}"
            )

        min_net_apy = cfg["min_net_apy_annualized"]
        if net_apy < min_net_apy:
            rejection_reasons.append(
                f"Net APY {net_apy:.1f}% < {min_net_apy}%"
            )

        min_score = cfg["min_composite_score"]
        if composite < min_score:
            rejection_reasons.append(
                f"Composite score {composite:.1f} < {min_score}"
            )

        is_actionable = len(rejection_reasons) == 0
        rejection_reason = "; ".join(rejection_reasons) if rejection_reasons else None

        # Direction inference: HIGH_FUNDING regime is overwhelmingly the
        # positive-funding case (the scanner picks the asset with the highest
        # funding APY, which is virtually always positive at these levels).
        # Backtester convention: "short" when funding > 0 (we earn funding).
        # TODO: when the engine starts emitting the signed funding rate per
        # asset in the JSONL stream, switch this to:
        #   direction = "short" if event.funding_rate > 0 else "long"
        direction = "short"

        return ScoredSignal(
            event=event,
            composite_score=composite,
            duration_survival_prob=round(duration_est.survival_probability, 4),
            expected_duration_min=round(duration_est.expected_duration_min, 1),
            liquidity_score=liq_score,
            net_expected_apy=round(net_apy, 2),
            is_actionable=is_actionable,
            rejection_reason=rejection_reason,
            cross_exchange_spread=cross_spread,
            direction=direction,
        )

    async def _compute_cross_exchange_spread(
        self, asset: str, primary_exchange: str
    ) -> float | None:
        """Compute the best funding rate spread across exchanges for this asset.

        Returns the max annualized APY spread (percentage points) between the
        primary exchange and any other exchange, or None if data from <2 exchanges.
        """
        if len(self.adapters) < 2:
            return None

        import asyncio
        rates_by_exchange: dict[str, float] = {}

        async def _fetch_rate(name: str, adapter: ExchangeAdapter):
            try:
                current = await adapter.fetch_current_rates()
                for r in current:
                    if r.asset == asset:
                        rates_by_exchange[name] = r.funding_rate_annualized
                        break
            except Exception as e:
                logger.debug("Cross-spread: failed to fetch %s from %s: %s", asset, name, e)

        tasks = [_fetch_rate(n, a) for n, a in self.adapters.items()]
        await asyncio.gather(*tasks)

        if len(rates_by_exchange) < 2:
            logger.debug("Cross-spread: only %d exchanges returned data for %s", len(rates_by_exchange), asset)
            return None

        rates = list(rates_by_exchange.values())
        spread = max(rates) - min(rates)
        logger.debug(
            "Cross-spread for %s: %s -> spread=%.2f%%",
            asset, {k: f"{v:.1f}%" for k, v in rates_by_exchange.items()}, spread,
        )
        return round(spread, 2)
