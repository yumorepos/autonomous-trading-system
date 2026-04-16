#!/usr/bin/env python3
"""
Phase 1 signal generation engine.
Produces canonical paper-trading signals for Hyperliquid.
"""

from __future__ import annotations

import json
import sys
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.runtime import (
    WORKSPACE_ROOT as WORKSPACE,
    LOGS_DIR,
    TRADING_MODE,
)
from utils.api_connectivity import fetch_hyperliquid_meta
from models.exchange_metadata import paper_exchange_is_experimental
from utils.json_utils import safe_read_jsonl
from utils.runtime_logging import append_runtime_event

SIGNALS_FILE = LOGS_DIR / "phase1-signals.jsonl"
REPORT_FILE = WORKSPACE / "PHASE1_SIGNAL_REPORT.md"


CANONICAL_POSITION_SIZES = {
    'Hyperliquid': 1.96,
}


def trading_mode_summary() -> str:
    return "Hyperliquid only"


def load_script_module(script_name: str, module_name: str):
    script_path = REPO_ROOT / "scripts" / script_name
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def signal_rank_score(signal: dict) -> float:
    return float(signal.get('ev_score_decayed', signal.get('ev_score', 0)) or 0)



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
            'experimental': paper_exchange_is_experimental('Hyperliquid'),
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



def calculate_position_sizing(signal: dict, account_balance: float = 97.80) -> dict:
    if signal['conviction'] == 'HIGH':
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


def enforce_signal_integrity(signals: list[dict]) -> tuple[list[dict], dict]:
    integrity_module = load_script_module("data-integrity-layer.py", "phase1_scanner_data_integrity")
    integrity = integrity_module.DataIntegrityLayer()

    accepted_signals: list[dict] = []
    rejected_signals = 0
    for raw_signal in signals:
        signal = dict(raw_signal)
        source_key = str(signal.get('exchange', signal.get('source', 'unknown'))).lower()
        passed, validations = integrity.validate_signal(signal, source_key)
        if passed:
            accepted_signals.append(signal)
            continue

        rejected_signals += 1
        append_runtime_event(
            stage="signal_scanner",
            exchange=signal.get('exchange', signal.get('source', 'unknown')),
            lifecycle_stage="signal_rejected",
            status="WARN",
            message="Signal rejected by canonical data-integrity validation",
            metadata={
                'signal_type': signal.get('signal_type'),
                'symbol': signal.get('symbol'),
                'asset': signal.get('asset'),
                'failed_checks': [result.check_name for result in validations if not result.passed],
            },
        )

    integrity.save_state()
    integrity.save_metrics()

    summary = {'accepted': len(accepted_signals), 'rejected': rejected_signals}
    append_runtime_event(
        stage="signal_scanner",
        exchange="system",
        lifecycle_stage="signal_integrity",
        status="WARN" if rejected_signals else "INFO",
        message=(
            f"Signal integrity validation accepted {summary['accepted']} signal(s) and rejected {summary['rejected']} signal(s)"
        ),
        metadata=summary,
    )
    return accepted_signals, summary


def generate_report(signals: list[dict], integrity_summary: dict | None = None) -> None:
    integrity_summary = integrity_summary or {'accepted': len(signals), 'rejected': 0}
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
        report += (
            f"- Funding Rate: {sig['funding_8h_pct']:+.4f}% per 8h ({sig['funding_annual_pct']:+.0f}% annual)\n"
            f"- Volume: ${sig['volume_24h']/1e6:.1f}M\n"
            f"- Open Interest: ${sig['oi_usd']/1e6:.1f}M\n"
        )
        report += "\n---\n"

    report += f"""
## Notes

- Hyperliquid is the canonical paper-trading path.
- Canonical signal persistence is gated by `DataIntegrityLayer.validate_signal()` before append-only logging.
- Accepted signals this scan: {integrity_summary['accepted']}
- Rejected signals this scan: {integrity_summary['rejected']}
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
    signals.extend(scan_hyperliquid_funding())

    signals.sort(key=signal_rank_score, reverse=True)
    validated_signals, integrity_summary = enforce_signal_integrity(signals)
    validated_signals.sort(key=signal_rank_score, reverse=True)
    top_signals = validated_signals[:8]

    print()
    print(f"[STATS] Total Signals Found: {len(signals)}")
    print(f"[CHECK] Accepted by canonical integrity validation: {integrity_summary['accepted']}")
    print(f"[BLOCK] Rejected by canonical integrity validation: {integrity_summary['rejected']}")
    print(f"[TARGET] Top Signals Selected: {len(top_signals)}")
    print()

    if top_signals:
        for i, sig in enumerate(top_signals[:5], 1):
            label = sig.get('market_question', sig.get('asset', 'Unknown'))
            print(f"  {i}. [{sig['exchange']}] {label} - EV: {signal_rank_score(sig):.2f} ({sig['conviction']})")
        log_signals(top_signals)
        generate_report(top_signals, integrity_summary)
        print()
        print("[OK] Scan complete")
    else:
        generate_report(top_signals, integrity_summary)
        print("[WARN] No high-quality signals found this scan")


if __name__ == "__main__":
    main()
