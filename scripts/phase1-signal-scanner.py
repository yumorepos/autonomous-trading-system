#!/usr/bin/env python3
"""
Phase 1 signal generation engine.
Produces canonical paper-trading signals for Hyperliquid and Polymarket within
one shared scanner architecture. Mixed mode remains a limited deterministic
one-entry-per-cycle evaluation path.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.runtime import (
    WORKSPACE_ROOT as WORKSPACE,
    LOGS_DIR,
    TRADING_MODE,
    mode_includes_hyperliquid,
    mode_includes_polymarket,
)
from utils.api_connectivity import fetch_hyperliquid_meta, fetch_polymarket_markets
from utils.json_utils import safe_read_jsonl
from utils.runtime_logging import append_runtime_event

SIGNALS_FILE = LOGS_DIR / "phase1-signals.jsonl"
REPORT_FILE = WORKSPACE / "PHASE1_SIGNAL_REPORT.md"


CANONICAL_POSITION_SIZES = {
    'Hyperliquid': 1.96,
    'Polymarket': 5.00,
}


def trading_mode_summary() -> str:
    return (
        "Hyperliquid only"
        if TRADING_MODE == 'hyperliquid_only'
        else "Polymarket only"
        if TRADING_MODE == 'polymarket_only'
        else "Mixed Hyperliquid + Polymarket"
    )



def scan_hyperliquid_funding() -> list[dict]:
    """Scan Hyperliquid for funding rate arbitrage signals."""
    print("[SCAN] Scanning Hyperliquid...")

    result, universe, contexts = fetch_hyperliquid_meta(timeout=10)
    if not result.ok:
        message = f"Hyperliquid scan error: {result.error}"
        print(f"  {message}")
        append_runtime_event(
            stage="signal_scanner",
            exchange="Hyperliquid",
            lifecycle_stage="scan",
            status="ERROR",
            message=message,
            metadata=result.to_dict(),
        )
        return []

    opportunities = []
    for asset, ctx in zip(universe, contexts):
        name = asset['name']
        funding = float(ctx.get('funding', 0))
        mark = float(ctx.get('markPx', 0))
        volume = float(ctx.get('dayNtlVlm', 0))
        oi = float(ctx.get('openInterest', 0)) * mark

        if volume <= 500000 or oi <= 200000 or mark <= 0:
            continue

        ann_funding = funding * 3 * 365 * 100
        if abs(ann_funding) <= 10:
            continue

        ev_score = abs(ann_funding) * (volume / 1_000_000)
        conviction = 'HIGH' if ev_score > 80 else 'MEDIUM' if ev_score > 40 else 'LOW'
        opportunities.append({
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'source': 'Hyperliquid',
            'exchange': 'Hyperliquid',
            'signal_type': 'funding_arbitrage',
            'strategy': 'funding_arbitrage',
            'asset': name,
            'symbol': name,
            'direction': 'LONG' if funding < 0 else 'SHORT',
            'entry_price': mark,
            'funding_8h_pct': funding * 100,
            'funding_annual_pct': ann_funding,
            'volume_24h': volume,
            'oi_usd': oi,
            'ev_score': ev_score,
            'conviction': conviction,
            'recommended_position_size_usd': CANONICAL_POSITION_SIZES['Hyperliquid'],
            'paper_only': True,
            'experimental': False,
        })

    opportunities.sort(key=lambda x: x['ev_score'], reverse=True)
    print(f"  Found {len(opportunities)} Hyperliquid opportunities")
    append_runtime_event(
        stage="signal_scanner",
        exchange="Hyperliquid",
        lifecycle_stage="scan",
        status="INFO",
        message=f"Hyperliquid scan completed with {len(opportunities[:5])} paper-trading signal(s)",
        metadata={**result.to_dict(), "signals_generated": len(opportunities[:5])},
    )
    return opportunities[:5]



def _token_book(token: dict) -> tuple[float, float, float]:
    bid = float(token.get('bestBid') or token.get('bid') or token.get('price') or 0)
    ask = float(token.get('bestAsk') or token.get('ask') or token.get('price') or bid or 0)
    last = float(token.get('price') or token.get('lastPrice') or ask or bid or 0)
    return bid, ask, last



def scan_polymarket_markets() -> list[dict]:
    """Scan Polymarket Gamma markets and emit executable paper-trading signals."""
    print("[SCAN] Scanning Polymarket...")

    result, markets = fetch_polymarket_markets(timeout=10, limit=100, closed=False)
    if not result.ok:
        message = f"Polymarket scan error: {result.error}"
        print(f"  {message}")
        append_runtime_event(
            stage="signal_scanner",
            exchange="Polymarket",
            lifecycle_stage="scan",
            status="ERROR",
            message=message,
            metadata=result.to_dict(),
        )
        return []

    opportunities: list[dict] = []
    for market in markets:
        tokens = market.get('tokens') or []
        if len(tokens) < 2:
            continue

        liquidity = float(
            market.get('liquidity')
            or market.get('liquidityNum')
            or market.get('volume')
            or market.get('volumeNum')
            or 0
        )
        if liquidity < 1000:
            continue

        token_signals = []
        for token in tokens:
            outcome = str(token.get('outcome') or '').upper()
            if outcome not in {'YES', 'NO'}:
                continue
            bid, ask, last = _token_book(token)
            if ask <= 0 or bid < 0 or last <= 0:
                continue
            spread_pct = ((ask - bid) / ask) * 100 if ask else 0
            edge_score = max(0.0, (0.55 - ask)) * 100 + min(spread_pct, 10)
            token_signals.append({
                'outcome': outcome,
                'token_id': str(token.get('token_id') or token.get('tokenId') or token.get('id') or outcome),
                'best_bid': bid,
                'best_ask': ask,
                'last_price': last,
                'spread_pct': spread_pct,
                'edge_score': edge_score,
            })

        if not token_signals:
            continue

        best = max(token_signals, key=lambda token: token['edge_score'])
        ev_score = best['edge_score'] + min(liquidity / 50_000, 10)
        conviction = 'HIGH' if ev_score >= 12 else 'MEDIUM' if ev_score >= 6 else 'LOW'
        market_id = str(market.get('conditionId') or market.get('condition_id') or market.get('id') or market.get('slug') or market.get('question'))
        question = str(market.get('question') or market.get('title') or market.get('slug') or market_id)
        opportunities.append({
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'source': 'Polymarket',
            'exchange': 'Polymarket',
            'signal_type': 'polymarket_binary_market',
            'strategy': 'polymarket_spread',
            'asset': market_id,
            'symbol': market_id,
            'market_id': market_id,
            'market_question': question,
            'side': best['outcome'],
            'direction': best['outcome'],
            'token_id': best['token_id'],
            'entry_price': best['best_ask'],
            'best_bid': best['best_bid'],
            'best_ask': best['best_ask'],
            'last_price': best['last_price'],
            'spread_pct': best['spread_pct'],
            'liquidity_usd': liquidity,
            'ev_score': ev_score,
            'conviction': conviction,
            'recommended_position_size_usd': CANONICAL_POSITION_SIZES['Polymarket'],
            'paper_only': True,
            'experimental': False,
        })

    opportunities.sort(key=lambda x: x['ev_score'], reverse=True)
    print(f"  Found {len(opportunities)} Polymarket opportunities")
    append_runtime_event(
        stage="signal_scanner",
        exchange="Polymarket",
        lifecycle_stage="scan",
        status="INFO",
        message=f"Polymarket scan completed with {len(opportunities[:5])} paper-trading signal(s)",
        metadata={**result.to_dict(), "signals_generated": len(opportunities[:5])},
    )
    return opportunities[:5]



def calculate_position_sizing(signal: dict, account_balance: float = 97.80) -> dict:
    if signal['exchange'] == 'Polymarket':
        pct = signal.get('recommended_position_size_usd', CANONICAL_POSITION_SIZES['Polymarket']) / account_balance
        stop_loss_pct = 5
        leverage = 1
    elif signal['conviction'] == 'HIGH':
        pct = 0.05
        stop_loss_pct = 15
        leverage = 2
    elif signal['conviction'] == 'MEDIUM':
        pct = 0.03
        stop_loss_pct = 10
        leverage = 1
    else:
        pct = 0.02
        stop_loss_pct = 10
        leverage = 1

    return {
        'position_size_usd': round(account_balance * pct, 2),
        'pct_of_account': pct * 100,
        'stop_loss_pct': stop_loss_pct,
        'leverage': leverage,
    }



def log_signals(signals: list[dict]) -> None:
    SIGNALS_FILE.parent.mkdir(exist_ok=True)
    _ = safe_read_jsonl(SIGNALS_FILE)
    with open(SIGNALS_FILE, 'a') as f:
        for signal in signals:
            f.write(json.dumps(signal) + '\n')
            append_runtime_event(
                stage="signal_scanner",
                exchange=signal.get('exchange', signal.get('source', 'unknown')),
                lifecycle_stage="signal_generated",
                status="INFO",
                message="Paper-trading signal persisted",
                metadata={
                    'signal_type': signal.get('signal_type'),
                    'symbol': signal.get('symbol'),
                    'asset': signal.get('asset'),
                    'ev_score': signal.get('ev_score'),
                },
            )



def generate_report(signals: list[dict]) -> None:
    report = f"""# Phase 1 Signal Report -- Paper Scan
**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}  
**Mode:** Paper Trading Research Only  
**Trading Mode:** {TRADING_MODE} ({trading_mode_summary()})

---

## TOP {len(signals)} SIGNALS (Ranked by EV)

"""

    for i, sig in enumerate(signals, 1):
        sizing = calculate_position_sizing(sig)
        report += f"""
### Signal #{i}: {sig.get('market_question', sig.get('asset', sig.get('symbol', 'Unknown')))}
**Exchange:** {sig['exchange']}  
**Strategy:** {sig['strategy']}  
**EV Score:** {sig['ev_score']:.2f} | **Conviction:** {sig['conviction']}

**Execution Side:** {sig.get('side', sig.get('direction', 'N/A'))}  
**Entry Price:** ${sig['entry_price']:.4f}  
**Recommended Paper Size:** ${sizing['position_size_usd']} ({sizing['pct_of_account']:.2f}% of account)

"""
        if sig['exchange'] == 'Hyperliquid':
            report += (
                f"- Funding Rate: {sig['funding_8h_pct']:+.4f}% per 8h ({sig['funding_annual_pct']:+.0f}% annual)\n"
                f"- Volume: ${sig['volume_24h']/1e6:.1f}M\n"
                f"- Open Interest: ${sig['oi_usd']/1e6:.1f}M\n"
            )
        else:
            report += (
                f"- Market ID: {sig['market_id']}\n"
                f"- Token: {sig['side']} ({sig['token_id']})\n"
                f"- Best Bid / Ask: ${sig['best_bid']:.4f} / ${sig['best_ask']:.4f}\n"
                f"- Liquidity: ${sig['liquidity_usd']:.0f}\n"
                f"- Experimental path: yes (paper only)\n"
            )
        report += "\n---\n"

    report += f"""
## Notes

- Hyperliquid remains the default canonical paper-trading path.
- Polymarket signals are canonical paper-trading signals when the mode includes Polymarket.
- Mixed mode remains a limited deterministic one-entry-per-cycle evaluation path and is not a dual-entry runtime.
"""

    with open(REPORT_FILE, 'w') as f:
        f.write(report)

    print(f"[REPORT] Report saved: {REPORT_FILE}")



def main() -> None:
    print("=" * 80)
    print("PHASE 1: PAPER-TRADING SIGNAL GENERATION ENGINE")
    print(f"Scan Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"Trading Mode: {TRADING_MODE} ({trading_mode_summary()})")
    print("=" * 80)
    print()

    signals: list[dict] = []
    if mode_includes_hyperliquid(TRADING_MODE):
        signals.extend(scan_hyperliquid_funding())
    if mode_includes_polymarket(TRADING_MODE):
        signals.extend(scan_polymarket_markets())

    signals.sort(key=lambda x: x['ev_score'], reverse=True)
    top_signals = signals[:8]

    print()
    print(f"[STATS] Total Signals Found: {len(signals)}")
    print(f"[TARGET] Top Signals Selected: {len(top_signals)}")
    print()

    if top_signals:
        for i, sig in enumerate(top_signals[:5], 1):
            label = sig.get('market_question', sig.get('asset', 'Unknown'))
            print(f"  {i}. [{sig['exchange']}] {label} - EV: {sig['ev_score']:.2f} ({sig['conviction']})")
        log_signals(top_signals)
        generate_report(top_signals)
        print()
        print("[OK] Scan complete")
    else:
        print("[WARN] No high-quality signals found this scan")


if __name__ == "__main__":
    main()
