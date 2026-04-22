#!/usr/bin/env python3
"""
REGIME DETECTOR — Classifies market funding-rate regime.

Fetches current funding rates for all Hyperliquid perp markets and classifies
the market into one of 4 regimes: EXTREME, HIGH_FUNDING, MODERATE, LOW_FUNDING.

Writes state to workspace/regime_state.json so the engine and scanner can
read regime-aware thresholds.

Usage:
    python3 scripts/regime_detector.py          # Print current regime + metrics
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.runtime import WORKSPACE_ROOT
from config.regime_thresholds import (
    EXTREME_PCT_ABOVE_100,
    HIGH_FUNDING_MIN_MAX_APY,
    MODERATE_MIN_MAX_APY,
    DEFAULT_REGIME,
    REGIME_STALE_SECONDS,
    REGIME_EXIT_THRESHOLDS,
    get_regime_thresholds,
)

REGIME_STATE_FILE = WORKSPACE_ROOT / "regime_state.json"

# Ordered from lowest to highest severity
REGIME_ORDER = ["LOW_FUNDING", "MODERATE", "HIGH_FUNDING", "EXTREME"]


def compute_regime_metrics(asset_funding: list[dict]) -> dict:
    """Compute regime classification metrics from asset funding data.

    Args:
        asset_funding: list of dicts with keys 'asset' and 'funding_apy'
                       (annualized, as decimal — e.g. 1.50 = 150% APY).
                       Only negative funding (long opportunities) should be
                       included, with funding_apy as the absolute value.

    Returns:
        dict with regime metrics.
    """
    if not asset_funding:
        return {
            "max_funding_apy": 0.0,
            "avg_top10_funding_apy": 0.0,
            "pct_above_50": 0.0,
            "pct_above_100": 0.0,
            "top_assets": [],
        }

    total_assets = len(asset_funding)
    sorted_by_apy = sorted(asset_funding, key=lambda x: x["funding_apy"], reverse=True)

    max_funding_apy = sorted_by_apy[0]["funding_apy"]
    top10 = sorted_by_apy[:10]
    avg_top10 = sum(a["funding_apy"] for a in top10) / len(top10)

    above_50 = sum(1 for a in asset_funding if a["funding_apy"] >= 0.50)
    above_100 = sum(1 for a in asset_funding if a["funding_apy"] >= 1.00)

    pct_above_50 = above_50 / total_assets if total_assets > 0 else 0.0
    pct_above_100 = above_100 / total_assets if total_assets > 0 else 0.0

    top_assets = [
        {"asset": a["asset"], "funding_apy": round(a["funding_apy"], 4)}
        for a in sorted_by_apy[:5]
    ]

    return {
        "max_funding_apy": round(max_funding_apy, 4),
        "avg_top10_funding_apy": round(avg_top10, 4),
        "pct_above_50": round(pct_above_50, 4),
        "pct_above_100": round(pct_above_100, 4),
        "top_assets": top_assets,
    }


def classify_regime(metrics: dict) -> str:
    """Classify market regime from metrics.

    Returns one of: EXTREME, HIGH_FUNDING, MODERATE, LOW_FUNDING.
    """
    if metrics["pct_above_100"] >= EXTREME_PCT_ABOVE_100:
        return "EXTREME"
    elif metrics["max_funding_apy"] >= HIGH_FUNDING_MIN_MAX_APY:
        return "HIGH_FUNDING"
    elif metrics["max_funding_apy"] >= MODERATE_MIN_MAX_APY:
        return "MODERATE"
    else:
        return "LOW_FUNDING"


def apply_hysteresis(previous_regime: str, metrics: dict) -> str:
    """Apply hysteresis to regime classification.

    Quick to upgrade (catch spikes fast), slow to downgrade (avoid flapping).

    - If raw regime is HIGHER than previous → upgrade immediately.
    - If raw regime equals previous → no change.
    - If raw regime is LOWER than previous → only downgrade if metrics
      dropped below the EXIT threshold for the current regime.
    """
    raw_regime = classify_regime(metrics)

    prev_idx = REGIME_ORDER.index(previous_regime) if previous_regime in REGIME_ORDER else 0
    raw_idx = REGIME_ORDER.index(raw_regime)

    # Upgrade or same → use raw classification
    if raw_idx >= prev_idx:
        return raw_regime

    # Downgrade path: check exit thresholds level by level from current down
    new_idx = prev_idx
    for level in range(prev_idx, 0, -1):
        regime_at_level = REGIME_ORDER[level]
        exit_thresh = REGIME_EXIT_THRESHOLDS.get(regime_at_level, {})

        should_exit = False
        if "pct_above_100" in exit_thresh:
            if metrics["pct_above_100"] < exit_thresh["pct_above_100"]:
                should_exit = True
        elif "max_funding_apy" in exit_thresh:
            if metrics["max_funding_apy"] < exit_thresh["max_funding_apy"]:
                should_exit = True
        else:
            should_exit = False

        if should_exit:
            new_idx = level - 1
        else:
            break  # Can't exit this level, so stay here

    return REGIME_ORDER[new_idx]


def detect_regime_from_api_response(resp: list) -> dict:
    """Run regime detection on a raw Hyperliquid metaAndAssetCtxs response.

    This is the integration point for trading_engine.py — reuses the API
    response that tiered_scanner already fetches, avoiding double API calls.

    Args:
        resp: raw response from metaAndAssetCtxs (list of [meta, assetCtxs])

    Returns:
        dict with regime, metrics, and thresholds.
    """
    asset_funding = []
    for u, ctx in zip(resp[0]["universe"], resp[1]):
        funding = float(ctx.get("funding", 0) or 0)
        if funding < 0:  # Only negative funding (long opportunities)
            # D43: HL `funding` is per-hour, not per-8h → × 24 × 365 = × 8760
            apy = abs(funding) * 24 * 365
            asset_funding.append({"asset": u["name"], "funding_apy": apy})

    metrics = compute_regime_metrics(asset_funding)

    # Apply hysteresis: read previous regime, use asymmetric thresholds
    previous_state = load_regime_state()
    previous_regime = previous_state.get("regime", "LOW_FUNDING") if previous_state else "LOW_FUNDING"
    regime = apply_hysteresis(previous_regime, metrics)
    thresholds = get_regime_thresholds(regime)

    return {
        "regime": regime,
        "raw_regime": classify_regime(metrics),
        "previous_regime": previous_regime,
        **metrics,
        "thresholds": thresholds,
    }


def load_regime_state() -> dict | None:
    """Load regime state from disk. Returns None if missing or stale."""
    if not REGIME_STATE_FILE.exists():
        return None

    try:
        state = json.loads(REGIME_STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return None

    # Check staleness
    updated_at = state.get("updated_at")
    if not updated_at:
        return None

    try:
        updated = datetime.fromisoformat(updated_at)
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - updated).total_seconds()
        if age > REGIME_STALE_SECONDS:
            return None
    except (ValueError, TypeError):
        return None

    return state


def save_regime_state(regime_result: dict, scan_count: int | None = None) -> dict:
    """Write regime state to disk.

    Args:
        regime_result: output from detect_regime_from_api_response()
        scan_count: optional scan counter (auto-incremented from previous state)

    Returns:
        The full state dict that was written.
    """
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    # Load previous state for scan_count, duration, and transition tracking
    prev = load_regime_state()
    if scan_count is None:
        scan_count = (prev.get("scan_count", 0) + 1) if prev else 1

    # Duration tracking: how long the current regime has been active
    new_regime = regime_result["regime"]
    if prev and prev.get("regime") == new_regime:
        # Same regime — carry forward the regime_since timestamp
        regime_since = prev.get("regime_since", now_iso)
    else:
        # New regime — reset timestamp
        regime_since = now_iso

    # Compute regime_duration_seconds from regime_since
    try:
        since_dt = datetime.fromisoformat(regime_since)
        if since_dt.tzinfo is None:
            since_dt = since_dt.replace(tzinfo=timezone.utc)
        regime_duration_seconds = round((now - since_dt).total_seconds())
    except (ValueError, TypeError):
        regime_duration_seconds = 0

    # Transition counter: count transitions in the last 24 hours
    transition_log: list[str] = prev.get("transition_log", []) if prev else []

    # Record new transition if regime changed
    if prev and prev.get("regime") != new_regime:
        transition_log.append(now_iso)

    # Prune transitions older than 24 hours
    cutoff = (now - timedelta(hours=24)).isoformat()
    transition_log = [t for t in transition_log if t > cutoff]

    state = {
        "regime": new_regime,
        "max_funding_apy": regime_result["max_funding_apy"],
        "avg_top10_funding_apy": regime_result["avg_top10_funding_apy"],
        "pct_above_50": regime_result["pct_above_50"],
        "pct_above_100": regime_result["pct_above_100"],
        "top_assets": regime_result["top_assets"],
        "updated_at": now_iso,
        "scan_count": scan_count,
        "regime_since": regime_since,
        "regime_duration_seconds": regime_duration_seconds,
        "transitions_last_24h": len(transition_log),
        "transition_log": transition_log,
    }

    if len(transition_log) > 10:
        import logging
        logging.getLogger(__name__).warning(
            "High regime transition rate: %d transitions in last 24h — "
            "consider widening hysteresis buffer",
            len(transition_log),
        )

    REGIME_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    REGIME_STATE_FILE.write_text(json.dumps(state, indent=2))
    return state


def get_active_regime() -> str:
    """Get the current active regime. Falls back to DEFAULT_REGIME if stale/missing."""
    state = load_regime_state()
    if state is None:
        return DEFAULT_REGIME
    return state.get("regime", DEFAULT_REGIME)


def get_active_thresholds() -> dict:
    """Get scanner thresholds for the current active regime.

    This is the primary interface for tiered_scanner.py.
    Falls back to HIGH_FUNDING defaults if regime state is stale/missing.
    """
    regime = get_active_regime()
    return get_regime_thresholds(regime)


# ---------------------------------------------------------------------------
# Standalone execution: fetch from API and print
# ---------------------------------------------------------------------------

def _fetch_and_detect() -> dict:
    """Fetch funding data from Hyperliquid API and run detection."""
    import urllib.request

    resp = json.loads(urllib.request.urlopen(
        urllib.request.Request(
            "https://api.hyperliquid.xyz/info",
            data=json.dumps({"type": "metaAndAssetCtxs"}).encode(),
            headers={"Content-Type": "application/json"},
        ),
        timeout=10,
    ).read())

    return detect_regime_from_api_response(resp)


def _format_duration(seconds: int) -> str:
    """Format seconds as human-readable duration."""
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    remaining_min = minutes % 60
    if hours < 24:
        return f"{hours}h {remaining_min}m"
    days = hours // 24
    remaining_hours = hours % 24
    return f"{days}d {remaining_hours}h"


def main():
    """Run standalone regime detection."""
    result = _fetch_and_detect()
    state = save_regime_state(result)

    regime = result["regime"]
    raw_regime = result.get("raw_regime", regime)
    thresholds = result["thresholds"]

    print("=" * 60)
    print(f"  REGIME: {regime}")
    if raw_regime != regime:
        print(f"  (raw classification: {raw_regime}, held by hysteresis)")
    print("=" * 60)
    print()
    print("  Metrics:")
    print(f"    Max funding APY:      {result['max_funding_apy'] * 100:>6.1f}%")
    print(f"    Avg top-10 APY:       {result['avg_top10_funding_apy'] * 100:>6.1f}%")
    print(f"    Assets above 50% APY: {result['pct_above_50'] * 100:>6.1f}%")
    print(f"    Assets above 100% APY:{result['pct_above_100'] * 100:>6.1f}%")
    print()
    print("  Top assets:")
    for a in result["top_assets"]:
        print(f"    {a['asset']:12s} {a['funding_apy'] * 100:>6.1f}% APY")
    print()
    print("  Hysteresis state:")
    duration = state.get("regime_duration_seconds", 0)
    print(f"    Current regime since:  {state.get('regime_since', 'N/A')}")
    print(f"    Regime duration:       {_format_duration(duration)}")
    print(f"    Transitions (24h):     {state.get('transitions_last_24h', 0)}")
    print()
    print("  Active thresholds:")
    print(f"    Tier 1 min funding:   {thresholds['tier1_min_funding'] * 100:>6.0f}% APY")
    print(f"    Tier 2 min funding:   {thresholds['tier2_min_funding'] * 100:>6.0f}% APY")
    print(f"    Max concurrent:       {thresholds['max_concurrent']}")
    print()
    print(f"  State written to: {REGIME_STATE_FILE}")
    print(f"  Scan count: {state['scan_count']}")


if __name__ == "__main__":
    main()
