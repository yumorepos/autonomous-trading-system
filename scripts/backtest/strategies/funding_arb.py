"""
Funding arbitrage strategy for backtesting.

Replicates the live trading engine's entry logic:
- Entry when abs(rate) * 24 * 365 > TIER2_MIN_FUNDING AND volume_24h > TIER2_MIN_VOLUME
- Short when funding highly positive (earn funding)
- Long when funding highly negative (earn funding)

D43: The input ``state.funding_rates[asset]`` is per-hour (Hyperliquid
``ctx['funding']``), not per-8h. The legacy name ``rate_8h`` in the code
is a misnomer preserved for diff hygiene.

D50: Optional composite-score instrumentation. When ``enable_scoring`` is
True the strategy attaches ScoredSignal fields to the returned candidate
so the engine can persist them to a companion jsonl. Scoring is
OBSERVATIONAL — it does not change candidate selection or execution
(PF_raw is unaffected). Synthesis: liquidity_score uses a volume-only
log-norm because historical open-interest data is not captured.
Duration-survival uses the real regime_history.db (pooled fallback for
assets absent from the DB, i.e., the scorer's own fallback path).
Cross-exchange-spread is None (scorer's <2-adapter path; single-venue
backtest).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.risk_params import (
    TIER1_MIN_FUNDING,
    TIER1_MIN_VOLUME,
    TIER2_MIN_FUNDING,
    TIER2_MIN_VOLUME,
    calculate_position_size,
    BACKTEST_INITIAL_CAPITAL,
)

if TYPE_CHECKING:
    from scripts.backtest.engine import MarketState


class FundingArbStrategy:
    """
    Callable strategy: strategy(market_state) -> signal dict or None.

    Scans all assets for funding rate opportunities each hour.
    Returns the highest-scoring signal (if any).
    """

    def __init__(
        self,
        min_funding_apy: float = TIER2_MIN_FUNDING,
        min_volume: float = TIER2_MIN_VOLUME,
        capital: float = BACKTEST_INITIAL_CAPITAL,
        enable_scoring: bool = False,
        regime_db_path: Path | None = None,
    ):
        self.min_funding_apy = min_funding_apy
        self.min_volume = min_volume
        self.capital = capital
        self.enable_scoring = enable_scoring

        self._scorer = None
        self._liq_stub = None
        self._asyncio = None

        if enable_scoring:
            # D50: construct composite scorer with historical stand-ins.
            # Imports deferred so non-scoring runs don't pay the cost.
            import asyncio as _asyncio
            from src.collectors.regime_history import RegimeHistoryCollector
            from src.scoring.composite_scorer import CompositeSignalScorer
            from src.scoring.duration_predictor import DurationPredictor

            self._asyncio = _asyncio
            db = regime_db_path or (REPO_ROOT / "data" / "regime_history.db")
            rhc = RegimeHistoryCollector(adapters=[], db_path=db)
            duration_pred = DurationPredictor(rhc)

            self._liq_stub = _HistoricalLiquidityScorer()
            self._scorer = CompositeSignalScorer(
                duration_predictor=duration_pred,
                liquidity_scorer=self._liq_stub,
                adapters={},  # single-venue backtest: cross_spread -> None
            )

    def __call__(self, state: MarketState) -> dict | None:
        """Evaluate all assets and return the best signal or None."""
        # First pass: filter. Collect raw candidates before any scoring so
        # the synthetic liquidity scorer can log-normalize against the
        # max volume among candidates in the current bar.
        raw: list[tuple[str, float, float, float]] = []
        for asset, rate_8h in state.funding_rates.items():
            if asset not in state.prices:
                continue

            # Annualized rate — D43: live HL `funding` is per-hour, not per-8h.
            # Backtest variable is named rate_8h for legacy reasons but carries
            # the same per-hour semantic as live ctx['funding']; use × 24 × 365.
            funding_annual = abs(rate_8h) * 24 * 365
            volume = state.volumes_24h.get(asset, 0)

            if funding_annual < self.min_funding_apy:
                continue
            if volume < self.min_volume:
                continue

            raw.append((asset, rate_8h, funding_annual, volume))

        if not raw:
            return None

        if self.enable_scoring and self._liq_stub is not None:
            self._liq_stub.set_bar_volumes({a: v for a, _, _, v in raw})

        candidates: list[dict] = []
        for asset, rate_8h, funding_annual, volume in raw:
            # Direction: short when funding positive (shorts earn),
            #            long when funding negative (longs earn)
            direction = "short" if rate_8h > 0 else "long"

            # Tiered sizing
            if funding_annual >= TIER1_MIN_FUNDING and volume >= TIER1_MIN_VOLUME:
                tier = 1
                score = funding_annual * 2  # Higher weight for tier 1
            else:
                tier = 2
                score = funding_annual

            size = calculate_position_size(self.capital, tier)

            cand = {
                "asset": asset,
                "direction": direction,
                "position_size_usd": size,
                "score": score,
                "funding_8h": rate_8h,
                "annualized_rate": funding_annual,
                "volume_24h": volume,
                "signal_type": "funding_arbitrage",
            }

            if self.enable_scoring:
                cand.update(self._score_candidate(asset, funding_annual, state.timestamp))

            candidates.append(cand)

        if not candidates:
            return None

        # Return highest scoring (by raw funding tier score; composite is observational)
        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates[0]

    def _score_candidate(
        self, asset: str, funding_annual: float, timestamp_ms: int
    ) -> dict:
        """Run the composite scorer at entry time for one candidate.

        Returns a dict of fields to attach to the candidate record. The
        scorer is invoked via read-only import; its adapters dict is
        empty (single-venue backtest) and its liquidity scorer is the
        historical volume stand-in.
        """
        from datetime import datetime, timezone
        from src.models import RegimeTier, RegimeTransitionEvent

        event = RegimeTransitionEvent(
            asset=asset,
            exchange="hyperliquid",
            new_regime=RegimeTier.HIGH_FUNDING,
            previous_regime=RegimeTier.MODERATE,
            max_apy_annualized=funding_annual * 100,  # fraction -> percent
            timestamp_utc=datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc),
        )
        signal = self._asyncio.run(self._scorer.score(event))
        return {
            "composite_score": signal.composite_score,
            "composite_score_normalized": round(signal.composite_score / 100.0, 4),
            "max_apy_annualized": event.max_apy_annualized,
            "new_regime": event.new_regime.value,
            "duration_survival_prob": signal.duration_survival_prob,
            "liquidity_score": signal.liquidity_score,
            "cross_exchange_spread": signal.cross_exchange_spread,
            "synthesized_fields": [
                "liquidity_score (OI unavailable historically; volume-only log-norm against per-bar max)",
            ],
            "scorer_is_actionable": signal.is_actionable,
            "scorer_rejection_reason": signal.rejection_reason,
        }


class _HistoricalLiquidityScorer:
    """Drop-in LiquidityScorer stand-in using historical 24h volume.

    D50 synthesis: open-interest component absent (not captured in
    historical data). Score is a pure log-normalization of 24h volume
    against the per-bar max volume across candidates. Matches the
    ``async def score(...) -> float`` signature the composite scorer
    invokes. Intentionally does NOT subclass LiquidityScorer so we skip
    the adapter-driven refresh path.
    """

    def __init__(self) -> None:
        self._volumes: dict[str, float] = {}
        self._max_volume = 1.0

    def set_bar_volumes(self, volumes: dict[str, float]) -> None:
        self._volumes = volumes
        self._max_volume = max(volumes.values()) if volumes else 1.0

    async def score(self, asset: str, exchange: str | None = None) -> float:
        import math

        vol = self._volumes.get(asset, 0.0)
        if self._max_volume <= 0:
            return 0.0
        raw = math.log10(vol + 1) / math.log10(self._max_volume + 1)
        return round(min(max(raw, 0.0), 1.0), 4)
