#!/usr/bin/env python3
"""
Daily Update: Progress report for 30-day capital doubling challenge.
Tracks capital, closed trades, win rate, and days remaining.
"""

import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Constants
START_DATE = datetime(2026, 3, 26, tzinfo=timezone.utc)
END_DATE = datetime(2026, 4, 25, tzinfo=timezone.utc)
START_CAPITAL = 97.14
TARGET_CAPITAL = 194.00
TRADE_LOGGER = Path(__file__).parent / "../workspace/logs/trade-lifecycle.jsonl"

def get_current_capital():
    """Get current capital from Hyperliquid API."""
    import urllib.request
    
    wallet = "0x8743f51c57e90644a0c141eD99064C4e9efFC01c"
    
    try:
        # Get spot balance
        resp = json.loads(urllib.request.urlopen(
            urllib.request.Request('https://api.hyperliquid.xyz/info',
                data=json.dumps({'type': 'spotClearinghouseState', 'user': wallet}).encode(),
                headers={'Content-Type': 'application/json'}),
            timeout=10
        ).read())
        
        spot = float(resp['balances'][0]['total'])
        
        # Get perp balance
        resp = json.loads(urllib.request.urlopen(
            urllib.request.Request('https://api.hyperliquid.xyz/info',
                data=json.dumps({'type': 'clearinghouseState', 'user': wallet}).encode(),
                headers={'Content-Type': 'application/json'}),
            timeout=10
        ).read())
        
        perp = float(resp['marginSummary']['accountValue'])
        
        return spot + perp
    except Exception as e:
        print(f"Error fetching capital: {e}")
        return None

def get_trade_stats():
    """Get trade statistics from trade logger."""
    if not TRADE_LOGGER.exists():
        return {"closed": 0, "wins": 0, "losses": 0, "win_rate": 0, "expectancy": 0}
    
    trades = []
    with TRADE_LOGGER.open("r") as f:
        for line in f:
            if line.strip():
                trades.append(json.loads(line))
    
    closed = [t for t in trades if t.get("exit_timestamp")]
    wins = [t for t in closed if t.get("total_pnl_usd", 0) > 0]
    losses = [t for t in closed if t.get("total_pnl_usd", 0) <= 0]
    
    win_rate = len(wins) / len(closed) if closed else 0
    
    if closed:
        avg_win = sum(t["total_pnl_usd"] for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t["total_pnl_usd"] for t in losses) / len(losses) if losses else 0
        expectancy = win_rate * avg_win + (1 - win_rate) * avg_loss
    else:
        expectancy = 0
    
    return {
        "closed": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": win_rate,
        "expectancy": expectancy,
    }

def generate_daily_update():
    """Generate daily progress report."""
    now = datetime.now(timezone.utc)
    days_elapsed = (now - START_DATE).days
    days_remaining = (END_DATE - now).days
    
    current_capital = get_current_capital()
    stats = get_trade_stats()
    
    print("=" * 70)
    print("  DAILY UPDATE — 30-DAY CAPITAL DOUBLING CHALLENGE")
    print("  " + now.strftime("%Y-%m-%d %H:%M UTC"))
    print("=" * 70)
    print()
    
    # Progress
    print("PROGRESS:")
    print(f"  Day {days_elapsed + 1} of 30 ({days_remaining} days remaining)")
    
    if current_capital:
        gain = current_capital - START_CAPITAL
        gain_pct = (gain / START_CAPITAL) * 100
        progress_to_target = ((current_capital - START_CAPITAL) / (TARGET_CAPITAL - START_CAPITAL)) * 100
        
        print(f"  Capital: ${current_capital:.2f} (started ${START_CAPITAL:.2f})")
        print(f"  Gain: ${gain:+.2f} ({gain_pct:+.1f}%)")
        print(f"  Target: ${TARGET_CAPITAL:.2f} (need ${TARGET_CAPITAL - current_capital:.2f} more)")
        print(f"  Progress: {progress_to_target:.1f}% toward target")
    else:
        print("  Capital: Unable to fetch (check connection)")
    
    print()
    
    # Validation Progress
    print("VALIDATION:")
    print(f"  Closed Trades: {stats['closed']} / 20 (need 20 for edge validation)")
    
    if stats['closed'] > 0:
        print(f"  Win Rate: {stats['win_rate']*100:.1f}% ({stats['wins']}W / {stats['losses']}L)")
        print(f"  Expectancy: ${stats['expectancy']:+.2f} per trade")
        
        if stats['closed'] >= 20:
            if stats['expectancy'] > 0.50 and stats['win_rate'] > 0.50:
                status = "✅ EDGE VALIDATED — Ready to scale"
            elif stats['expectancy'] > 0:
                status = "⚠️  WEAK EDGE — Consider optimization"
            else:
                status = "❌ NO EDGE — Strategy not working"
            print(f"  Status: {status}")
        else:
            print(f"  Status: ⏳ In progress (need {20 - stats['closed']} more trades)")
    else:
        print("  Status: ⏳ Waiting for first closed trade")
    
    print()
    
    # Daily Targets
    required_daily_gain = (TARGET_CAPITAL - (current_capital or START_CAPITAL)) / max(days_remaining, 1)
    required_daily_pct = (required_daily_gain / (current_capital or START_CAPITAL)) * 100
    
    print("REQUIRED DAILY PERFORMANCE:")
    print(f"  Need: ${required_daily_gain:+.2f}/day ({required_daily_pct:+.2f}% daily)")
    print(f"  To hit: ${TARGET_CAPITAL:.2f} by Day 30")
    
    print()
    
    # Week Targets
    if days_elapsed < 7:
        print("WEEK 1 TARGET (VALIDATION):")
        print("  Goal: 5-10 closed trades")
        print("  Focus: Prove edge exists")
        print(f"  Current: {stats['closed']} closed trades")
    elif days_elapsed < 14:
        print("WEEK 2 TARGET (CALIBRATION):")
        print("  Goal: 10-15 closed trades total")
        print("  Focus: Tier performance comparison")
        print(f"  Current: {stats['closed']} closed trades")
    elif days_elapsed < 21:
        print("WEEK 3 TARGET (SCALING):")
        print("  Goal: 20+ closed trades (edge validated)")
        print("  Focus: Increase position sizes")
        print(f"  Current: {stats['closed']} closed trades")
    else:
        print("WEEK 4 TARGET (COMPOUND):")
        print("  Goal: Deploy 100% capital")
        print("  Focus: Aggressive compounding")
        print(f"  Target: ${TARGET_CAPITAL:.2f} by end of week")
    
    print()
    print("=" * 70)
    
    # Next Actions
    print("NEXT ACTIONS:")
    
    if stats['closed'] < 20:
        print("  • System running autonomously (no manual intervention)")
        print("  • Wait for trades to close naturally via guardian")
        print(f"  • {20 - stats['closed']} more trades needed for validation")
    else:
        if stats['expectancy'] > 0.50 and stats['win_rate'] > 0.50:
            print("  • ✅ Edge validated — UNLOCK optimization")
            print("  • Scale position sizes (Tier 1 $15→$18, Tier 2 $8→$10)")
            print("  • Consider adding 4th concurrent position")
        else:
            print("  • ⚠️  Review performance data")
            print("  • Analyze what's not working")
            print("  • Consider threshold adjustments or strategy pivot")
    
    print()
    print("Dashboard: https://ats-dashboard-omega.vercel.app")
    print("=" * 70)

if __name__ == "__main__":
    generate_daily_update()
