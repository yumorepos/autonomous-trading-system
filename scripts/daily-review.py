#!/usr/bin/env python3
"""
Daily Position Review & Signal Scan — Paper Trading Only.

Reads current paper positions, evaluates hold/exit decisions against live
market data, scans for new signal candidates, executes paper trades, and
writes an auditable daily report.

Usage:
    python scripts/daily-review.py
    OPENCLAW_TRADING_MODE=mixed python scripts/daily-review.py
"""

from __future__ import annotations

import json
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

BANNER = "⚠️ PAPER TRADING ONLY — no real funds, no live execution"


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
    delta = utcnow() - dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else utcnow() - dt
    return max(delta.total_seconds() / 3600, 0.0)


# ---------------------------------------------------------------------------
# Position Loading
# ---------------------------------------------------------------------------

def load_open_positions() -> list[dict[str, Any]]:
    """Load open positions from position-state.json."""
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
            result.append(pos)
    return result


def load_paper_trades() -> list[dict[str, Any]]:
    """Load all paper trades from JSONL."""
    if not PAPER_TRADES_FILE.exists():
        return []
    return safe_read_jsonl(PAPER_TRADES_FILE)


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


def fetch_polymarket_active_markets(limit: int = 50) -> list[dict[str, Any]]:
    """Fetch active Polymarket markets."""
    result, markets = fetch_polymarket_markets(timeout=10, limit=limit, closed=False)
    if not result.ok:
        return []
    return [m for m in markets if m.get("active") and not m.get("closed")]


# ---------------------------------------------------------------------------
# Position Evaluation
# ---------------------------------------------------------------------------

def evaluate_position(pos: dict[str, Any], hl_prices: dict[str, float]) -> dict[str, Any]:
    """Evaluate a single open position and return enriched record with decision."""
    exchange = pos.get("exchange", "").lower()
    entry_price = float(pos.get("entry_price", 0))
    asset = pos.get("asset", pos.get("condition_id", "unknown"))
    direction = pos.get("direction", "long").lower()
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

    # Decision logic
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

    return {
        **pos,
        "current_price": current_price,
        "pnl_pct": pnl_pct,
        "age_hours": hours,
        "decision": decision,
        "decision_reason": reason,
    }


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

        annualized = funding_rate * 3 * 365  # 8h funding * 3 * 365
        if abs(annualized) > 0.5 and vol > 100_000:  # >50% annualized, >$100k daily volume
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
        volume = m.get("volumeNum", 0) or 0
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
                "total_volume": volume,
                "score": score,
                "scanned_at": iso(utcnow()),
            })

    signals.sort(key=lambda s: s["score"], reverse=True)
    return signals[:5]


# ---------------------------------------------------------------------------
# Paper Trade Execution
# ---------------------------------------------------------------------------

def paper_close_position(pos: dict[str, Any], reason: str) -> dict[str, Any]:
    """Create a paper close record."""
    return {
        "event": "paper_close",
        "trade_id": pos.get("trade_id", "unknown"),
        "exchange": pos.get("exchange", "unknown"),
        "asset": pos.get("asset", pos.get("condition_id", "unknown")),
        "entry_price": pos.get("entry_price"),
        "exit_price": pos.get("current_price"),
        "pnl_pct": pos.get("pnl_pct", 0),
        "reason": reason,
        "closed_at": iso(utcnow()),
    }


def paper_open_position(signal: dict[str, Any], position_count: int) -> dict[str, Any] | None:
    """Create a paper open record if within limits."""
    if position_count >= MAX_CONCURRENT_POSITIONS:
        return None
    position_size = min(MAX_POSITION_SIZE_USD, 50.0)
    entry_price = signal.get("entry_price", 0)
    if entry_price <= 0:
        return None
    return {
        "event": "paper_open",
        "trade_id": f"daily-{signal['exchange'].lower()}-{signal.get('asset', signal.get('condition_id', 'unk'))}-{utcnow().strftime('%Y%m%d%H%M')}",
        "exchange": signal["exchange"],
        "asset": signal.get("asset", signal.get("condition_id", "")),
        "direction": signal.get("direction", "long"),
        "entry_price": entry_price,
        "position_size_usd": position_size,
        "signal_type": signal.get("signal_type", ""),
        "signal_score": signal.get("score", 0),
        "stop_loss_pct": DEFAULT_STOP_LOSS_PCT,
        "take_profit_pct": DEFAULT_TAKE_PROFIT_PCT,
        "timeout_hours": DEFAULT_TIMEOUT_HOURS,
        "opened_at": iso(utcnow()),
        "status": "OPEN",
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def generate_report(
    positions: list[dict[str, Any]],
    exits: list[dict[str, Any]],
    new_entries: list[dict[str, Any]],
    hl_signals: list[dict[str, Any]],
    pm_signals: list[dict[str, Any]],
    hl_ok: bool,
    pm_ok: bool,
    hl_asset_count: int,
    pm_market_count: int,
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

    # Positions
    lines.append("## Open Positions")
    if not positions:
        lines.append("_No open positions._\n")
    else:
        lines.append("| Exchange | Asset | Direction | Entry | Current | P&L | Age (h) | Decision |")
        lines.append("|----------|-------|-----------|-------|---------|-----|---------|----------|")
        for p in positions:
            cur = f"${p.get('current_price', 0):.4f}" if p.get("current_price") else "N/A"
            lines.append(
                f"| {p.get('exchange', '?')} | {p.get('asset', p.get('condition_id', '?'))} "
                f"| {p.get('direction', '?')} | ${p.get('entry_price', 0):.4f} "
                f"| {cur} | {p.get('pnl_pct', 0):+.1%} "
                f"| {p.get('age_hours', 0):.1f} | **{p.get('decision', '?')}** |"
            )
        lines.append("")

    # Exits
    lines.append("## Exits Executed")
    if not exits:
        lines.append("_No exits this cycle._\n")
    else:
        for e in exits:
            lines.append(f"- **{e['asset']}** ({e['exchange']}): {e['reason']} | P&L: {e.get('pnl_pct', 0):+.1%}")
        lines.append("")

    # New Entries
    lines.append("## New Paper Entries")
    if not new_entries:
        lines.append("_No new entries this cycle._\n")
    else:
        for n in new_entries:
            lines.append(f"- **{n['asset']}** ({n['exchange']}): {n['direction']} @ ${n['entry_price']:.4f} | Score: {n.get('signal_score', 0):.2f}")
        lines.append("")

    # Signal Candidates
    lines.append("## Signal Candidates (Top Scored)")
    if hl_signals:
        lines.append("### Hyperliquid — Funding Anomalies")
        for s in hl_signals[:3]:
            lines.append(f"- **{s['asset']}**: {s['annualized_rate']:+.0%} annualized | Vol: ${s['volume_24h']:,.0f} | Score: {s['score']:.2f}")
        lines.append("")
    if pm_signals:
        lines.append("### Polymarket — Volume Movers")
        for s in pm_signals[:3]:
            lines.append(f"- **{s['question'][:60]}**: YES@{s['yes_price']:.2f} | Vol24h: ${s['volume_24h']:,.0f} | Score: {s['score']:.2f}")
        lines.append("")

    # Risk Summary
    open_count = sum(1 for p in positions if p.get("decision") == "HOLD")
    total_exposure = sum(float(p.get("position_size_usd", 0)) for p in positions if p.get("decision") == "HOLD")
    lines.extend([
        "## Risk Summary",
        f"- Open positions after review: **{open_count}** / {MAX_CONCURRENT_POSITIONS} max",
        f"- Total paper exposure: **${total_exposure:,.2f}** / ${MAX_CONCURRENT_POSITIONS * MAX_POSITION_SIZE_USD:,.2f} max",
        f"- New entries this cycle: **{len(new_entries)}**",
        f"- Exits this cycle: **{len(exits)}**",
        "",
        "---",
        f"_Report generated by autonomous-trading-system daily-review.py_",
    ])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_daily_review() -> dict[str, Any]:
    """Execute the full daily review workflow. Returns summary dict."""
    now = utcnow()
    print(f"\n{'='*60}")
    print(f"  DAILY REVIEW — {iso(now)}")
    print(f"  {BANNER}")
    print(f"  Mode: {TRADING_MODE}")
    print(f"{'='*60}\n")

    # 1. Load positions
    positions = load_open_positions()
    print(f"[1/5] Loaded {len(positions)} open position(s)")

    # 2. Fetch live prices
    hl_prices = {}
    hl_asset_count = 0
    pm_markets: list[dict[str, Any]] = []
    pm_market_count = 0
    hl_universe: list = []
    hl_contexts: list = []

    if mode_includes_hyperliquid():
        hl_result, hl_universe, hl_contexts = fetch_hyperliquid_meta(timeout=10)
        hl_ok = hl_result.ok
        hl_asset_count = hl_result.record_count
        if hl_ok:
            hl_prices = fetch_hyperliquid_prices()
        print(f"[2/5] Hyperliquid: {'✅' if hl_ok else '❌'} ({hl_asset_count} assets, {len(hl_prices)} prices)")
    else:
        hl_ok = False
        print(f"[2/5] Hyperliquid: skipped (mode={TRADING_MODE})")

    if mode_includes_polymarket():
        pm_result, pm_markets = fetch_polymarket_markets(timeout=10, limit=50, closed=False)
        pm_ok = pm_result.ok
        pm_market_count = pm_result.record_count
        pm_markets = [m for m in pm_markets if m.get("active") and not m.get("closed")]
        print(f"[2/5] Polymarket: {'✅' if pm_ok else '❌'} ({pm_market_count} markets, {len(pm_markets)} active)")
    else:
        pm_ok = False
        print(f"[2/5] Polymarket: skipped (mode={TRADING_MODE})")

    # 3. Evaluate positions
    evaluated = [evaluate_position(p, hl_prices) for p in positions]
    exits_needed = [p for p in evaluated if p["decision"].startswith("EXIT")]
    holds = [p for p in evaluated if p["decision"] in ("HOLD", "STALE")]
    print(f"[3/5] Position review: {len(holds)} hold, {len(exits_needed)} exit")

    # Execute paper exits
    exits_executed = []
    for p in exits_needed:
        close_record = paper_close_position(p, p["decision_reason"])
        exits_executed.append(close_record)
        print(f"  EXIT: {close_record['asset']} — {close_record['reason']}")

    # 4. Scan signals
    existing_hl_assets = {p.get("asset", "") for p in holds if "hyperliquid" in p.get("exchange", "").lower()}
    existing_pm_ids = {p.get("condition_id", "") for p in holds if "polymarket" in p.get("exchange", "").lower()}

    hl_signals = scan_hyperliquid_signals(hl_universe, hl_contexts, existing_hl_assets) if hl_ok else []
    pm_signals = scan_polymarket_signals(pm_markets, existing_pm_ids) if pm_ok else []
    print(f"[4/5] Signals: {len(hl_signals)} Hyperliquid, {len(pm_signals)} Polymarket")

    # Execute paper entries (best signal only per exchange)
    new_entries = []
    current_count = len(holds)
    for signal in (hl_signals[:1] + pm_signals[:1]):
        entry = paper_open_position(signal, current_count)
        if entry:
            new_entries.append(entry)
            current_count += 1
            print(f"  NEW: {entry['asset']} ({entry['exchange']}) @ ${entry['entry_price']:.4f}")

    # 5. Generate report & logs
    report = generate_report(evaluated, exits_executed, new_entries, hl_signals, pm_signals, hl_ok, pm_ok, hl_asset_count, pm_market_count)
    DAILY_REPORT_FILE.write_text(report, encoding="utf-8")
    print(f"\n[5/5] Report written to {DAILY_REPORT_FILE}")

    # Append to daily review log
    log_entry = {
        "timestamp": iso(now),
        "mode": TRADING_MODE,
        "positions_reviewed": len(evaluated),
        "exits": len(exits_executed),
        "new_entries": len(new_entries),
        "hl_signals": len(hl_signals),
        "pm_signals": len(pm_signals),
        "hl_connected": hl_ok,
        "pm_connected": pm_ok,
        "exits_detail": exits_executed,
        "entries_detail": new_entries,
    }
    with open(DAILY_REVIEW_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry) + "\n")

    # Append paper trades
    for entry in new_entries:
        with open(PAPER_TRADES_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    for exit_rec in exits_executed:
        with open(PAPER_TRADES_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(exit_rec) + "\n")

    print(f"\n{'='*60}")
    print(f"  REVIEW COMPLETE — {len(holds)} positions held, {len(exits_executed)} exits, {len(new_entries)} new entries")
    print(f"{'='*60}\n")

    return log_entry


if __name__ == "__main__":
    run_daily_review()
