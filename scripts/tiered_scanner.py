#!/usr/bin/env python3
"""
TIERED CAPITAL ALLOCATION SCANNER
Classifies signals by strength and assigns appropriate position size.

All thresholds imported from config/risk_params.py (single source of truth).
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


def classify_signal(funding_annual, premium, volume):
    """Classify signal into Tier 1, 2, or 3."""
    if funding_annual >= TIER1_MIN_FUNDING and premium < TIER1_MIN_PREMIUM and volume >= TIER1_MIN_VOLUME:
        return 1
    elif funding_annual >= TIER2_MIN_FUNDING and premium < TIER2_MIN_PREMIUM and volume >= TIER2_MIN_VOLUME:
        return 2
    else:
        return 3


def scan_tiered(account_balance: float = 95.0):
    """Scan for signals with tiered classification and capital-proportional sizing."""

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

        tier = classify_signal(funding_annual, premium, volume)

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
    signals = scan_tiered()

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
