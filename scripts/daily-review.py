#!/usr/bin/env python3
"""
Daily Position Review & Signal Scan.

Reads REAL positions from Hyperliquid (if HL_PRIVATE_KEY set) and paper
positions from local state. Evaluates risk, scans signals, executes paper
trades only. Real execution requires explicit --live flag (NOT IMPLEMENTED).

Usage:
    python scripts/daily-review.py
    OPENCLAW_TRADING_MODE=mixed python scripts/daily-review.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

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
from utils.json_utils import safe_read_json, safe_read_jsonl

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

POSITION_STATE_FILE = LOGS_DIR / "position-state.json"
PAPER_TRADES_FILE = LOGS_DIR / "phase1-paper-trades.jsonl"
DAILY_REVIEW_LOG = LOGS_DIR / "daily-review.jsonl"
DAILY_REPORT_FILE = WORKSPACE / "DAILY_REVIEW_REPORT.md"

MAX_CONCURRENT_POSITIONS = 5
MAX_POSITION_SIZE_USD = 50.0
DEFAULT_TIMEOUT_HOURS = 72
DEFAULT_STOP_LOSS_PCT = 0.15
DEFAULT_TAKE_PROFIT_PCT = 0.25

BANNER = "⚠️ PAPER TRADING ONLY — no real funds at risk, no live execution"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat()


def parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def age_hours(opened_at: str | None) -> float:
    dt = parse_iso(opened_at)
    if dt is None:
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = utcnow() - dt
    return max(delta.total_seconds() / 3600, 0.0)


# ---------------------------------------------------------------------------
# Hyperliquid Real Position Reader
# ---------------------------------------------------------------------------

def read_hyperliquid_positions() -> dict[str, Any]:
    """Read real Hyperliquid account state. Returns raw dict or error."""
    key = os.environ.get("HL_PRIVATE_KEY", "")
    if not key:
        return {"status": "NO_CREDENTIALS", "positions": [], "account": {}}

    try:
        from hyperliquid.info import Info
        from hyperliquid.utils import constants
        from eth_account import Account

        info = Info(constants.MAINNET_API_URL, skip_ws=True)
        account = Account.from_key(key)
        address = account.address

        user_state = info.user_state(address)
        open_orders = info.open_orders(address)

        positions = []
        for ap in user_state.get("assetPositions", []):
            p = ap.get("position", {})
            coin = p.get("coin", "")
            szi = float(p.get("szi", 0))
            if szi == 0:
                continue
            positions.append({
                "exchange": "Hyperliquid",
                "asset": coin,
                "direction": "long" if szi > 0 else "short",
                "size": abs(szi),
                "entry_price": float(p.get("entryPx", 0)),
                "position_value": float(p.get("positionValue", 0)),
                "unrealized_pnl": float(p.get("unrealizedPnl", 0)),
                "roe": float(p.get("returnOnEquity", 0)),
                "leverage": p.get("leverage", {}).get("value", 1),
                "margin_used": float(p.get("marginUsed", 0)),
                "cum_funding": float(p.get("cumFunding", {}).get("sinceOpen", 0)),
                "source": "LIVE_EXCHANGE",
            })

        margin = user_state.get("marginSummary", {})
        return {
            "status": "CONNECTED",
            "address": address,
            "account_value": float(margin.get("accountValue", 0)),
            "total_notional": float(margin.get("totalNtlPos", 0)),
            "withdrawable": float(user_state.get("withdrawable", 0)),
            "positions": positions,
            "open_orders": len(open_orders),
            "raw_orders": open_orders[:5],
        }
    except Exception as e:
        return {"status": f"ERROR: {type(e).__name__}: {e}", "positions": [], "account": {}}


# ---------------------------------------------------------------------------
# Paper Position Loading
# ---------------------------------------------------------------------------

def load_paper_positions() -> list[dict[str, Any]]:
    """Load open paper positions from position-state.json."""
    if not POSITION_STATE_FILE.exists():
        return []
    state = safe_read_json(POSITION_STATE_FILE)
    if not isinstance(state, dict):
        return []
    positions = state.get("positions", {})
    if not isinstance(positions, dict):
        return []
    result = []
    for pid, pos in positions.items():
        if isinstance(pos, dict) and pos.get("status", "").upper() == "OPEN":
            pos["trade_id"] = pos.get("trade_id", pid)
            pos["source"] = "PAPER"
            result.append(pos)
    return result


# ---------------------------------------------------------------------------
# Live Price Fetching
# ---------------------------------------------------------------------------

def fetch_hyperliquid_prices() -> dict[str, float]:
    """Fetch current mid prices for all Hyperliquid assets."""
    result, universe, contexts = fetch_hyperliquid_meta(timeout=10)
    if not result.ok or not universe or not contexts:
        return {}
    prices = {}
    for asset, ctx in zip(universe, contexts):
        name = asset.get("name", "")
        mid = ctx.get("midPx")
        if name and mid:
            try:
                prices[name] = float(mid)
            except (ValueError, TypeError):
                pass
    return prices


# ---------------------------------------------------------------------------
# Position Evaluation
# ---------------------------------------------------------------------------

def evaluate_position(pos: dict[str, Any], hl_prices: dict[str, float]) -> dict[str, Any]:
    """Evaluate a single position and return enriched record with decision."""
    exchange = pos.get("exchange", "").lower()
    entry_price = float(pos.get("entry_price", 0))
    asset = pos.get("asset", pos.get("condition_id", "unknown"))
    direction = pos.get("direction", "long").lower()
    source = pos.get("source", "PAPER")

    # For live positions, use the exchange-provided P&L
    if source == "LIVE_EXCHANGE":
        pnl_pct = float(pos.get("roe", 0))
        current_price = hl_prices.get(asset)
        hours = 0  # We don't have opened_at for live positions
        decision = "HOLD"
        reason = f"Live position: ROE {pnl_pct:+.1%}, ${pos.get('position_value', 0):.2f} notional"

        if pnl_pct <= -DEFAULT_STOP_LOSS_PCT:
            decision = "REVIEW_STOPLOSS"
            reason = f"⚠️ ROE {pnl_pct:+.1%} near stop-loss threshold (live position — manual action required)"
        elif pnl_pct >= DEFAULT_TAKE_PROFIT_PCT:
            decision = "REVIEW_TAKEPROFIT"
            reason = f"💰 ROE {pnl_pct:+.1%} above take-profit threshold (live position — consider taking profit)"

        return {**pos, "current_price": current_price, "pnl_pct": pnl_pct,
                "age_hours": hours, "decision": decision, "decision_reason": reason}

    # Paper positions
    opened_at = pos.get("opened_at") or pos.get("entry_timestamp")
    hours = age_hours(opened_at)
    timeout_h = float(pos.get("timeout_hours", DEFAULT_TIMEOUT_HOURS))
    sl_pct = float(pos.get("stop_loss_pct", DEFAULT_STOP_LOSS_PCT))
    tp_pct = float(pos.get("take_profit_pct", DEFAULT_TAKE_PROFIT_PCT))

    current_price = None
    if "hyperliquid" in exchange and asset in hl_prices:
        current_price = hl_prices[asset]

    pnl_pct = 0.0
    if current_price and entry_price > 0:
        if direction == "long":
            pnl_pct = (current_price - entry_price) / entry_price
        else:
            pnl_pct = (entry_price - current_price) / entry_price

    decision = "HOLD"
    reason = "Within thresholds"
    if hours > timeout_h:
        decision = "EXIT_TIMEOUT"
        reason = f"Position age {hours:.1f}h exceeds {timeout_h}h timeout"
    elif pnl_pct <= -sl_pct:
        decision = "EXIT_STOPLOSS"
        reason = f"P&L {pnl_pct:+.1%} hit stop-loss at -{sl_pct:.0%}"
    elif pnl_pct >= tp_pct:
        decision = "EXIT_TAKEPROFIT"
        reason = f"P&L {pnl_pct:+.1%} hit take-profit at +{tp_pct:.0%}"
    elif current_price is None and hours > 24:
        decision = "STALE"
        reason = f"No live price available, position age {hours:.1f}h"

    return {**pos, "current_price": current_price, "pnl_pct": pnl_pct,
            "age_hours": hours, "decision": decision, "decision_reason": reason}


# ---------------------------------------------------------------------------
# Signal Scanning
# ---------------------------------------------------------------------------

def scan_hyperliquid_signals(universe: list, contexts: list, existing_assets: set[str]) -> list[dict[str, Any]]:
    """Scan Hyperliquid for funding rate anomalies."""
    signals = []
    for asset, ctx in zip(universe, contexts):
        name = asset.get("name", "")
        if name in existing_assets:
            continue
        funding = ctx.get("funding")
        mid_px = ctx.get("midPx")
        volume = ctx.get("dayNtlVlm")
        if not funding or not mid_px:
            continue
        try:
            funding_rate = float(funding)
            price = float(mid_px)
            vol = float(volume) if volume else 0
        except (ValueError, TypeError):
            continue

        annualized = funding_rate * 3 * 365
        if abs(annualized) > 0.5 and vol > 100_000:
            direction = "short" if funding_rate > 0 else "long"
            signals.append({
                "exchange": "Hyperliquid",
                "asset": name,
                "signal_type": "funding_anomaly",
                "direction": direction,
                "entry_price": price,
                "funding_rate_8h": funding_rate,
                "annualized_rate": annualized,
                "volume_24h": vol,
                "score": abs(annualized) * min(vol / 1_000_000, 5.0),
                "scanned_at": iso(utcnow()),
            })
    signals.sort(key=lambda s: s["score"], reverse=True)
    return signals[:5]


def scan_polymarket_signals(markets: list[dict[str, Any]], existing_ids: set[str]) -> list[dict[str, Any]]:
    """Scan Polymarket for volume/probability movers."""
    signals = []
    for m in markets:
        cid = m.get("conditionId", "")
        if cid in existing_ids:
            continue
        question = m.get("question", "")
        volume_24h = m.get("volume24hr", 0) or 0
        try:
            outcome_prices = json.loads(m.get("outcomePrices", "[]"))
            yes_price = float(outcome_prices[0]) if outcome_prices else 0
        except (json.JSONDecodeError, IndexError, ValueError, TypeError):
            yes_price = 0

        if volume_24h > 10_000 and 0.15 < yes_price < 0.85:
            edge = abs(yes_price - 0.5)
            score = edge * min(volume_24h / 100_000, 3.0)
            signals.append({
                "exchange": "Polymarket",
                "condition_id": cid,
                "question": question[:100],
                "signal_type": "volume_mover",
                "direction": "yes" if yes_price < 0.5 else "no",
                "entry_price": yes_price if yes_price < 0.5 else 1 - yes_price,
                "yes_price": yes_price,
                "volume_24h": volume_24h,
                "score": score,
                "scanned_at": iso(utcnow()),
            })
    signals.sort(key=lambda s: s["score"], reverse=True)
    return signals[:5]


# ---------------------------------------------------------------------------
# Paper Trade Execution
# ---------------------------------------------------------------------------

def paper_close_position(pos: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "event": "paper_close", "trade_id": pos.get("trade_id", "unknown"),
        "exchange": pos.get("exchange", "unknown"),
        "asset": pos.get("asset", pos.get("condition_id", "unknown")),
        "entry_price": pos.get("entry_price"), "exit_price": pos.get("current_price"),
        "pnl_pct": pos.get("pnl_pct", 0), "reason": reason, "closed_at": iso(utcnow()),
    }


def paper_open_position(signal: dict[str, Any], position_count: int) -> dict[str, Any] | None:
    if position_count >= MAX_CONCURRENT_POSITIONS:
        return None
    entry_price = signal.get("entry_price", 0)
    if entry_price <= 0:
        return None
    return {
        "event": "paper_open",
        "trade_id": f"daily-{signal['exchange'].lower()}-{signal.get('asset', signal.get('condition_id', 'unk'))}-{utcnow().strftime('%Y%m%d%H%M')}",
        "exchange": signal["exchange"], "asset": signal.get("asset", signal.get("condition_id", "")),
        "direction": signal.get("direction", "long"), "entry_price": entry_price,
        "position_size_usd": min(MAX_POSITION_SIZE_USD, 50.0),
        "signal_type": signal.get("signal_type", ""), "signal_score": signal.get("score", 0),
        "stop_loss_pct": DEFAULT_STOP_LOSS_PCT, "take_profit_pct": DEFAULT_TAKE_PROFIT_PCT,
        "timeout_hours": DEFAULT_TIMEOUT_HOURS, "opened_at": iso(utcnow()), "status": "OPEN",
    }


# ---------------------------------------------------------------------------
# Report Generation
# ---------------------------------------------------------------------------

def generate_report(
    live_hl: dict[str, Any], paper_positions: list[dict[str, Any]],
    all_evaluated: list[dict[str, Any]], exits: list[dict[str, Any]],
    new_entries: list[dict[str, Any]], hl_signals: list[dict[str, Any]],
    pm_signals: list[dict[str, Any]], hl_ok: bool, pm_ok: bool,
    hl_asset_count: int, pm_market_count: int,
) -> str:
    now = utcnow()
    lines = [
        f"# Daily Review Report",
        f"",
        f"> {BANNER}",
        f"",
        f"**Generated:** {iso(now)}  ",
        f"**Trading Mode:** {TRADING_MODE}  ",
        f"**Exchange Connectivity:** Hyperliquid {'✅' if hl_ok else '❌'} ({hl_asset_count} assets) | Polymarket {'✅' if pm_ok else '❌'} ({pm_market_count} markets)",
        f"",
    ]

    # Live Hyperliquid Account
    hl_status = live_hl.get("status", "UNKNOWN")
    if hl_status == "CONNECTED":
        lines.extend([
            "## 🔴 LIVE Hyperliquid Account",
            f"- **Address:** `{live_hl.get('address', '?')}`",
            f"- **Account Value:** ${live_hl.get('account_value', 0):.6f}",
            f"- **Total Notional:** ${live_hl.get('total_notional', 0):.4f}",
            f"- **Withdrawable:** ${live_hl.get('withdrawable', 0):.6f}",
            f"- **Open Orders:** {live_hl.get('open_orders', 0)}",
            "",
        ])
        live_positions = [p for p in all_evaluated if p.get("source") == "LIVE_EXCHANGE"]
        if live_positions:
            lines.append("### Live Positions")
            lines.append("| Asset | Dir | Size | Entry | Current | P&L | ROE | Leverage | Decision |")
            lines.append("|-------|-----|------|-------|---------|-----|-----|----------|----------|")
            for p in live_positions:
                cur = f"${p.get('current_price', 0):,.2f}" if p.get("current_price") else "N/A"
                lines.append(
                    f"| {p['asset']} | {p['direction']} | {p.get('size', 0):.4f} "
                    f"| ${p['entry_price']:,.2f} | {cur} "
                    f"| ${p.get('unrealized_pnl', 0):+.4f} | {p.get('roe', 0):+.1%} "
                    f"| {p.get('leverage', '?')}x | **{p['decision']}** |"
                )
            lines.append("")
        lines.append("> ⚠️ Live position management requires manual action. This system is read-only for live positions.")
        lines.append("")
    else:
        lines.extend([
            f"## Hyperliquid Account",
            f"- **Status:** {hl_status}",
            "",
        ])

    # Paper Positions
    paper_eval = [p for p in all_evaluated if p.get("source") == "PAPER"]
    lines.append("## Paper Positions")
    if not paper_eval:
        lines.append("_No open paper positions._\n")
    else:
        lines.append("| Exchange | Asset | Dir | Entry | Current | P&L | Age (h) | Decision |")
        lines.append("|----------|-------|-----|-------|---------|-----|---------|----------|")
        for p in paper_eval:
            cur = f"${p.get('current_price', 0):.4f}" if p.get("current_price") else "N/A"
            lines.append(
                f"| {p.get('exchange', '?')} | {p.get('asset', '?')} | {p.get('direction', '?')} "
                f"| ${p.get('entry_price', 0):.4f} | {cur} | {p.get('pnl_pct', 0):+.1%} "
                f"| {p.get('age_hours', 0):.1f} | **{p['decision']}** |"
            )
        lines.append("")

    # Exits & Entries
    lines.append("## Paper Exits Executed")
    if not exits:
        lines.append("_No exits this cycle._\n")
    else:
        for e in exits:
            lines.append(f"- **{e['asset']}** ({e['exchange']}): {e['reason']}")
        lines.append("")

    lines.append("## New Paper Entries")
    if not new_entries:
        lines.append("_No new entries this cycle._\n")
    else:
        for n in new_entries:
            lines.append(f"- **{n['asset']}** ({n['exchange']}): {n['direction']} @ ${n['entry_price']:.4f} | Score: {n.get('signal_score', 0):.2f}")
        lines.append("")

    # Signals
    if hl_signals:
        lines.append("## Hyperliquid Signals — Funding Anomalies")
        for s in hl_signals[:3]:
            lines.append(f"- **{s['asset']}**: {s['annualized_rate']:+.0%} ann. | Vol: ${s['volume_24h']:,.0f} | Score: {s['score']:.2f}")
        lines.append("")
    if pm_signals:
        lines.append("## Polymarket Signals — Volume Movers")
        for s in pm_signals[:3]:
            lines.append(f"- **{s['question'][:60]}**: YES@{s['yes_price']:.2f} | Vol24h: ${s['volume_24h']:,.0f} | Score: {s['score']:.2f}")
        lines.append("")

    # Execution Status
    lines.extend([
        "## Execution Status",
        "",
        "| Exchange | Data Feed | Position Reading | Live Execution | Status |",
        "|----------|-----------|-----------------|----------------|--------|",
        f"| Hyperliquid | {'✅ Public API' if hl_ok else '❌'} | {'✅ SDK + Key' if hl_status == 'CONNECTED' else '❌ No credentials'} | ❌ NOT IMPLEMENTED | **{'PARTIAL' if hl_status == 'CONNECTED' else 'PAPER ONLY'}** |",
        f"| Polymarket | {'✅ Gamma API' if pm_ok else '❌'} | ❌ No CLOB key | ❌ NOT IMPLEMENTED | **PAPER ONLY** |",
        "",
        "## Scheduling",
        "```",
        "# Not installed — run manually or add to crontab:",
        f"0 20 * * * cd {REPO_ROOT} && python3 scripts/daily-review.py >> workspace/logs/cron.log 2>&1",
        "```",
        "",
        "---",
        f"_Generated by autonomous-trading-system/scripts/daily-review.py_",
    ])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_daily_review() -> dict[str, Any]:
    now = utcnow()
    print(f"\n{'='*60}")
    print(f"  DAILY REVIEW — {iso(now)}")
    print(f"  {BANNER}")
    print(f"  Mode: {TRADING_MODE}")
    print(f"{'='*60}\n")

    # 1. Read live Hyperliquid positions
    live_hl: dict[str, Any] = {"status": "SKIPPED", "positions": []}
    if mode_includes_hyperliquid():
        live_hl = read_hyperliquid_positions()
        hl_status = live_hl["status"]
        live_pos = live_hl.get("positions", [])
        print(f"[1/6] Hyperliquid account: {hl_status}")
        if hl_status == "CONNECTED":
            print(f"       Account value: ${live_hl.get('account_value', 0):.6f}")
            print(f"       Live positions: {len(live_pos)}")
            for p in live_pos:
                print(f"         {p['asset']} {p['direction']} {p['size']} @ ${p['entry_price']:,.2f} | PnL: ${p['unrealized_pnl']:+.4f} ({p['roe']:+.1%})")
    else:
        print(f"[1/6] Hyperliquid: skipped (mode={TRADING_MODE})")

    # 2. Load paper positions
    paper_positions = load_paper_positions()
    print(f"[2/6] Paper positions: {len(paper_positions)}")

    # 3. Fetch market data
    hl_prices = {}
    hl_asset_count = 0
    hl_universe: list = []
    hl_contexts: list = []
    hl_ok = False

    if mode_includes_hyperliquid():
        hl_result, hl_universe, hl_contexts = fetch_hyperliquid_meta(timeout=10)
        hl_ok = hl_result.ok
        hl_asset_count = hl_result.record_count
        if hl_ok:
            hl_prices = fetch_hyperliquid_prices()
        print(f"[3/6] Hyperliquid data: {'✅' if hl_ok else '❌'} ({hl_asset_count} assets, {len(hl_prices)} prices)")

    pm_markets: list[dict[str, Any]] = []
    pm_ok = False
    pm_market_count = 0
    if mode_includes_polymarket():
        pm_result, pm_markets = fetch_polymarket_markets(timeout=10, limit=50, closed=False)
        pm_ok = pm_result.ok
        pm_market_count = pm_result.record_count
        pm_markets = [m for m in pm_markets if m.get("active") and not m.get("closed")]
        print(f"[3/6] Polymarket data: {'✅' if pm_ok else '❌'} ({pm_market_count} markets)")

    # 4. Evaluate ALL positions (live + paper)
    all_positions = live_hl.get("positions", []) + paper_positions
    evaluated = [evaluate_position(p, hl_prices) for p in all_positions]

    # Only paper positions can be auto-exited
    paper_exits = [p for p in evaluated if p.get("source") == "PAPER" and p["decision"].startswith("EXIT")]
    paper_holds = [p for p in evaluated if p.get("source") == "PAPER" and p["decision"] in ("HOLD", "STALE")]
    live_alerts = [p for p in evaluated if p.get("source") == "LIVE_EXCHANGE" and p["decision"].startswith("REVIEW")]

    print(f"[4/6] Evaluation: {len(evaluated)} total | Paper exits: {len(paper_exits)} | Live alerts: {len(live_alerts)}")
    for a in live_alerts:
        print(f"  ⚠️ LIVE ALERT: {a['asset']} — {a['decision_reason']}")

    exits_executed = [paper_close_position(p, p["decision_reason"]) for p in paper_exits]

    # 5. Scan signals
    existing_hl = {p.get("asset", "") for p in all_positions}
    existing_pm = {p.get("condition_id", "") for p in all_positions}
    hl_signals = scan_hyperliquid_signals(hl_universe, hl_contexts, existing_hl) if hl_ok else []
    pm_signals = scan_polymarket_signals(pm_markets, existing_pm) if pm_ok else []
    print(f"[5/6] Signals: {len(hl_signals)} HL, {len(pm_signals)} PM")

    # Paper entries (best signal per exchange)
    new_entries = []
    current_count = len(paper_holds)
    for signal in (hl_signals[:1] + pm_signals[:1]):
        entry = paper_open_position(signal, current_count)
        if entry:
            new_entries.append(entry)
            current_count += 1
            print(f"  📝 PAPER ENTRY: {entry['asset']} ({entry['exchange']}) @ ${entry['entry_price']:.4f}")

    # 6. Write report
    report = generate_report(live_hl, paper_positions, evaluated, exits_executed, new_entries,
                              hl_signals, pm_signals, hl_ok, pm_ok, hl_asset_count, pm_market_count)
    DAILY_REPORT_FILE.write_text(report, encoding="utf-8")

    log_entry = {
        "timestamp": iso(now), "mode": TRADING_MODE,
        "hl_status": live_hl.get("status"), "hl_account_value": live_hl.get("account_value"),
        "hl_live_positions": len(live_hl.get("positions", [])),
        "paper_positions": len(paper_positions), "exits": len(exits_executed),
        "new_entries": len(new_entries), "hl_signals": len(hl_signals), "pm_signals": len(pm_signals),
        "live_alerts": [{"asset": a["asset"], "decision": a["decision"]} for a in live_alerts],
        "exits_detail": exits_executed, "entries_detail": new_entries,
    }
    with open(DAILY_REVIEW_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry) + "\n")
    for entry in new_entries + exits_executed:
        with open(PAPER_TRADES_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    print(f"\n[6/6] Report: {DAILY_REPORT_FILE}")
    print(f"{'='*60}")
    print(f"  COMPLETE — Live: {len(live_hl.get('positions', []))} | Paper: {len(paper_holds)} held, {len(exits_executed)} exited, {len(new_entries)} new")
    print(f"{'='*60}\n")
    return log_entry


if __name__ == "__main__":
    run_daily_review()
