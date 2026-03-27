#!/usr/bin/env python3
"""
TIERED CAPITAL ALLOCATION SCANNER
Classifies signals by strength and assigns appropriate position size.
"""

import json
import urllib.request

# TIER 1: High Conviction
TIER1_MIN_FUNDING = 1.50  # 150% annual
TIER1_MIN_PREMIUM = -0.01  # -1%
TIER1_MIN_VOLUME = 1_000_000
TIER1_POSITION_SIZE = 15.0

# TIER 2: Medium Conviction
TIER2_MIN_FUNDING = 0.75  # 75% annual
TIER2_MIN_PREMIUM = -0.005  # -0.5%
TIER2_MIN_VOLUME = 500_000
TIER2_POSITION_SIZE = 8.0

# TIER 3: Reject
# Anything below Tier 2 thresholds = no trade

def classify_signal(funding_annual, premium, volume):
    """Classify signal into Tier 1, 2, or 3 and return position size."""
    
    # Tier 1: Highest conviction
    if funding_annual >= TIER1_MIN_FUNDING and premium < TIER1_MIN_PREMIUM and volume >= TIER1_MIN_VOLUME:
        return 1, TIER1_POSITION_SIZE
    
    # Tier 2: Medium conviction
    elif funding_annual >= TIER2_MIN_FUNDING and premium < TIER2_MIN_PREMIUM and volume >= TIER2_MIN_VOLUME:
        return 2, TIER2_POSITION_SIZE
    
    # Tier 3: Reject
    else:
        return 3, 0.0

def scan_tiered():
    """Scan for signals with tiered classification."""
    
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
        
        # Classify
        tier, position_size = classify_signal(funding_annual, premium, volume)
        
        # Skip Tier 3
        if tier == 3:
            continue
        
        # Calculate score (higher = better)
        # Tier 1 gets base score 7.5, Tier 2 gets 5.5
        base_score = 7.5 if tier == 1 else 5.5
        
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
            "position_size_usd": position_size,  # KEY: dynamic sizing
            "composite": {"premium": premium},
        })
    
    # Sort by tier (1 first), then by score
    signals.sort(key=lambda x: (x['tier'], -x['score']))
    
    return signals

if __name__ == "__main__":
    signals = scan_tiered()
    
    tier1 = [s for s in signals if s['tier'] == 1]
    tier2 = [s for s in signals if s['tier'] == 2]
    
    print(f"=== TIERED SIGNAL SCAN ===")
    print()
    print(f"Tier 1 (High Conviction — ${TIER1_POSITION_SIZE} each): {len(tier1)}")
    for s in tier1:
        print(f"  {s['asset']:8s} fund={s['annualized_rate']*100:>5.0f}% prem={s['premium']*100:>+5.1f}% vol=${s['volume_24h']/1e6:>4.1f}M")
    
    print()
    print(f"Tier 2 (Medium Conviction — ${TIER2_POSITION_SIZE} each): {len(tier2)}")
    for s in tier2:
        print(f"  {s['asset']:8s} fund={s['annualized_rate']*100:>5.0f}% prem={s['premium']*100:>+5.1f}% vol=${s['volume_24h']/1e6:>4.1f}M")
    
    print()
    print(f"Total tradeable: {len(signals)}")
    print(f"Max capital if all entered: Tier1=${len(tier1)*TIER1_POSITION_SIZE:.0f} + Tier2=${len(tier2)*TIER2_POSITION_SIZE:.0f} = ${len(tier1)*TIER1_POSITION_SIZE + len(tier2)*TIER2_POSITION_SIZE:.0f}")
