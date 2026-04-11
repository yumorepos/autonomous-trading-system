#!/usr/bin/env python3
"""
TIERED CAPITAL ALLOCATION SCANNER
Classifies signals by strength and assigns appropriate position size.

All thresholds imported from config/risk_params.py (single source of truth).
Supports dynamic thresholds from regime detector (overrides static defaults).
"""

import json
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.risk_params import (
    TIER1_MIN_FUNDING, TIER1_MIN_PREMIUM, TIER1_MIN_VOLUME,
    TIER2_MIN_FUNDING, TIER2_MIN_PREMIUM, TIER2_MIN_VOLUME,
    calculate_position_size,
)


def classify_signal(funding_annual, premium, volume,
                    tier1_min_funding=None, tier2_min_funding=None):
    """Classify signal into Tier 1, 2, or 3.

    Args:
        funding_annual: annualized funding rate (decimal, e.g. 1.0 = 100%)
        premium: premium as decimal (e.g. -0.01 = -1%)
        volume: 24h volume in USD
        tier1_min_funding: override for Tier 1 funding threshold (from regime)
        tier2_min_funding: override for Tier 2 funding threshold (from regime)
    """
    t1_funding = tier1_min_funding if tier1_min_funding is not None else TIER1_MIN_FUNDING
    t2_funding = tier2_min_funding if tier2_min_funding is not None else TIER2_MIN_FUNDING

    if funding_annual >= t1_funding and premium < TIER1_MIN_PREMIUM and volume >= TIER1_MIN_VOLUME:
        return 1
    elif funding_annual >= t2_funding and premium < TIER2_MIN_PREMIUM and volume >= TIER2_MIN_VOLUME:
        return 2
    else:
        return 3


def scan_tiered(account_balance: float = 95.0, regime_thresholds: dict | None = None):
    """Scan for signals with tiered classification and capital-proportional sizing.

    Args:
        account_balance: current account balance in USD
        regime_thresholds: optional dict with keys 'tier1_min_funding',
                          'tier2_min_funding', 'max_concurrent' from regime detector.
                          If None, uses static defaults from risk_params.
    """
    t1_funding = None
    t2_funding = None
    if regime_thresholds:
        t1_funding = regime_thresholds.get("tier1_min_funding")
        t2_funding = regime_thresholds.get("tier2_min_funding")

    resp = json.loads(urllib.request.urlopen(
        urllib.request.Request('https://api.hyperliquid.xyz/info',
            data=json.dumps({'type': 'metaAndAssetCtxs'}).encode(),
            headers={'Content-Type': 'application/json'}),
        timeout=10
    ).read())

    signals = []

    for u, ctx in zip(resp[0]['universe'], resp[1]):
        asset = u['name']
        premium = float(ctx.get('premium', 0) or 0)
        funding = float(ctx.get('funding', 0) or 0)
        volume = float(ctx.get('dayNtlVlm', 0) or 0)
        mid = float(ctx.get('midPx', 0) or 0)
        funding_annual = abs(funding) * 3 * 365

        # Skip if funding is positive (we'd pay, not earn)
        if funding >= 0:
            continue

        tier = classify_signal(funding_annual, premium, volume,
                               tier1_min_funding=t1_funding,
                               tier2_min_funding=t2_funding)

        # Skip Tier 3
        if tier == 3:
            continue

        base_score = 7.5 if tier == 1 else 5.5
        position_size = calculate_position_size(account_balance, tier)

        signals.append({
            "asset": asset,
            "direction": "long",
            "price": mid,
            "score": base_score,
            "signal_type": "funding_arbitrage" if tier == 1 else "moderate_funding",
            "funding_8h": funding,
            "annualized_rate": funding_annual,
            "premium": premium,
            "volume_24h": volume,
            "tier": tier,
            "position_size_usd": position_size,
            "composite": {"premium": premium},
        })

    # Sort by tier (1 first), then by score
    signals.sort(key=lambda x: (x['tier'], -x['score']))

    return signals

if __name__ == "__main__":
    # When run standalone, use regime-aware thresholds if available
    from scripts.regime_detector import get_active_thresholds
    thresholds = get_active_thresholds()
    signals = scan_tiered(regime_thresholds=thresholds)

    tier1 = [s for s in signals if s['tier'] == 1]
    tier2 = [s for s in signals if s['tier'] == 2]

    print("=== TIERED SIGNAL SCAN ===")
    print()
    print(f"Tier 1 (High Conviction): {len(tier1)}")
    for s in tier1:
        print(f"  {s['asset']:8s} fund={s['annualized_rate']*100:>5.0f}% prem={s['premium']*100:>+5.1f}% vol=${s['volume_24h']/1e6:>4.1f}M  size=${s['position_size_usd']:.2f}")

    print()
    print(f"Tier 2 (Medium Conviction): {len(tier2)}")
    for s in tier2:
        print(f"  {s['asset']:8s} fund={s['annualized_rate']*100:>5.0f}% prem={s['premium']*100:>+5.1f}% vol=${s['volume_24h']/1e6:>4.1f}M  size=${s['position_size_usd']:.2f}")

    print()
    total_capital = sum(s['position_size_usd'] for s in signals)
    print(f"Total tradeable: {len(signals)} (${total_capital:.0f} total)")
