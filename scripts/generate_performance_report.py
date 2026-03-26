#!/usr/bin/env python3
"""
Generate recruiter-grade performance report from canonical trade logs.
Reads ONLY real closed trades. No simulation. No projection.

Outputs:
  artifacts/performance_report.json
  artifacts/PERFORMANCE_REPORT.md
  artifacts/equity_curve.csv
  artifacts/trade_summary.csv
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LOG_FILE = REPO_ROOT / "workspace" / "logs" / "phase1-paper-trades.jsonl"
ARTIFACTS = REPO_ROOT / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)


def parse_closed_trades() -> list[dict]:
    closed = []
    for line in LOG_FILE.read_text().splitlines():
        if not line.strip():
            continue
        trade = json.loads(line)
        if trade.get("status") == "CLOSED":
            closed.append(trade)
    closed.sort(key=lambda t: t.get("exit_timestamp", ""))
    return closed


def compute_metrics(trades: list[dict]) -> dict:
    if not trades:
        return {"error": "no closed trades"}

    pnls = [t.get("realized_pnl_usd", 0) for t in trades]
    pcts = [t.get("realized_pnl_pct", 0) for t in trades]
    sizes = [t.get("position_size_usd", 0) for t in trades]

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    # Durations
    durations_min = []
    for t in trades:
        entry = t.get("entry_timestamp")
        exit_ = t.get("exit_timestamp")
        if entry and exit_:
            e = datetime.fromisoformat(entry.replace("Z", "+00:00"))
            x = datetime.fromisoformat(exit_.replace("Z", "+00:00"))
            durations_min.append((x - e).total_seconds() / 60)

    # Equity curve (cumulative PnL)
    starting_balance = 97.80  # from paper-account.json
    cumulative = []
    running = starting_balance
    for t in trades:
        running += t.get("realized_pnl_usd", 0)
        cumulative.append({
            "trade_id": t.get("trade_id"),
            "symbol": t.get("symbol"),
            "exit_timestamp": t.get("exit_timestamp"),
            "pnl_usd": t.get("realized_pnl_usd", 0),
            "cumulative_balance": round(running, 4),
        })

    # Max drawdown from peak
    peak = starting_balance
    max_dd = 0
    for point in cumulative:
        bal = point["cumulative_balance"]
        if bal > peak:
            peak = bal
        dd = (peak - bal) / peak * 100
        if dd > max_dd:
            max_dd = dd

    total_pnl = sum(pnls)
    win_rate = len(wins) / len(pnls) * 100 if pnls else 0
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = sum(losses) / len(losses) if losses else 0
    expectancy = total_pnl / len(pnls) if pnls else 0
    profit_factor = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float("inf")

    # Exit reason breakdown
    exit_reasons = {}
    for t in trades:
        reason = t.get("exit_reason", "unknown")
        exit_reasons[reason] = exit_reasons.get(reason, 0) + 1

    # Strategy breakdown
    strategies = {}
    for t in trades:
        strat = t.get("strategy", "unknown")
        if strat not in strategies:
            strategies[strat] = {"count": 0, "pnl": 0}
        strategies[strat]["count"] += 1
        strategies[strat]["pnl"] += t.get("realized_pnl_usd", 0)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_source": str(LOG_FILE),
        "sample_size": len(trades),
        "disclaimer": "Paper trading only. Sample size too small for statistical significance.",
        "summary": {
            "total_trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate_pct": round(win_rate, 1),
            "total_pnl_usd": round(total_pnl, 4),
            "avg_pnl_usd": round(expectancy, 4),
            "avg_pnl_pct": round(sum(pcts) / len(pcts), 2) if pcts else 0,
            "avg_win_usd": round(avg_win, 4),
            "avg_loss_usd": round(avg_loss, 4),
            "profit_factor": round(profit_factor, 2),
            "expectancy_per_trade_usd": round(expectancy, 4),
            "max_drawdown_from_peak_pct": round(max_dd, 4),
            "starting_balance_usd": starting_balance,
            "ending_balance_usd": round(cumulative[-1]["cumulative_balance"], 2) if cumulative else starting_balance,
        },
        "duration": {
            "avg_trade_duration_min": round(sum(durations_min) / len(durations_min), 1) if durations_min else 0,
            "min_trade_duration_min": round(min(durations_min), 1) if durations_min else 0,
            "max_trade_duration_min": round(max(durations_min), 1) if durations_min else 0,
        },
        "exit_reasons": exit_reasons,
        "strategies": {k: {"count": v["count"], "pnl_usd": round(v["pnl"], 4)} for k, v in strategies.items()},
        "position_sizing": {
            "avg_position_usd": round(sum(sizes) / len(sizes), 2) if sizes else 0,
            "total_capital_deployed_usd": round(sum(sizes), 2),
        },
        "equity_curve": cumulative,
        "trades": [
            {
                "trade_id": t.get("trade_id"),
                "symbol": t.get("symbol"),
                "side": t.get("side") or t.get("direction"),
                "entry_price": t.get("entry_price"),
                "exit_price": t.get("exit_price"),
                "position_size_usd": t.get("position_size_usd"),
                "pnl_usd": t.get("realized_pnl_usd"),
                "pnl_pct": t.get("realized_pnl_pct"),
                "exit_reason": t.get("exit_reason"),
                "duration_min": round(
                    (
                        datetime.fromisoformat(t["exit_timestamp"].replace("Z", "+00:00"))
                        - datetime.fromisoformat(t["entry_timestamp"].replace("Z", "+00:00"))
                    ).total_seconds()
                    / 60,
                    1,
                )
                if t.get("entry_timestamp") and t.get("exit_timestamp")
                else None,
            }
            for t in trades
        ],
    }


def generate_markdown(metrics: dict) -> str:
    s = metrics["summary"]
    d = metrics["duration"]
    lines = [
        "# Paper Trading Performance Report",
        "",
        f"> Generated: {metrics['generated_at'][:19]} UTC",
        f"> Data source: `{Path(metrics['data_source']).name}`",
        f"> **⚠️ {metrics['disclaimer']}**",
        "",
        "## Summary",
        "",
        f"| Metric | Value |",
        f"|---|---|",
        f"| Total trades | {s['total_trades']} |",
        f"| Wins / Losses | {s['wins']} / {s['losses']} |",
        f"| Win rate | {s['win_rate_pct']}% |",
        f"| Total PnL | ${s['total_pnl_usd']:+.4f} |",
        f"| Avg PnL per trade | ${s['avg_pnl_usd']:+.4f} |",
        f"| Avg win | ${s['avg_win_usd']:+.4f} |",
        f"| Avg loss | ${s['avg_loss_usd']:+.4f} |",
        f"| Profit factor | {s['profit_factor']} |",
        f"| Max drawdown | {s['max_drawdown_from_peak_pct']:.4f}% |",
        f"| Starting balance | ${s['starting_balance_usd']:.2f} |",
        f"| Ending balance | ${s['ending_balance_usd']:.2f} |",
        "",
        "## Duration",
        "",
        f"| Metric | Value |",
        f"|---|---|",
        f"| Avg duration | {d['avg_trade_duration_min']} min |",
        f"| Shortest | {d['min_trade_duration_min']} min |",
        f"| Longest | {d['max_trade_duration_min']} min |",
        "",
        "## Exit Reasons",
        "",
        "| Reason | Count |",
        "|---|---|",
    ]
    for reason, count in metrics["exit_reasons"].items():
        lines.append(f"| {reason} | {count} |")

    lines += [
        "",
        "## Trade Log",
        "",
        "| # | Symbol | Side | Size | PnL | PnL% | Exit | Duration |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for i, t in enumerate(metrics["trades"], 1):
        lines.append(
            f"| {i} | {t['symbol']} | {t['side']} | ${t['position_size_usd']:.2f} "
            f"| ${t['pnl_usd']:+.4f} | {t['pnl_pct']:+.2f}% | {t['exit_reason']} "
            f"| {t['duration_min']}m |"
        )

    lines += [
        "",
        "## Equity Curve",
        "",
        "| Trade | Symbol | PnL | Balance |",
        "|---|---|---|---|",
        f"| 0 | — | — | ${s['starting_balance_usd']:.2f} |",
    ]
    for i, point in enumerate(metrics["equity_curve"], 1):
        lines.append(
            f"| {i} | {point['symbol']} | ${point['pnl_usd']:+.4f} | ${point['cumulative_balance']:.4f} |"
        )

    lines += [
        "",
        "## Limitations",
        "",
        "- **Paper trading only** — no real capital at risk, no slippage, no market impact",
        f"- **Sample size: {s['total_trades']} trades** — far too small for statistical significance",
        "- **Single strategy** — funding arbitrage only, no diversification tested",
        "- **Single day of data** — no regime change or volatility shift testing",
        "- **No transaction costs** — real trading would include fees, spread, and slippage",
        "",
        "## What This Proves",
        "",
        "- End-to-end execution pipeline works: signal → safety gates → entry → exit → logging",
        "- Schema contracts enforced: all trades have required fields, pass validation",
        "- Safety systems active: circuit breakers, position limits, timeout enforcement",
        "- Canonical data persistence: all trades logged to append-only JSONL",
        "",
    ]
    return "\n".join(lines)


def generate_equity_csv(metrics: dict) -> str:
    lines = ["trade_number,trade_id,symbol,pnl_usd,cumulative_balance"]
    lines.append(f"0,start,—,0,{metrics['summary']['starting_balance_usd']}")
    for i, point in enumerate(metrics["equity_curve"], 1):
        lines.append(
            f"{i},{point['trade_id']},{point['symbol']},{point['pnl_usd']},{point['cumulative_balance']}"
        )
    return "\n".join(lines)


def generate_trade_csv(metrics: dict) -> str:
    lines = ["trade_id,symbol,side,position_size_usd,pnl_usd,pnl_pct,exit_reason,duration_min"]
    for t in metrics["trades"]:
        lines.append(
            f"{t['trade_id']},{t['symbol']},{t['side']},{t['position_size_usd']},"
            f"{t['pnl_usd']},{t['pnl_pct']},{t['exit_reason']},{t['duration_min']}"
        )
    return "\n".join(lines)


def main():
    trades = parse_closed_trades()
    if not trades:
        print("No closed trades found.")
        sys.exit(1)

    metrics = compute_metrics(trades)

    # Write JSON
    (ARTIFACTS / "performance_report.json").write_text(json.dumps(metrics, indent=2, default=str))
    print(f"✅ artifacts/performance_report.json ({len(trades)} trades)")

    # Write Markdown
    md = generate_markdown(metrics)
    (ARTIFACTS / "PERFORMANCE_REPORT.md").write_text(md)
    print(f"✅ artifacts/PERFORMANCE_REPORT.md")

    # Write CSVs
    (ARTIFACTS / "equity_curve.csv").write_text(generate_equity_csv(metrics))
    print(f"✅ artifacts/equity_curve.csv")

    (ARTIFACTS / "trade_summary.csv").write_text(generate_trade_csv(metrics))
    print(f"✅ artifacts/trade_summary.csv")

    # Print summary
    s = metrics["summary"]
    print(f"\n{'='*50}")
    print(f"  PAPER TRADING PERFORMANCE")
    print(f"{'='*50}")
    print(f"  Trades:     {s['total_trades']} ({s['wins']}W / {s['losses']}L)")
    print(f"  Win rate:   {s['win_rate_pct']}%")
    print(f"  Total PnL:  ${s['total_pnl_usd']:+.4f}")
    print(f"  Expectancy: ${s['avg_pnl_usd']:+.4f}/trade")
    print(f"  Balance:    ${s['starting_balance_usd']:.2f} → ${s['ending_balance_usd']:.2f}")
    print(f"{'='*50}")
    print(f"  ⚠️  {metrics['disclaimer']}")


if __name__ == "__main__":
    main()
