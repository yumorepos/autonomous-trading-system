#!/usr/bin/env python3
"""
Collects 48-hour paper trading results into a single report.
Run this after the paper trader has been live for >= 48 hours.

Usage: python3 scripts/collect_results.py

Outputs:
    - Full report to stdout (paste this into next Claude conversation)
    - Report saved to data/48h_results.txt
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def main():
    report_lines = []

    def out(line=""):
        report_lines.append(line)
        print(line)

    out("=" * 60)
    out("  48-HOUR PAPER TRADING RESULTS")
    out(f"  Collected: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    out("=" * 60)
    out()

    # 1. Process status
    pid_file = Path("data/paper_trader.pid")
    if pid_file.exists():
        pid = pid_file.read_text().strip()
        try:
            os.kill(int(pid), 0)
            out(f"  Process: RUNNING (PID {pid})")
        except (ProcessLookupError, ValueError):
            out(f"  Process: STOPPED (PID {pid} not found)")
    else:
        out("  Process: NO PID FILE")
    out()

    # 2. Stats API data
    out("--- PERFORMANCE METRICS ---")
    try:
        import urllib.request
        resp = urllib.request.urlopen("http://localhost:8081/paper/stats", timeout=5)
        stats = json.loads(resp.read())
        for key, val in stats.items():
            if isinstance(val, float):
                out(f"  {key}: {val:.4f}")
            else:
                out(f"  {key}: {val}")
    except Exception as e:
        out(f"  (Could not fetch from API: {e})")
        out("  Falling back to trade log analysis...")
    out()

    # 3. Orchestrator status
    out("--- ORCHESTRATOR STATUS ---")
    try:
        import urllib.request
        resp = urllib.request.urlopen("http://localhost:8081/paper/status", timeout=5)
        status = json.loads(resp.read())
        orch = status.get("orchestrator", {})
        for key, val in orch.items():
            out(f"  {key}: {val}")
    except Exception as e:
        out(f"  (Could not fetch: {e})")
    out()

    # 4. Trade log analysis
    trades_file = Path("data/paper_trades.jsonl")
    if trades_file.exists():
        trades = []
        for line in trades_file.read_text().strip().split("\n"):
            if line.strip():
                try:
                    trades.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

        out(f"--- TRADE LOG ({len(trades)} entries) ---")
        opens = [t for t in trades if t.get("action") == "OPEN"]
        closes = [t for t in trades if t.get("action") == "CLOSE"]

        out(f"  Opens:   {len(opens)}")
        out(f"  Closes:  {len(closes)}")

        total_pnl = sum(t.get("net_pnl_usd", 0) for t in closes)
        out(f"  Net PnL: ${total_pnl:.4f}")

        out()
        out("  LAST 5 TRADE EVENTS:")
        for t in trades[-5:]:
            out(f"    {json.dumps(t)}")
    else:
        out("--- TRADE LOG: no trades recorded ---")
    out()

    # 5. Signal filter stats
    out("--- SIGNAL FILTER STATS (24h) ---")
    try:
        import urllib.request
        resp = urllib.request.urlopen("http://localhost:8081/stats", timeout=5)
        filter_stats = json.loads(resp.read())
        for key, val in filter_stats.items():
            if isinstance(val, (list, dict)):
                out(f"  {key}: {json.dumps(val, indent=4)}")
            else:
                out(f"  {key}: {val}")
    except Exception as e:
        out(f"  (Could not fetch: {e})")
    out()

    # 6. Log tail
    out("--- LAST 30 LOG LINES ---")
    log_file = Path("data/paper_stdout.log")
    if log_file.exists():
        lines = log_file.read_text().strip().split("\n")
        for line in lines[-30:]:
            out(f"  {line}")
    else:
        out("  (No log file found)")
    out()

    # 7. Decision recommendation
    out("=" * 60)
    if trades_file.exists() and trades_file.stat().st_size > 0:
        trades = []
        for line in trades_file.read_text().strip().split("\n"):
            if line.strip():
                try:
                    trades.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        closes = [t for t in trades if t.get("action") == "CLOSE"]
        total_pnl = sum(t.get("net_pnl_usd", 0) for t in closes)

        if len(closes) == 0:
            out("  DECISION: INSUFFICIENT DATA — no closed trades after 48h")
            out("  Action: Check if ATS engine is generating regime transitions.")
            out("  Action: Check logs for connector/scoring issues.")
        elif total_pnl > 0:
            out(f"  DECISION: BUILD EXECUTION LAYER")
            out(f"  Net PnL: ${total_pnl:.2f} across {len(closes)} trades (POSITIVE)")
            out(f"  Paper simulation confirms strategy is profitable after fees.")
        else:
            out(f"  DECISION: RETUNE FILTER BEFORE EXECUTION")
            out(f"  Net PnL: ${total_pnl:.2f} across {len(closes)} trades (NEGATIVE)")
            out(f"  Action: Analyze which gate thresholds need adjustment.")
    else:
        out("  DECISION: INSUFFICIENT DATA — no trade log found")
        out("  The market may have been in LOW_FUNDING with no regime transitions.")
        out("  Paper trader is waiting for regime_updated events in the JSONL log.")
    out("=" * 60)

    # Save report
    report_path = Path("data/48h_results.txt")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(report_lines))
    print(f"\nReport saved to {report_path}")


if __name__ == "__main__":
    main()
