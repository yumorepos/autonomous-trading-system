#!/usr/bin/env python3
"""
Phase 1: Autonomous Signal Generation Engine
Continuously scans financial sources for high-EV trading opportunities
Research & analysis only - no real trades
"""

import requests
import json
import sys
import os
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.runtime import WORKSPACE_ROOT as WORKSPACE, LOGS_DIR, DATA_DIR
from utils.json_utils import safe_read_jsonl
SIGNALS_FILE = LOGS_DIR / "phase1-signals.jsonl"
REPORT_FILE = WORKSPACE / "PHASE1_SIGNAL_REPORT.md"


def scan_hyperliquid_funding():
    """Scan Hyperliquid for funding rate arbitrage"""
    print("[STATS] Scanning Hyperliquid...")
    
    try:
        r = requests.post("https://api.hyperliquid.xyz/info",
                         json={"type": "metaAndAssetCtxs"}, timeout=10)
        data = r.json()
        universe = data[0]['universe']
        contexts = data[1]
        
        opportunities = []
        for asset, ctx in zip(universe, contexts):
            name = asset['name']
            funding = float(ctx.get('funding', 0))
            mark = float(ctx.get('markPx', 0))
            volume = float(ctx.get('dayNtlVlm', 0))
            oi = float(ctx.get('openInterest', 0)) * mark
            
            # Filter: liquid markets with extreme funding
            if volume > 500000 and oi > 200000:
                ann_funding = funding * 3 * 365 * 100
                if abs(ann_funding) > 10:
                    ev_score = abs(ann_funding) * (volume / 1000000)
                    
                    opportunities.append({
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'source': 'Hyperliquid',
                        'signal_type': 'funding_arbitrage',
                        'asset': name,
                        'direction': 'LONG' if funding < 0 else 'SHORT',
                        'entry_price': mark,
                        'funding_8h_pct': funding * 100,
                        'funding_annual_pct': ann_funding,
                        'volume_24h': volume,
                        'oi_usd': oi,
                        'ev_score': ev_score,
                        'conviction': 'HIGH' if ev_score > 80 else 'MEDIUM' if ev_score > 40 else 'LOW'
                    })
        
        opportunities.sort(key=lambda x: x['ev_score'], reverse=True)
        print(f"  Found {len(opportunities)} opportunities")
        return opportunities[:5]  # Top 5
        
    except Exception as e:
        print(f"  Error: {e}")
        return []


def scan_polymarket_spreads():
    """Scan Polymarket for wide spreads (arbitrage)"""
    print("[TARGET] Scanning Polymarket...")
    
    try:
        cutoff = int(datetime.now().timestamp() - 300)
        r = requests.get("https://data-api.polymarket.com/trades",
                        params={"min_timestamp": cutoff}, timeout=10)
        trades = r.json()
        
        markets = {}
        for trade in trades:
            mid = trade.get('slug') or trade.get('market')
            if mid:
                if mid not in markets:
                    markets[mid] = {'trades': [], 'title': trade.get('title', 'Unknown')}
                markets[mid]['trades'].append(trade)
        
        opportunities = []
        for mid, data in markets.items():
            if len(data['trades']) < 5:
                continue
            
            buys = [t['price'] for t in data['trades'] if t.get('side') == 'BUY']
            sells = [t['price'] for t in data['trades'] if t.get('side') == 'SELL']
            
            if buys and sells:
                best_bid = max(buys)
                best_ask = min(sells)
                spread = best_ask - best_bid
                
                if spread > 0.03:
                    ev_score = spread * 100
                    
                    opportunities.append({
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'source': 'Polymarket',
                        'signal_type': 'spread_arbitrage',
                        'market': data['title'][:60],
                        'bid': best_bid,
                        'ask': best_ask,
                        'spread_pct': spread * 100,
                        'ev_score': ev_score,
                        'conviction': 'HIGH' if spread > 0.05 else 'MEDIUM'
                    })
        
        opportunities.sort(key=lambda x: x['ev_score'], reverse=True)
        print(f"  Found {len(opportunities)} opportunities")
        return opportunities[:3]  # Top 3
        
    except Exception as e:
        print(f"  Error: {e}")
        return []


def calculate_position_sizing(signal, account_balance=97.80):
    """Calculate safe position size for paper trading"""
    if signal['conviction'] == 'HIGH':
        pct = 0.05  # 5%
    elif signal['conviction'] == 'MEDIUM':
        pct = 0.03  # 3%
    else:
        pct = 0.02  # 2%
    
    return {
        'position_size_usd': round(account_balance * pct, 2),
        'pct_of_account': pct * 100,
        'stop_loss_pct': 15 if signal['conviction'] == 'HIGH' else 10,
        'leverage': 2 if signal['conviction'] == 'HIGH' else 1
    }


def log_signals(signals):
    """Log signals to JSONL file"""
    SIGNALS_FILE.parent.mkdir(exist_ok=True)
    _ = safe_read_jsonl(SIGNALS_FILE)
    
    with open(SIGNALS_FILE, 'a') as f:
        for signal in signals:
            f.write(json.dumps(signal) + '\n')


def generate_report(signals):
    """Generate markdown report"""
    report = f"""# Phase 1 Signal Report -- Live Scan
**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M EDT')}  
**Mode:** Research Only (No Real Trades)

---

## TOP {len(signals)} SIGNALS (Ranked by EV)

"""
    
    for i, sig in enumerate(signals, 1):
        sizing = calculate_position_sizing(sig)
        
        report += f"""
### Signal #{i}: {sig.get('asset', sig.get('market', 'Unknown'))} {sig['signal_type'].replace('_', ' ').title()}
**EV Score:** {sig['ev_score']:.2f} | **Conviction:** {sig['conviction']}

**Strategy:** {sig['direction'] if 'direction' in sig else 'Arbitrage'}  
**Source:** {sig['source']}

**Entry:**
- Asset: {sig.get('asset', sig.get('market', 'N/A'))}
- Entry Price: ${sig.get('entry_price', sig.get('bid', 0)):.4f}
- Position Size: ${sizing['position_size_usd']} ({sizing['pct_of_account']}% of account)
- Leverage: {sizing['leverage']}x

**Exit:**
- Stop Loss: -{sizing['stop_loss_pct']}%
- Target: Profit when edge disappears

**Data:**
"""
        
        if 'funding_annual_pct' in sig:
            report += f"- Funding Rate: {sig['funding_8h_pct']:+.4f}% per 8h ({sig['funding_annual_pct']:+.0f}% annual)\n"
            report += f"- Volume: ${sig['volume_24h']/1e6:.1f}M\n"
            report += f"- OI: ${sig['oi_usd']/1e6:.1f}M\n"
        elif 'spread_pct' in sig:
            report += f"- Spread: {sig['spread_pct']:.2f}%\n"
            report += f"- Bid: {sig['bid']:.4f}\n"
            report += f"- Ask: {sig['ask']:.4f}\n"
        
        report += "\n---\n"
    
    report += f"""
## NEXT SCAN: 4 hours from now

**Status:** [OK] Research engine active  
**Signals This Scan:** {len(signals)}  
**Paper Trade Recommendation:** Top {min(2, len(signals))} signals

---

*Phase 1 = Research Only. No real capital at risk.*
"""
    
    with open(REPORT_FILE, 'w') as f:
        f.write(report)
    
    print(f"[REPORT] Report saved: {REPORT_FILE}")


def main():
    print("=" * 80)
    print("PHASE 1: AUTONOMOUS SIGNAL GENERATION ENGINE")
    print(f"Scan Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S EDT')}")
    print("=" * 80)
    print()
    
    # Scan all sources
    hl_signals = scan_hyperliquid_funding()
    pm_signals = scan_polymarket_spreads()
    
    # Combine and rank
    all_signals = hl_signals + pm_signals
    all_signals.sort(key=lambda x: x['ev_score'], reverse=True)
    
    # Take top 5
    top_signals = all_signals[:5]
    
    print()
    print(f"[STATS] Total Signals Found: {len(all_signals)}")
    print(f"[TARGET] Top Signals Selected: {len(top_signals)}")
    print()
    
    if top_signals:
        print("Top 3:")
        for i, sig in enumerate(top_signals[:3], 1):
            print(f"  {i}. {sig.get('asset', sig.get('market', 'Unknown'))} - EV: {sig['ev_score']:.2f} ({sig['conviction']})")
        
        # Log and report
        log_signals(top_signals)
        generate_report(top_signals)
        
        print()
        print("[OK] Scan complete")
    else:
        print("[WARN] No high-quality signals found this scan")
    
    print("=" * 80)


if __name__ == "__main__":
    main()
