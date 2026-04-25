"""
SignalFilterPipeline — Orchestrates signal scoring, logging, and forwarding.

Receives raw regime transitions, scores them via CompositeSignalScorer,
logs all results, and forwards actionable signals to Telegram.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from config.risk_params import EXECUTION_MIN_SCORE
from src.config import get_config
from src.models import RegimeTransitionEvent, ScoredSignal
from src.scoring.composite_scorer import CompositeSignalScorer
from src.scoring.liquidity_scorer import LiquidityScorer

logger = logging.getLogger(__name__)


class SignalFilterPipeline:
    """End-to-end signal filtering pipeline."""

    def __init__(self, scorer: CompositeSignalScorer, signal_log_path: str | Path | None = None):
        cfg = get_config()
        self.scorer = scorer
        self.signal_log_path = Path(signal_log_path or cfg["history"]["signal_log_path"])
        self._telegram_token = cfg["telegram"]["bot_token"]
        self._telegram_chat_id = cfg["telegram"]["chat_id"]
        self._send_rejected = cfg["telegram"].get("send_rejected", False)
        self._init_signal_db()

    def _init_signal_db(self):
        """Create signal log database."""
        self.signal_log_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.signal_log_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS signal_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp_utc TEXT NOT NULL,
                asset TEXT NOT NULL,
                exchange TEXT NOT NULL,
                new_regime TEXT NOT NULL,
                previous_regime TEXT NOT NULL,
                max_apy_annualized REAL,
                composite_score REAL,
                duration_survival_prob REAL,
                expected_duration_min REAL,
                liquidity_score REAL,
                net_expected_apy REAL,
                cross_exchange_spread REAL,
                is_actionable INTEGER,
                rejection_reason TEXT
            )
        """)
        conn.commit()
        conn.close()

    def _log_signal(self, signal: ScoredSignal):
        """Persist signal to SQLite log."""
        conn = sqlite3.connect(str(self.signal_log_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """INSERT INTO signal_log
               (timestamp_utc, asset, exchange, new_regime, previous_regime,
                max_apy_annualized, composite_score, duration_survival_prob,
                expected_duration_min, liquidity_score, net_expected_apy,
                cross_exchange_spread, is_actionable, rejection_reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                signal.event.timestamp_utc.isoformat(),
                signal.event.asset,
                signal.event.exchange,
                signal.event.new_regime.value,
                signal.event.previous_regime.value,
                signal.event.max_apy_annualized,
                signal.composite_score,
                signal.duration_survival_prob,
                signal.expected_duration_min,
                signal.liquidity_score,
                signal.net_expected_apy,
                signal.cross_exchange_spread,
                1 if signal.is_actionable else 0,
                signal.rejection_reason,
            ),
        )
        conn.commit()
        conn.close()

    def _send_telegram(self, message: str) -> bool:
        """Send a Telegram message. Returns True on success."""
        if not self._telegram_token or not self._telegram_chat_id:
            return False

        url = f"https://api.telegram.org/bot{self._telegram_token}/sendMessage"
        payload = json.dumps({
            "chat_id": self._telegram_chat_id,
            "text": message,
            "parse_mode": "HTML",
        }).encode()

        try:
            req = urllib.request.Request(
                url, data=payload,
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=5)
            return True
        except Exception as e:
            logger.warning("Telegram send failed: %s", e)
            return False

    def _format_actionable_alert(self, signal: ScoredSignal) -> str:
        """Format enriched Telegram alert for an actionable signal."""
        ts = signal.event.timestamp_utc.strftime("%H:%M:%S")
        grade = LiquidityScorer.grade(signal.liquidity_score)
        spread = (
            f"{signal.cross_exchange_spread:.1f}%"
            if signal.cross_exchange_spread is not None
            else "N/A"
        )

        score_norm = signal.composite_score / 100.0
        verdict = "ACCEPTED" if score_norm >= EXECUTION_MIN_SCORE else "REJECTED"

        return (
            f"🟢 <b>ACTIONABLE SIGNAL</b> [{ts} UTC]\n"
            f"Asset: <b>{signal.event.asset}</b> on {signal.event.exchange}\n"
            f"Regime: {signal.event.previous_regime.value} → {signal.event.new_regime.value}\n"
            f"Score: <b>{score_norm:.2f}</b> normalized "
            f"({signal.composite_score:.0f}/100 raw) — "
            f"gate {EXECUTION_MIN_SCORE:.2f}: {verdict}\n"
            f"Net APY: {signal.net_expected_apy:.1f}% | "
            f"Duration P(≥15m): {signal.duration_survival_prob * 100:.0f}%\n"
            f"Liquidity: {grade} | Cross-spread: {spread}\n"
            f"Paper: opens regardless of gate (live_orchestrator.py:277, by design)"
        )

    async def process(self, event: RegimeTransitionEvent) -> ScoredSignal:
        """Process a regime transition event through the full pipeline.

        1. Score the event
        2. Log to DB (always)
        3. Forward to Telegram (if actionable)
        """
        signal = await self.scorer.score(event)

        # Log all signals
        self._log_signal(signal)

        if signal.is_actionable:
            logger.info(
                "ACTIONABLE: %s on %s — score=%.1f, net_apy=%.1f%%",
                event.asset, event.exchange, signal.composite_score, signal.net_expected_apy,
            )
            alert = self._format_actionable_alert(signal)
            self._send_telegram(alert)
        else:
            logger.debug(
                "REJECTED: %s on %s — %s",
                event.asset, event.exchange, signal.rejection_reason,
            )

        return signal

    async def process_batch(self, events: list[RegimeTransitionEvent]) -> list[ScoredSignal]:
        """Process multiple events. Returns all scored signals."""
        signals = []
        for event in events:
            signal = await self.process(event)
            signals.append(signal)
        return signals

    def get_stats(self, hours: int = 24) -> dict:
        """Get signal statistics for the stats API."""
        conn = sqlite3.connect(str(self.signal_log_path))
        cutoff = datetime.now(timezone.utc).isoformat()

        # Total and actionable in last N hours
        total = conn.execute(
            "SELECT COUNT(*) FROM signal_log WHERE timestamp_utc >= datetime(?, ?)",
            (cutoff, f"-{hours} hours"),
        ).fetchone()[0]

        actionable = conn.execute(
            "SELECT COUNT(*) FROM signal_log WHERE is_actionable=1 AND timestamp_utc >= datetime(?, ?)",
            (cutoff, f"-{hours} hours"),
        ).fetchone()[0]

        # Top 5 scored signals
        top5_rows = conn.execute(
            """SELECT asset, exchange, new_regime, composite_score, net_expected_apy,
                      duration_survival_prob, timestamp_utc
               FROM signal_log
               WHERE timestamp_utc >= datetime(?, ?)
               ORDER BY composite_score DESC
               LIMIT 5""",
            (cutoff, f"-{hours} hours"),
        ).fetchall()

        top5 = [
            {
                "asset": r[0], "exchange": r[1], "regime": r[2],
                "score": r[3], "net_apy": r[4], "survival_prob": r[5],
                "timestamp": r[6],
            }
            for r in top5_rows
        ]

        # Per-asset breakdown
        asset_rows = conn.execute(
            """SELECT asset,
                      COUNT(*) as total,
                      SUM(CASE WHEN is_actionable=1 THEN 1 ELSE 0 END) as actionable,
                      AVG(composite_score) as avg_score
               FROM signal_log
               WHERE timestamp_utc >= datetime(?, ?)
               GROUP BY asset""",
            (cutoff, f"-{hours} hours"),
        ).fetchall()

        per_asset = {
            r[0]: {"total": r[1], "actionable": r[2], "avg_score": round(r[3] or 0, 1)}
            for r in asset_rows
        }

        conn.close()

        actionable_rate = (actionable / total * 100) if total > 0 else 0.0

        return {
            "period_hours": hours,
            "total_signals": total,
            "actionable_signals": actionable,
            "actionable_rate_pct": round(actionable_rate, 1),
            "top_5_signals": top5,
            "per_asset": per_asset,
        }
