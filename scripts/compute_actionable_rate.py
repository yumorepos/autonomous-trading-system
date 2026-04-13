#!/usr/bin/env python3
"""
Replays ALL historical regime transitions through CompositeSignalScorer
and reports the actionable rate.

Usage:
    python3 scripts/compute_actionable_rate.py
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.config import load_config
from src.factory import build_adapters
from src.collectors.regime_history import RegimeHistoryCollector
from src.scoring.duration_predictor import DurationPredictor
from src.scoring.liquidity_scorer import LiquidityScorer
from src.scoring.composite_scorer import CompositeSignalScorer
from src.models import RegimeTransitionEvent, RegimeTier, ScoredSignal

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _load_transitions(db_path: str) -> list[dict]:
    """Load all regime transitions from the database."""
    conn = sqlite3.connect(db_path)
    rows = conn.execute("""
        SELECT asset, exchange, regime, start_time_utc, end_time_utc,
               duration_seconds, max_apy, avg_apy
        FROM regime_transitions
        WHERE duration_seconds IS NOT NULL
        ORDER BY start_time_utc
    """).fetchall()
    conn.close()

    transitions = []
    for r in rows:
        transitions.append({
            "asset": r[0],
            "exchange": r[1],
            "regime": r[2],
            "start_time": r[3],
            "end_time": r[4],
            "duration_seconds": r[5],
            "max_apy": r[6],
            "avg_apy": r[7],
        })
    return transitions


def _build_events(transitions: list[dict]) -> list[RegimeTransitionEvent]:
    """Convert raw transitions to RegimeTransitionEvent objects."""
    events = []
    # Group by (asset, exchange) to determine previous regime
    by_pair: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for t in transitions:
        by_pair[(t["asset"], t["exchange"])].append(t)

    for (asset, exchange), pair_transitions in by_pair.items():
        pair_transitions.sort(key=lambda x: x["start_time"])
        for i, t in enumerate(pair_transitions):
            try:
                regime = RegimeTier(t["regime"])
            except ValueError:
                continue

            prev_regime = (
                RegimeTier(pair_transitions[i - 1]["regime"])
                if i > 0 else RegimeTier.LOW_FUNDING
            )

            ts = datetime.fromisoformat(t["start_time"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)

            events.append(RegimeTransitionEvent(
                asset=asset,
                exchange=exchange,
                new_regime=regime,
                previous_regime=prev_regime,
                max_apy_annualized=t["max_apy"],
                timestamp_utc=ts,
            ))

    return events


async def main():
    cfg = load_config()
    db_path = cfg["history"]["db_path"]

    if not Path(db_path).exists():
        print("ERROR: regime_history.db not found. Run backfill first.")
        sys.exit(1)

    # Build scorer — pre-warm liquidity cache once, skip per-event cross-spread API calls
    adapters = build_adapters(cfg)
    collector = RegimeHistoryCollector(adapters)
    duration_predictor = DurationPredictor(collector)
    liquidity_scorer = LiquidityScorer(adapters)

    print("  Pre-warming liquidity cache...")
    await liquidity_scorer.refresh()

    # Pass adapters for cross-spread on a small sample, but not all 1,472 events
    adapter_dict = {a.name: a for a in adapters}
    scorer = CompositeSignalScorer(duration_predictor, liquidity_scorer)
    # We'll compute cross-spread separately on a sample

    # Load and convert transitions
    transitions = _load_transitions(db_path)
    events = _build_events(transitions)

    if not events:
        print("ERROR: No events to replay.")
        sys.exit(1)

    print(f"\n  Scoring {len(events)} regime transitions...")

    # Score all events
    results: list[ScoredSignal] = []
    for i, event in enumerate(events):
        try:
            signal = await scorer.score(event)
            results.append(signal)
        except Exception as e:
            logger.warning("Failed to score event %d: %s", i, e)

        if (i + 1) % 200 == 0:
            print(f"    ... scored {i + 1}/{len(events)}")

    actionable = [r for r in results if r.is_actionable]
    rejected = [r for r in results if not r.is_actionable]

    # --- Gate analysis ---
    gate_counters = Counter()
    for r in rejected:
        if r.rejection_reason:
            reasons = r.rejection_reason.split("; ")
            # Only count the first gate that failed (ordered rejection)
            gate_counters[reasons[0].split(":")[0].strip()] += 1

    # Get date range
    dates = sorted(r.event.timestamp_utc for r in results)
    date_start = dates[0].strftime("%Y-%m-%d") if dates else "N/A"
    date_end = dates[-1].strftime("%Y-%m-%d") if dates else "N/A"

    # --- Print report ---
    print()
    print("=" * 70)
    print("  ACTIONABLE RATE REPORT")
    print("=" * 70)
    print(f"\n  Period: {date_start} to {date_end}")
    print(f"  Total regime transitions scored: {len(results):,}")

    print(f"\n  GATE ANALYSIS (why signals are rejected):")
    print(f"  {'Gate':<40} {'Rejected':>10} {'%':>8}")
    print(f"  {'-'*40} {'-'*10} {'-'*8}")

    # Categorize rejections
    gate_labels = {
        "Regime is": "Not HIGH_FUNDING",
        "Duration survival prob": "Duration P < threshold",
        "Liquidity score": "Liquidity < threshold",
        "Net APY": "Net APY < threshold",
        "Composite score": "Composite score < threshold",
    }

    categorized = Counter()
    for r in rejected:
        if r.rejection_reason:
            first_reason = r.rejection_reason.split(";")[0].strip()
            matched = False
            for prefix, label in gate_labels.items():
                if first_reason.startswith(prefix):
                    categorized[label] += 1
                    matched = True
                    break
            if not matched:
                categorized[first_reason] += 1

    for label, count in categorized.most_common():
        pct = count / len(results) * 100
        print(f"  {label:<40} {count:>10,} {pct:>7.1f}%")

    print(f"  {'─'*40} {'─'*10} {'─'*8}")
    pct_actionable = len(actionable) / len(results) * 100 if results else 0
    print(f"  {'PASSED ALL GATES':<40} {len(actionable):>10,} {pct_actionable:>7.1f}%")

    # --- Actionable breakdown ---
    if actionable:
        print(f"\n  ACTIONABLE SIGNALS BREAKDOWN:")
        print(f"  {'Asset':<10} {'Exchange':<14} {'Count':>8} {'Avg Score':>10} {'Avg Net APY':>12}")
        print(f"  {'-'*10} {'-'*14} {'-'*8} {'-'*10} {'-'*12}")

        by_pair: dict[tuple[str, str], list[ScoredSignal]] = defaultdict(list)
        for r in actionable:
            by_pair[(r.event.asset, r.event.exchange)].append(r)

        for (asset, exchange), signals in sorted(by_pair.items(), key=lambda x: -len(x[1])):
            avg_score = sum(s.composite_score for s in signals) / len(signals)
            avg_apy = sum(s.net_expected_apy for s in signals) / len(signals)
            print(f"  {asset:<10} {exchange:<14} {len(signals):>8} {avg_score:>10.1f} {avg_apy:>11.1f}%")

    # --- Top 10 ---
    print(f"\n  TOP 10 HISTORICAL SIGNALS (by composite score):")
    print(f"  {'Timestamp':<22} {'Asset':<8} {'Exchange':<12} {'Score':>6} {'Net APY':>9} {'P(≥15m)':>8} {'Liq':>5}")
    print(f"  {'-'*22} {'-'*8} {'-'*12} {'-'*6} {'-'*9} {'-'*8} {'-'*5}")

    top10 = sorted(results, key=lambda r: r.composite_score, reverse=True)[:10]
    for r in top10:
        ts = r.event.timestamp_utc.strftime("%Y-%m-%d %H:%M")
        print(
            f"  {ts:<22} {r.event.asset:<8} {r.event.exchange:<12} "
            f"{r.composite_score:>6.1f} {r.net_expected_apy:>8.1f}% "
            f"{r.duration_survival_prob:>7.2%} {r.liquidity_score:>5.2f}"
        )

    # --- Cross-exchange spread analysis (spot check on unique assets) ---
    print(f"\n  CROSS-EXCHANGE SPREAD ANALYSIS (live spot check):")
    spot_scorer = CompositeSignalScorer(duration_predictor, liquidity_scorer, adapter_dict)
    unique_assets = list({r.event.asset for r in results})
    spread_results = {}
    for asset in unique_assets[:6]:
        try:
            spread = await spot_scorer._compute_cross_exchange_spread(asset, "hyperliquid")
            spread_results[asset] = spread
        except Exception:
            spread_results[asset] = None

    spreads_found = {k: v for k, v in spread_results.items() if v is not None}
    print(f"  Assets with cross-exchange spread data: {len(spreads_found)}/{len(unique_assets)}")
    for asset, spread in sorted(spreads_found.items()):
        print(f"    {asset}: {spread:.2f}%")
    if not spreads_found:
        print("  WARNING: No cross-exchange spread data — symbol normalization may need more aliases")

    # --- Decision ---
    print()
    print("=" * 70)
    print(f"  ACTIONABLE RATE: {pct_actionable:.1f}%")

    if pct_actionable < 10:
        print("  → BELOW TARGET RANGE (10-40%)")
        print("  → Recommended: expand to cross-exchange scanning or loosen thresholds")
    elif pct_actionable > 40:
        print("  → ABOVE TARGET RANGE (10-40%)")
        print("  → Recommended: tighten thresholds and re-run")
    else:
        print("  → WITHIN TARGET RANGE (10-40%)")
        print("  → Recommended next build: EXECUTION LAYER")

    print("=" * 70)
    print()


if __name__ == "__main__":
    asyncio.run(main())
