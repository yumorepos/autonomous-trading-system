"""
RegimeHistoryCollector — Fetches and stores historical funding rate data.

Builds the empirical distribution of regime durations per asset per exchange,
persisted to SQLite for the DurationPredictor.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.config import get_config
from src.models import FundingRateRecord, RegimeTier, RegimeTransition
from src.collectors.exchange_adapters.base import ExchangeAdapter
from src.utils.symbol_mapper import SymbolMapper

logger = logging.getLogger(__name__)


def _classify_regime(apy_annualized: float, thresholds: dict) -> RegimeTier:
    """Classify a funding rate into a regime tier.

    Args:
        apy_annualized: Annualized APY as percentage (e.g. 150.0 = 150%)
        thresholds: dict with low_funding_max_apy and moderate_max_apy
    """
    if apy_annualized >= thresholds["moderate_max_apy"]:
        return RegimeTier.HIGH_FUNDING
    elif apy_annualized >= thresholds["low_funding_max_apy"]:
        return RegimeTier.MODERATE
    else:
        return RegimeTier.LOW_FUNDING


class RegimeHistoryCollector:
    """Polls historical funding rates and builds regime transition history."""

    def __init__(self, adapters: list[ExchangeAdapter], db_path: str | Path | None = None):
        cfg = get_config()
        self.adapters = {a.name: a for a in adapters}
        self.db_path = Path(db_path or cfg["history"]["db_path"])
        self.backfill_days = cfg["history"]["backfill_days"]
        self.thresholds = cfg["regime_thresholds"]
        self.assets = cfg["assets"]
        self._init_db()

    def _init_db(self):
        """Create tables if they don't exist. Enable WAL mode."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS funding_rates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset TEXT NOT NULL,
                exchange TEXT NOT NULL,
                timestamp_utc TEXT NOT NULL,
                funding_rate REAL NOT NULL,
                funding_rate_annualized REAL NOT NULL,
                funding_interval_hours REAL NOT NULL,
                UNIQUE(asset, exchange, timestamp_utc)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS regime_transitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset TEXT NOT NULL,
                exchange TEXT NOT NULL,
                regime TEXT NOT NULL,
                start_time_utc TEXT NOT NULL,
                end_time_utc TEXT,
                duration_seconds REAL,
                max_apy REAL DEFAULT 0,
                avg_apy REAL DEFAULT 0,
                UNIQUE(asset, exchange, start_time_utc)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_funding_asset_exchange
            ON funding_rates(asset, exchange, timestamp_utc)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_transitions_asset_regime
            ON regime_transitions(asset, regime, exchange)
        """)
        conn.commit()
        conn.close()

    def _get_last_timestamp(self, asset: str, exchange: str) -> int | None:
        """Get the most recent funding rate timestamp (ms) for incremental fetch."""
        conn = sqlite3.connect(str(self.db_path))
        row = conn.execute(
            "SELECT MAX(timestamp_utc) FROM funding_rates WHERE asset=? AND exchange=?",
            (asset, exchange),
        ).fetchone()
        conn.close()
        if row and row[0]:
            dt = datetime.fromisoformat(row[0])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000) + 1
        return None

    def _store_funding_rates(self, records: list[FundingRateRecord]):
        """Persist funding rate records to SQLite (idempotent via UNIQUE constraint)."""
        if not records:
            return
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executemany(
            """INSERT OR IGNORE INTO funding_rates
               (asset, exchange, timestamp_utc, funding_rate, funding_rate_annualized, funding_interval_hours)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [
                (r.asset, r.exchange, r.timestamp_utc.isoformat(), r.funding_rate,
                 r.funding_rate_annualized, r.funding_interval_hours)
                for r in records
            ],
        )
        conn.commit()
        conn.close()

    def _build_regime_transitions(self, asset: str, exchange: str):
        """Compute regime transitions from stored funding rates for one asset/exchange pair."""
        conn = sqlite3.connect(str(self.db_path))
        rows = conn.execute(
            """SELECT timestamp_utc, funding_rate_annualized
               FROM funding_rates
               WHERE asset=? AND exchange=?
               ORDER BY timestamp_utc""",
            (asset, exchange),
        ).fetchall()
        conn.close()

        if not rows:
            return

        transitions: list[RegimeTransition] = []
        current_regime: RegimeTier | None = None
        regime_start: datetime | None = None
        regime_apys: list[float] = []

        for ts_str, apy in rows:
            ts = datetime.fromisoformat(ts_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)

            regime = _classify_regime(abs(apy), self.thresholds)

            if current_regime is None:
                current_regime = regime
                regime_start = ts
                regime_apys = [abs(apy)]
                continue

            if regime != current_regime:
                # Close out the previous regime
                duration = (ts - regime_start).total_seconds()
                transitions.append(RegimeTransition(
                    asset=asset,
                    exchange=exchange,
                    regime=current_regime,
                    start_time_utc=regime_start,
                    end_time_utc=ts,
                    duration_seconds=duration,
                    max_apy=max(regime_apys),
                    avg_apy=sum(regime_apys) / len(regime_apys),
                ))

                current_regime = regime
                regime_start = ts
                regime_apys = [abs(apy)]
            else:
                regime_apys.append(abs(apy))

        # Don't close the last regime — it's still ongoing

        # Store transitions (idempotent)
        if transitions:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executemany(
                """INSERT OR IGNORE INTO regime_transitions
                   (asset, exchange, regime, start_time_utc, end_time_utc, duration_seconds, max_apy, avg_apy)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (t.asset, t.exchange, t.regime.value, t.start_time_utc.isoformat(),
                     t.end_time_utc.isoformat() if t.end_time_utc else None,
                     t.duration_seconds, t.max_apy, t.avg_apy)
                    for t in transitions
                ],
            )
            conn.commit()
            conn.close()

        logger.info(
            "Built %d regime transitions for %s on %s",
            len(transitions), asset, exchange,
        )

    async def backfill(self):
        """Fetch last N days of funding history for all assets on all exchanges."""
        now = datetime.now(timezone.utc)
        start_ms = int((now - timedelta(days=self.backfill_days)).timestamp() * 1000)
        end_ms = int(now.timestamp() * 1000)

        tasks = []
        for asset in self.assets:
            for name, adapter in self.adapters.items():
                # Use incremental start if we have existing data
                last_ts = self._get_last_timestamp(asset, name)
                effective_start = last_ts if last_ts and last_ts > start_ms else start_ms

                tasks.append(self._fetch_and_store(adapter, asset, effective_start, end_ms))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                logger.warning("Backfill task failed: %s", r)

        # Build regime transitions from stored rates
        for asset in self.assets:
            for name in self.adapters:
                self._build_regime_transitions(asset, name)

        # Validate and log distribution
        self._log_distribution_summary()

    async def _fetch_and_store(
        self, adapter: ExchangeAdapter, asset: str, start_ms: int, end_ms: int
    ):
        """Fetch funding history for one asset on one exchange and store it."""
        try:
            records = await adapter.fetch_funding_history(asset, start_ms, end_ms)
            self._store_funding_rates(records)
        except Exception as e:
            logger.warning("Failed to fetch %s from %s: %s", asset, adapter.name, e)

    def get_regime_durations(
        self, asset: str | None = None, regime: str | None = None, exchange: str | None = None
    ) -> list[float]:
        """Get list of regime durations (seconds) matching the given filters."""
        conn = sqlite3.connect(str(self.db_path))
        query = "SELECT duration_seconds FROM regime_transitions WHERE duration_seconds IS NOT NULL"
        params: list = []

        if asset:
            query += " AND asset=?"
            params.append(asset)
        if regime:
            query += " AND regime=?"
            params.append(regime)
        if exchange:
            query += " AND exchange=?"
            params.append(exchange)

        rows = conn.execute(query, params).fetchall()
        conn.close()
        return [r[0] for r in rows]

    def get_transition_count(self) -> int:
        """Get total number of regime transitions in the database."""
        conn = sqlite3.connect(str(self.db_path))
        count = conn.execute("SELECT COUNT(*) FROM regime_transitions").fetchone()[0]
        conn.close()
        return count

    def _log_distribution_summary(self):
        """Log regime duration distribution statistics."""
        import numpy as np

        conn = sqlite3.connect(str(self.db_path))
        total = conn.execute("SELECT COUNT(*) FROM regime_transitions").fetchone()[0]
        logger.info("Total regime transitions stored: %d", total)

        if total < 5:
            conn.close()
            return

        regimes = [r[0] for r in conn.execute(
            "SELECT DISTINCT regime FROM regime_transitions"
        ).fetchall()]

        for regime in regimes:
            durations = [
                r[0] for r in conn.execute(
                    "SELECT duration_seconds FROM regime_transitions WHERE regime=? AND duration_seconds IS NOT NULL",
                    (regime,),
                ).fetchall()
            ]
            if not durations:
                continue

            arr = np.array(durations)
            logger.info(
                "Regime %s (n=%d): mean=%.0fs median=%.0fs p25=%.0fs p75=%.0fs p90=%.0fs",
                regime, len(arr), arr.mean(), np.median(arr),
                np.percentile(arr, 25), np.percentile(arr, 75), np.percentile(arr, 90),
            )

        conn.close()
