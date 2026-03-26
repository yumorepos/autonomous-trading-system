#!/usr/bin/env python3
"""
Multi-Factor Signal Engine — Funding + Momentum + Volume.

Combines 3 lightweight signals into a composite score with confirmation logic.
Replaces the single-factor funding scanner in hl_entry.py.

Signals:
  1. FUNDING: Annualized funding rate anomaly (existing)
  2. MOMENTUM: 24h price change alignment with entry direction
  3. VOLUME: Daily volume relative to typical (liquidity confirmation)

Entry requires: composite_score >= threshold AND at least 2 of 3 signals agree.

Usage:
    from scripts.signal_engine import scan_multifactor_signals
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utils.api_connectivity import fetch_hyperliquid_meta

# ---------------------------------------------------------------------------
# Signal Weights (fixed — no optimization until 20+ trades)
# ---------------------------------------------------------------------------

W_FUNDING = 0.50      # Funding is the primary thesis
W_MOMENTUM = 0.30     # Momentum confirms direction
W_VOLUME = 0.20       # Volume confirms liquidity

# Thresholds
MIN_FUNDING_ANNUALIZED = 0.30     # 30% annualized (lowered from 50% for multi-factor)
MIN_VOLUME_24H = 300_000          # $300k daily volume
MIN_COMPOSITE_SCORE = 6.0         # Higher than old 5.0 — multi-factor should be more selective
MIN_CONFIRMATIONS = 2             # At least 2 of 3 signals must agree
MAX_SIGNALS = 3                   # Return top 3 candidates only

# Momentum
MOMENTUM_BULLISH_THRESHOLD = 0.005   # +0.5% 24h = bullish
MOMENTUM_BEARISH_THRESHOLD = -0.005  # -0.5% 24h = bearish

# Volume scoring: volume / $1M, capped at 5
VOLUME_NORM = 1_000_000
VOLUME_CAP = 5.0


# ---------------------------------------------------------------------------
# Individual Signal Computations
# ---------------------------------------------------------------------------

def compute_funding_signal(ctx: dict[str, Any]) -> dict[str, Any]:
    """Compute funding signal component."""
    funding = float(ctx.get("funding", 0) or 0)
    annualized = funding * 3 * 365  # 8h rate * 3 * 365

    if abs(annualized) < MIN_FUNDING_ANNUALIZED:
        return {"active": False, "score": 0, "direction": None, "annualized": annualized, "raw": funding}

    # Direction: negative funding → longs earn → signal long
    direction = "long" if funding < 0 else "short"

    # Score: how extreme is the funding? Capped at 10.
    raw_score = min(abs(annualized) * 2, 10.0)

    return {
        "active": True,
        "score": round(raw_score, 2),
        "direction": direction,
        "annualized": round(annualized, 4),
        "raw": funding,
    }


def compute_momentum_signal(ctx: dict[str, Any]) -> dict[str, Any]:
    """Compute 24h price momentum signal."""
    mid = float(ctx.get("midPx", 0) or 0)
    prev = float(ctx.get("prevDayPx", 0) or 0)

    if mid <= 0 or prev <= 0:
        return {"active": False, "score": 0, "direction": None, "change_pct": 0}

    change_pct = (mid - prev) / prev

    if change_pct > MOMENTUM_BULLISH_THRESHOLD:
        direction = "long"
    elif change_pct < MOMENTUM_BEARISH_THRESHOLD:
        direction = "short"
    else:
        # Flat — no momentum signal
        return {"active": False, "score": 0, "direction": None, "change_pct": round(change_pct, 6)}

    # Score: magnitude of move, capped at 10
    raw_score = min(abs(change_pct) * 100, 10.0)  # 10% move = score 10

    return {
        "active": True,
        "score": round(raw_score, 2),
        "direction": direction,
        "change_pct": round(change_pct, 6),
    }


def compute_volume_signal(ctx: dict[str, Any]) -> dict[str, Any]:
    """Compute volume/liquidity confirmation signal."""
    volume = float(ctx.get("dayNtlVlm", 0) or 0)

    if volume < MIN_VOLUME_24H:
        return {"active": False, "score": 0, "volume": volume}

    # Score: volume / $1M, capped
    raw_score = min(volume / VOLUME_NORM, VOLUME_CAP)

    return {
        "active": True,
        "score": round(raw_score, 2),
        "volume": volume,
        "above_1m": volume > 1_000_000,
    }


# ---------------------------------------------------------------------------
# Composite Scoring
# ---------------------------------------------------------------------------

def compute_composite(
    funding: dict[str, Any],
    momentum: dict[str, Any],
    volume: dict[str, Any],
) -> dict[str, Any]:
    """Combine 3 signals into composite score + confirmation count."""

    # Weighted score
    f_score = funding["score"] * W_FUNDING if funding["active"] else 0
    m_score = momentum["score"] * W_MOMENTUM if momentum["active"] else 0
    v_score = volume["score"] * W_VOLUME if volume["active"] else 0
    composite = f_score + m_score + v_score

    # Direction consensus
    f_dir = funding.get("direction")
    m_dir = momentum.get("direction")

    # Confirmation: how many signals agree on direction?
    confirmations = 0
    agreed_direction = None

    if f_dir:
        agreed_direction = f_dir
        confirmations += 1

    if m_dir:
        if agreed_direction is None:
            agreed_direction = m_dir
            confirmations += 1
        elif m_dir == agreed_direction:
            confirmations += 1
        else:
            # Momentum contradicts funding — reduce confidence
            composite *= 0.5

    # Volume is direction-agnostic — confirms if active
    if volume["active"]:
        confirmations += 1

    return {
        "composite_score": round(composite, 2),
        "confirmations": confirmations,
        "direction": agreed_direction,
        "funding_contribution": round(f_score, 2),
        "momentum_contribution": round(m_score, 2),
        "volume_contribution": round(v_score, 2),
        "momentum_aligned": m_dir == f_dir if (m_dir and f_dir) else None,
    }


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

def scan_multifactor_signals(existing_assets: set[str] | None = None) -> list[dict[str, Any]]:
    """Scan all Hyperliquid assets and return top multi-factor signals."""
    if existing_assets is None:
        existing_assets = set()

    result, universe, contexts = fetch_hyperliquid_meta(timeout=10)
    if not result.ok or not universe or not contexts:
        return []

    candidates = []
    now = datetime.now(timezone.utc)

    for asset, ctx in zip(universe, contexts):
        name = asset.get("name", "")
        if name in existing_assets:
            continue

        # Compute individual signals
        funding = compute_funding_signal(ctx)
        momentum = compute_momentum_signal(ctx)
        volume = compute_volume_signal(ctx)

        # Skip if funding signal not active (primary thesis)
        if not funding["active"]:
            continue

        composite = compute_composite(funding, momentum, volume)

        # Gate: minimum score
        if composite["composite_score"] < MIN_COMPOSITE_SCORE:
            continue

        # Gate: minimum confirmations
        if composite["confirmations"] < MIN_CONFIRMATIONS:
            continue

        # Gate: funding direction must align (Gate #11 built in)
        if composite["direction"] == "long" and funding["raw"] > 0:
            continue
        if composite["direction"] == "short" and funding["raw"] < 0:
            continue

        candidates.append({
            "asset": name,
            "direction": composite["direction"],
            "price": float(ctx.get("midPx", 0)),
            "composite_score": composite["composite_score"],
            "confirmations": composite["confirmations"],
            "signal_type": "multifactor",
            "strategy_tag": "funding_arb_mf",
            # Components for logging
            "funding": funding,
            "momentum": momentum,
            "volume": volume,
            "composite": composite,
            # Legacy compatibility
            "score": composite["composite_score"],
            "entry_price": float(ctx.get("midPx", 0)),
            "funding_rate_8h": funding["raw"],
            "annualized_rate": funding["annualized"],
            "volume_24h": volume.get("volume", 0),
            "scanned_at": now.isoformat(),
        })

    candidates.sort(key=lambda c: c["composite_score"], reverse=True)
    return candidates[:MAX_SIGNALS]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    print(f"\n{'='*60}")
    print(f"  MULTI-FACTOR SIGNAL SCAN")
    print(f"  {datetime.now(timezone.utc).isoformat()}")
    print(f"{'='*60}")
    print(f"\n  Weights: Funding={W_FUNDING} | Momentum={W_MOMENTUM} | Volume={W_VOLUME}")
    print(f"  Min score: {MIN_COMPOSITE_SCORE} | Min confirmations: {MIN_CONFIRMATIONS}/3")

    signals = scan_multifactor_signals()
    print(f"\n  Signals found: {len(signals)}\n")

    for s in signals:
        c = s["composite"]
        f = s["funding"]
        m = s["momentum"]
        v = s["volume"]
        print(f"  {s['asset']} — {s['direction'].upper()} @ ${s['price']:.4f}")
        print(f"    Composite: {c['composite_score']:.1f} ({c['confirmations']}/3 confirmed)")
        print(f"    Funding:   {f['annualized']:+.0%} ann. → {c['funding_contribution']:.1f}pts")
        print(f"    Momentum:  {m.get('change_pct', 0):+.2%} 24h → {c['momentum_contribution']:.1f}pts {'✅' if c.get('momentum_aligned') else '⚠️ not aligned' if c.get('momentum_aligned') is False else '—'}")
        print(f"    Volume:    ${v.get('volume', 0):,.0f} → {c['volume_contribution']:.1f}pts")
        print()

    if not signals:
        print("  No signals pass multi-factor gates.")
        print("  This is correct — better no trade than a bad trade.")


if __name__ == "__main__":
    main()
