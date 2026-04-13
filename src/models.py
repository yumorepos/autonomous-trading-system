"""
Pydantic data models for the signal filtering pipeline.

All times are UTC. All APY figures are annualized percentages (e.g. 150.0 = 150% APY).
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class RegimeTier(str, Enum):
    LOW_FUNDING = "LOW_FUNDING"
    MODERATE = "MODERATE"
    HIGH_FUNDING = "HIGH_FUNDING"


class FundingRateRecord(BaseModel):
    """Single funding rate observation from an exchange."""
    asset: str
    exchange: str
    timestamp_utc: datetime
    funding_rate: float          # Raw per-interval rate (e.g. 0.0001)
    funding_rate_annualized: float  # Annualized percentage (e.g. 109.5)
    funding_interval_hours: float


class CurrentFundingRate(BaseModel):
    """Current/next funding rate snapshot."""
    asset: str
    exchange: str
    funding_rate: float
    funding_rate_annualized: float
    next_funding_time_utc: datetime | None = None
    mark_price: float | None = None
    index_price: float | None = None


class RegimeTransition(BaseModel):
    """A single regime transition record stored in the history DB."""
    asset: str
    exchange: str
    regime: RegimeTier
    start_time_utc: datetime
    end_time_utc: datetime | None = None
    duration_seconds: float | None = None
    max_apy: float = 0.0
    avg_apy: float = 0.0


class RegimeTransitionEvent(BaseModel):
    """Incoming regime transition event from the ATS engine."""
    asset: str
    exchange: str
    new_regime: RegimeTier
    previous_regime: RegimeTier
    max_apy_annualized: float
    timestamp_utc: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ScoredSignal(BaseModel):
    """Output of the CompositeSignalScorer."""
    event: RegimeTransitionEvent
    composite_score: float         # 0.0 to 100.0
    duration_survival_prob: float  # P(regime lasts >= min_duration)
    expected_duration_min: float
    liquidity_score: float
    net_expected_apy: float        # APY minus estimated fees
    is_actionable: bool
    rejection_reason: str | None = None
    cross_exchange_spread: float | None = None


class TickerInfo(BaseModel):
    """24h ticker data used for liquidity scoring."""
    asset: str
    exchange: str
    volume_24h_usd: float
    open_interest_usd: float


# --- Paper Trading Models ---

class SimulatedPosition(BaseModel):
    """A simulated delta-neutral position (long spot + short perp)."""
    position_id: str
    asset: str
    exchange: str
    entry_time_utc: datetime
    entry_regime: RegimeTier
    notional_usd: float
    entry_funding_apy: float
    accumulated_funding_usd: float = 0.0
    accumulated_fees_usd: float = 0.0
    funding_payments: int = 0
    is_open: bool = True
    exit_time_utc: datetime | None = None
    exit_reason: str | None = None
    pnl_usd: float = 0.0

    @property
    def net_pnl_usd(self) -> float:
        return self.accumulated_funding_usd - self.accumulated_fees_usd

    @property
    def holding_duration_seconds(self) -> float:
        end = self.exit_time_utc or datetime.now(timezone.utc)
        return (end - self.entry_time_utc).total_seconds()


class PaperTradeStats(BaseModel):
    """Aggregate paper trading statistics."""
    total_trades: int = 0
    open_positions: int = 0
    closed_positions: int = 0
    total_pnl_usd: float = 0.0
    total_funding_collected_usd: float = 0.0
    total_fees_paid_usd: float = 0.0
    win_rate: float = 0.0
    avg_holding_hours: float = 0.0
    best_trade_pnl: float = 0.0
    worst_trade_pnl: float = 0.0
