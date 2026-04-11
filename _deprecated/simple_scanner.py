#!/usr/bin/env python3
"""
CEO OVERRIDE: Simple scanner that actually works.
Bypasses broken multi-factor engine.
"""

import json
import urllib.request

MIN_FUNDING_TIER1 = 0.75  # 75% annual (CEO: relaxed for capital utilization)
MIN_VOLUME_TIER1 = 500_000        # $500k (was $1M)
MIN_PREMIUM_TIER1 = -0.005        # -0.5% (was -1%)

MIN_PREMIUM_TIER2 = -0.025
MIN_VOLUME_TIER2 = 500_000

def scan_simple():
    """Scan for Tier 1 and Tier 2 signals using simple, direct rules."""
    
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
        
        # Tier 1: Strong funding
        if funding_annual >= MIN_FUNDING_TIER1 and premium < MIN_PREMIUM_TIER1 and volume >= MIN_VOLUME_TIER1:
            signals.append({
                "asset": asset,
                "direction": "long",
                "price": mid,
                "score": 7.5,  # Above threshold
                "signal_type": "funding_anomaly",
                "funding_8h": funding,
                "annualized_rate": funding_annual,
                "premium": premium,
                "volume_24h": volume,
                "tier": 1,
                "composite": {"premium": premium},
            })
        
        # Tier 2: Strong premium discount
        elif premium < MIN_PREMIUM_TIER2 and volume >= MIN_VOLUME_TIER2:
            signals.append({
                "asset": asset,
                "direction": "long",
                "price": mid,
                "score": 5.5,  # Lower than Tier 1
                "signal_type": "premium_reversion",
                "funding_8h": funding,
                "annualized_rate": funding_annual,
                "premium": premium,
                "volume_24h": volume,
                "tier": 2,
                "composite": {"premium": premium},
            })
    
    return signals

if __name__ == "__main__":
    signals = scan_simple()
    print(f"Found {len(signals)} signals:")
    for s in signals:
        tier = s.get('tier', 1)
        print(f"  Tier {tier}: {s['asset']:8s} score={s['score']:.1f} fund={s['annualized_rate']*100:.0f}% prem={s['premium']*100:+.2f}%")
