#!/usr/bin/env python3
"""
Live Position Monitor — 10-minute micro-control loop.
Checks position, funding, momentum, and fires override alerts.

Usage:
    python3 scripts/live-monitor.py          # Single check
    python3 scripts/live-monitor.py --loop   # Continuous 10-min loop
"""

import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LOGS_DIR = REPO_ROOT / "workspace" / "logs"
MONITOR_LOG = LOGS_DIR / "live-monitor.jsonl"

# Override thresholds
FUNDING_FLIP_THRESHOLD = 0.0     # Exit if funding goes positive
VOLUME_SPIKE_MULTIPLIER = 2.0    # Alert if volume > 2x baseline
MOMENTUM_BREAKDOWN_CANDLES = 3   # 3 consecutive red candles
MOMENTUM_BREAKDOWN_PCT = -1.0    # Each >1% drop
PREMIUM_FLIP_THRESHOLD = 0.01    # +1% premium = reversion gone
OI_DROP_ALERT_PCT = -15.0        # 15% OI drop
EARLY_EXIT_ROE = -0.05           # -5% ROE early exit if thesis weakening


def api_call(payload):
    req = urllib.request.Request(
        'https://api.hyperliquid.xyz/info',
        data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json'},
    )
    return json.loads(urllib.request.urlopen(req, timeout=10).read())


def get_wallet():
    from eth_account import Account
    return Account.from_key(os.environ['HL_PRIVATE_KEY']).address


def check_position():
    addr = get_wallet()

    # Position
    state = api_call({'type': 'clearinghouseState', 'user': addr})
    positions = state.get('assetPositions', [])
    if not positions:
        return {"status": "NO_POSITION", "alerts": []}

    pos = positions[0].get('position', {})
    coin = pos.get('coin', '?')
    entry = float(pos.get('entryPx', 0))
    roe = float(pos.get('returnOnEquity', 0))
    pnl = float(pos.get('unrealizedPnl', 0))
    size = float(pos.get('szi', 0))

    # Market data
    meta = api_call({'type': 'metaAndAssetCtxs'})
    ctx = None
    for u, c in zip(meta[0].get('universe', []), meta[1]):
        if u['name'] == coin:
            ctx = c
            break

    if not ctx:
        return {"status": "NO_MARKET_DATA", "alerts": []}

    funding = float(ctx.get('funding', 0) or 0)
    mid = float(ctx.get('midPx', 0) or 0)
    premium = float(ctx.get('premium', 0) or 0)
    volume = float(ctx.get('dayNtlVlm', 0) or 0)
    oi = float(ctx.get('openInterest', 0) or 0)
    annual = funding * 3 * 365 * 100

    # Recent candles (5-min, last 30 min)
    now = datetime.now(timezone.utc)
    candles = api_call({
        'type': 'candleSnapshot',
        'req': {
            'coin': coin,
            'interval': '5m',
            'startTime': int((now.timestamp() - 1800) * 1000),
            'endTime': int(now.timestamp() * 1000),
        }
    })

    alerts = []
    action = "HOLD"

    # Check 1: Funding flip
    if funding >= FUNDING_FLIP_THRESHOLD:
        alerts.append(f"🚨 FUNDING FLIPPED POSITIVE: {annual:+.0f}% annual")
        action = "EXIT"

    # Check 2: Momentum breakdown (3+ red candles >1% each)
    if len(candles) >= MOMENTUM_BREAKDOWN_CANDLES:
        recent = candles[-MOMENTUM_BREAKDOWN_CANDLES:]
        red_count = 0
        for c in recent:
            chg = (float(c['c']) - float(c['o'])) / float(c['o']) * 100
            if chg < MOMENTUM_BREAKDOWN_PCT:
                red_count += 1
        if red_count >= MOMENTUM_BREAKDOWN_CANDLES:
            alerts.append(f"🚨 MOMENTUM BREAKDOWN: {red_count} consecutive red candles >1%")
            if roe < EARLY_EXIT_ROE:
                action = "EXIT"

    # Check 3: Premium flip (reversion gone)
    if premium > PREMIUM_FLIP_THRESHOLD:
        alerts.append(f"⚠️ PREMIUM FLIPPED POSITIVE: {premium*100:+.2f}%")

    # Check 4: ROE danger zone
    if roe <= -0.08:
        alerts.append(f"🚨 ROE CRITICAL: {roe*100:+.2f}% — approaching stop-loss")
        action = "TIGHTEN"

    result = {
        "timestamp": now.isoformat(),
        "coin": coin,
        "entry": entry,
        "mid": mid,
        "roe": round(roe * 100, 2),
        "pnl": round(pnl, 4),
        "funding_annual": round(annual, 1),
        "premium_pct": round(premium * 100, 2),
        "volume_24h": round(volume),
        "oi": round(oi),
        "alerts": alerts,
        "action": action,
    }

    # Log
    MONITOR_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(MONITOR_LOG, "a") as f:
        f.write(json.dumps(result, default=str) + "\n")

    return result


def print_status(result):
    now = datetime.now(timezone.utc).strftime('%H:%M:%S UTC')
    coin = result.get('coin', '?')
    roe = result.get('roe', 0)
    pnl = result.get('pnl', 0)
    funding = result.get('funding_annual', 0)
    premium = result.get('premium_pct', 0)
    action = result.get('action', '?')
    alerts = result.get('alerts', [])

    status_emoji = "🟢" if roe > 0 else "🟡" if roe > -3 else "🔴"

    print(f"[{now}] {status_emoji} {coin} ROE:{roe:+.2f}% PnL:${pnl:+.4f} Fund:{funding:+.0f}%ann Prem:{premium:+.2f}% → {action}")

    for alert in alerts:
        print(f"  {alert}")

    if not alerts:
        print(f"  ✅ No alerts. Thesis intact.")


def main():
    loop = "--loop" in sys.argv

    if loop:
        print("Live Monitor — 10-minute loop (Ctrl+C to stop)")
        print("=" * 60)
        while True:
            try:
                result = check_position()
                print_status(result)

                if result.get("action") == "EXIT":
                    print("\n🚨🚨🚨 EXIT SIGNAL — MANUAL INTERVENTION REQUIRED 🚨🚨🚨")

                print()
                time.sleep(600)  # 10 minutes
            except KeyboardInterrupt:
                print("\nMonitor stopped.")
                break
            except Exception as e:
                print(f"  ❌ Error: {e}")
                time.sleep(60)
    else:
        result = check_position()
        print_status(result)


if __name__ == "__main__":
    main()
