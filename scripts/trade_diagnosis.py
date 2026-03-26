#!/usr/bin/env python3
"""
Trade Diagnosis Engine — Post-trade failure analysis and signal refinement.

Runs after every trade close. Classifies failures, decomposes signals,
tracks feature importance, and produces improvement recommendations.

Usage:
    python scripts/trade_diagnosis.py                # Diagnose all trades
    python scripts/trade_diagnosis.py --trade-id X   # Diagnose specific trade
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.runtime import WORKSPACE_ROOT as WORKSPACE, LOGS_DIR

# Load trade ledger
_spec = importlib.util.spec_from_file_location("trade_ledger", REPO_ROOT / "scripts" / "trade_ledger.py")
_ledger = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ledger)

DIAGNOSIS_FILE = LOGS_DIR / "trade-diagnosis.jsonl"
DIAGNOSIS_REPORT = WORKSPACE / "TRADE_DIAGNOSIS_REPORT.md"

# Min pattern count before enforcing a rule change
MIN_PATTERN_COUNT = 3


# ---------------------------------------------------------------------------
# 1. Failure Classification
# ---------------------------------------------------------------------------

FAILURE_CATEGORIES = {
    "funding_misread": "Entered funding arb but paid funding instead of earning",
    "wrong_direction": "Price moved against position direction",
    "false_signal": "Signal score was above threshold but setup was low quality",
    "low_liquidity": "Asset had thin order book or wide spread",
    "volatility_spike": "Sudden price move exceeded normal range",
    "late_entry": "Entered after the move already happened",
    "regime_mismatch": "Market regime changed after entry (trend reversal, volatility shift)",
    "timeout_exit": "Position expired without reaching TP or SL",
    "thesis_correct_but_slow": "Thesis was right but took too long, exited early",
}


def classify_failure(trade: dict[str, Any]) -> list[str]:
    """Classify a losing trade into 1-2 failure categories."""
    reasons = []
    pnl = trade.get("pnl_usd", 0)
    exit_reason = trade.get("exit_reason", "")
    entry_reason = trade.get("entry_reason", {})
    signal_type = entry_reason.get("signal_type", "")
    funding_rate = entry_reason.get("funding_rate", entry_reason.get("annualized_rate", 0))
    direction = trade.get("direction", "")
    funding_earned = trade.get("funding_earned_usd", 0)

    if pnl >= 0:
        return ["winner"]

    # Funding misread: entered for funding arb but paid funding
    if signal_type == "funding_anomaly" and funding_earned < 0:
        reasons.append("funding_misread")

    # Wrong direction: price moved against us
    entry_px = trade.get("entry_price", 0)
    exit_px = trade.get("exit_price", 0)
    if entry_px > 0 and exit_px > 0:
        if direction in ("long", "yes") and exit_px < entry_px:
            reasons.append("wrong_direction")
        elif direction in ("short", "no") and exit_px > entry_px:
            reasons.append("wrong_direction")

    # Timeout
    if exit_reason == "timeout":
        reasons.append("timeout_exit")

    # Thesis invalidated early
    if exit_reason == "thesis_invalidated":
        if not reasons:
            reasons.append("false_signal")

    # Low liquidity proxy: small signal score or low volume
    volume = entry_reason.get("volume_24h", 0)
    if volume and volume < 500_000:
        reasons.append("low_liquidity")

    # Default if nothing else matched
    if not reasons:
        reasons.append("false_signal")

    return reasons[:2]


# ---------------------------------------------------------------------------
# 2. Signal Decomposition
# ---------------------------------------------------------------------------

def decompose_signal(trade: dict[str, Any]) -> dict[str, Any]:
    """Break down which signal components contributed to the outcome."""
    entry_reason = trade.get("entry_reason", {})
    market = trade.get("market_conditions", {})
    pnl = trade.get("pnl_usd", 0)
    is_win = pnl > 0

    components = {}

    # Funding rate
    funding = entry_reason.get("annualized_rate", entry_reason.get("funding_rate", 0))
    if funding:
        components["funding_rate"] = {
            "value": funding,
            "predicted": "long" if funding < 0 else "short",
            "actual_direction": trade.get("direction"),
            "contributed_to_outcome": is_win,
        }

    # Volume
    volume = entry_reason.get("volume_24h", market.get("volume_24h", 0))
    if volume:
        components["volume_24h"] = {
            "value": volume,
            "above_500k": volume > 500_000,
            "above_1m": volume > 1_000_000,
        }

    # Signal score
    score = trade.get("signal_score", 0)
    components["signal_score"] = {
        "value": score,
        "outcome": "win" if is_win else "loss",
    }

    # Funding earned vs expected
    funding_earned = trade.get("funding_earned_usd", 0)
    if trade.get("entry_reason", {}).get("signal_type") == "funding_anomaly":
        components["funding_execution"] = {
            "earned": funding_earned,
            "expected_positive": True,
            "actual_positive": funding_earned > 0,
            "thesis_held": funding_earned > 0,
        }

    return components


# ---------------------------------------------------------------------------
# 3. Feature Importance (directional heuristics)
# ---------------------------------------------------------------------------

def compute_feature_importance(trades: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Rank signal features by contribution to wins vs losses."""
    features: dict[str, dict[str, list]] = defaultdict(lambda: {"win": [], "loss": []})

    for t in trades:
        pnl = t.get("pnl_usd", 0)
        bucket = "win" if pnl > 0 else "loss"
        entry = t.get("entry_reason", {})
        market = t.get("market_conditions", {})

        # Score
        features["signal_score"][bucket].append(t.get("signal_score", 0))

        # Funding
        fr = entry.get("annualized_rate", 0)
        if fr:
            features["funding_annualized"][bucket].append(abs(fr))

        # Volume
        vol = entry.get("volume_24h", market.get("volume_24h", 0))
        if vol:
            features["volume_24h"][bucket].append(vol)

        # Hold time
        features["hold_minutes"][bucket].append(t.get("time_held_minutes", 0))

    result = {}
    for feature, buckets in features.items():
        win_avg = sum(buckets["win"]) / len(buckets["win"]) if buckets["win"] else 0
        loss_avg = sum(buckets["loss"]) / len(buckets["loss"]) if buckets["loss"] else 0
        win_n = len(buckets["win"])
        loss_n = len(buckets["loss"])

        result[feature] = {
            "win_avg": round(win_avg, 4),
            "loss_avg": round(loss_avg, 4),
            "win_count": win_n,
            "loss_count": loss_n,
            "direction": "higher_wins" if win_avg > loss_avg else "higher_losses" if loss_avg > win_avg else "neutral",
            "confidence": "low" if (win_n + loss_n) < 5 else "medium" if (win_n + loss_n) < 15 else "high",
        }

    return result


# ---------------------------------------------------------------------------
# 4. Improvement Recommendations
# ---------------------------------------------------------------------------

def generate_recommendations(
    failures: dict[str, int],
    importance: dict[str, dict],
    trade_count: int,
) -> list[dict[str, Any]]:
    """Generate signal improvement recommendations. Conservative — requires patterns."""
    recs = []

    # Only recommend changes if we've seen the same failure 3+ times
    for category, count in sorted(failures.items(), key=lambda x: -x[1]):
        if category == "winner":
            continue

        rec: dict[str, Any] = {
            "failure": category,
            "occurrences": count,
            "description": FAILURE_CATEGORIES.get(category, "unknown"),
        }

        if count >= MIN_PATTERN_COUNT:
            rec["confidence"] = "actionable"

            if category == "funding_misread":
                rec["recommendation"] = "Add pre-entry funding direction check: verify we EARN funding on the position, not pay it"
                rec["implementation"] = "In hl_entry.py gate: reject if funding_rate sign doesn't align with earning"
            elif category == "wrong_direction":
                rec["recommendation"] = "Add trend filter: require price momentum aligned with entry direction over last 4h"
                rec["implementation"] = "Compare current price vs 4h-ago price — reject counter-trend entries"
            elif category == "low_liquidity":
                rec["recommendation"] = "Raise minimum volume threshold from $100k to $500k"
                rec["implementation"] = "In hl_entry.py: MIN_VOLUME_24H = 500_000"
            elif category == "false_signal":
                rec["recommendation"] = "Raise minimum signal score from 5.0 to 7.0"
                rec["implementation"] = "In hl_entry.py: MIN_SIGNAL_SCORE = 7.0"
            elif category == "timeout_exit":
                rec["recommendation"] = "Reduce timeout from 24h to 12h — if thesis hasn't played out by then, it won't"
                rec["implementation"] = "In risk-guardian.py: TIMEOUT_HOURS = 12"
            else:
                rec["recommendation"] = f"Investigate {category} pattern further"
                rec["implementation"] = "Manual review needed"
        else:
            rec["confidence"] = "observation_only"
            rec["recommendation"] = f"Seen {count}x — monitor but don't change yet (need {MIN_PATTERN_COUNT}+)"

        recs.append(rec)

    return recs


# ---------------------------------------------------------------------------
# 5. Trade Diagnosis Report
# ---------------------------------------------------------------------------

def diagnose_trade(trade: dict[str, Any]) -> dict[str, Any]:
    """Produce full diagnosis for a single trade."""
    failures = classify_failure(trade)
    components = decompose_signal(trade)
    pnl = trade.get("pnl_usd", 0)

    diagnosis = {
        "trade_id": trade.get("trade_id"),
        "asset": trade.get("asset"),
        "pnl_usd": pnl,
        "outcome": "WIN" if pnl > 0 else "LOSS",
        "failure_categories": failures,
        "signal_decomposition": components,
        "what_worked": [],
        "what_failed": [],
        "should_change": [],
        "conclusion_confidence": "low",  # Always low with small sample
    }

    # What worked
    if trade.get("exit_reason") == "thesis_invalidated":
        diagnosis["what_worked"].append("Early exit on broken thesis — limited loss")
    if trade.get("time_held_minutes", 0) < 120 and pnl < 0:
        diagnosis["what_worked"].append("Quick exit — didn't let loser run")
    if pnl > 0:
        diagnosis["what_worked"].append(f"Profitable trade: +${pnl:.4f}")

    # What failed
    for f in failures:
        if f != "winner":
            diagnosis["what_failed"].append(FAILURE_CATEGORIES.get(f, f))

    # Changes (cautious)
    if "funding_misread" in failures:
        diagnosis["should_change"].append("Add funding direction verification before entry")
    if "wrong_direction" in failures:
        diagnosis["should_change"].append("Consider adding trend alignment filter")
    if "low_liquidity" in failures:
        diagnosis["should_change"].append("Increase minimum volume threshold")

    if not diagnosis["should_change"]:
        diagnosis["should_change"].append("No changes recommended from single trade — need more data")

    return diagnosis


def diagnose_all() -> dict[str, Any]:
    """Run diagnosis on all closed trades and generate report."""
    trades = _ledger.load_closed_trades()
    if not trades:
        return {"status": "NO_TRADES"}

    diagnoses = [diagnose_trade(t) for t in trades]
    failure_counts: dict[str, int] = defaultdict(int)
    for d in diagnoses:
        for f in d["failure_categories"]:
            failure_counts[f] += 1

    importance = compute_feature_importance(trades)
    recommendations = generate_recommendations(failure_counts, importance, len(trades))

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "trade_count": len(trades),
        "diagnoses": diagnoses,
        "failure_distribution": dict(failure_counts),
        "feature_importance": importance,
        "recommendations": recommendations,
    }

    # Save diagnosis log
    for d in diagnoses:
        d["diagnosed_at"] = datetime.now(timezone.utc).isoformat()
        with open(DIAGNOSIS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(d, default=str) + "\n")

    return report


# ---------------------------------------------------------------------------
# Markdown Report
# ---------------------------------------------------------------------------

def write_report(report: dict[str, Any]) -> str:
    lines = [
        "# Trade Diagnosis Report",
        f"\n> Generated: {report.get('generated_at', '?')}",
        f"> Trades analyzed: {report.get('trade_count', 0)}",
        "",
    ]

    # Per-trade diagnosis
    for d in report.get("diagnoses", []):
        outcome = "✅ WIN" if d["outcome"] == "WIN" else "❌ LOSS"
        lines.append(f"## {d['trade_id']} — {d['asset']} ({outcome}: ${d['pnl_usd']:+.4f})")
        lines.append(f"**Failures:** {', '.join(d['failure_categories'])}")
        lines.append(f"**What worked:** {'; '.join(d['what_worked']) if d['what_worked'] else 'Nothing notable'}")
        lines.append(f"**What failed:** {'; '.join(d['what_failed']) if d['what_failed'] else 'N/A'}")
        lines.append(f"**Should change:** {'; '.join(d['should_change'])}")
        lines.append(f"**Confidence:** {d['conclusion_confidence']}")
        lines.append("")

    # Failure distribution
    lines.append("## Failure Distribution")
    for cat, count in sorted(report.get("failure_distribution", {}).items(), key=lambda x: -x[1]):
        desc = FAILURE_CATEGORIES.get(cat, cat)
        lines.append(f"- **{cat}** ({count}x): {desc}")
    lines.append("")

    # Feature importance
    lines.append("## Feature Importance")
    for feat, data in report.get("feature_importance", {}).items():
        lines.append(f"- **{feat}**: win_avg={data['win_avg']} vs loss_avg={data['loss_avg']} → {data['direction']} [{data['confidence']}]")
    lines.append("")

    # Recommendations
    lines.append("## Recommendations")
    for rec in report.get("recommendations", []):
        emoji = "🔧" if rec["confidence"] == "actionable" else "👁️"
        lines.append(f"- {emoji} **{rec['failure']}** ({rec['occurrences']}x) [{rec['confidence']}]")
        lines.append(f"  {rec['recommendation']}")
        if rec.get("implementation"):
            lines.append(f"  Implementation: `{rec['implementation']}`")
    lines.append("")

    text = "\n".join(lines)
    DIAGNOSIS_REPORT.write_text(text, encoding="utf-8")
    return text


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    report = diagnose_all()
    if report.get("status") == "NO_TRADES":
        print("No trades to diagnose. Run trade_ledger.py first.")
        return

    md = write_report(report)
    print(md)

    # Current weaknesses
    print("=" * 60)
    print("  CURRENT SYSTEM WEAKNESSES")
    print("=" * 60)
    weaknesses = [
        "1. No funding direction verification — entered PROVE paying funding (should earn)",
        "2. No trend alignment filter — entered long while price was declining",
        "3. Signal score threshold (5.0) may be too low — PROVE scored 5.6, barely above minimum",
        "4. Single signal type (funding anomaly) — no diversification of alpha sources",
        "5. No regime detection — can't distinguish trending vs mean-reverting markets",
    ]
    for w in weaknesses:
        print(f"  {w}")

    print(f"\n{'='*60}")
    print("  TOP 3 SIGNAL IMPROVEMENTS TO TEST NEXT")
    print("=" * 60)
    improvements = [
        "1. FUNDING DIRECTION GATE: Before entry, verify that our position direction earns funding (long when funding is negative = shorts pay us). Reject if we'd be paying.",
        "2. TREND ALIGNMENT: Compare current price vs 4-hour-ago price. Only enter long if price is flat or rising. Only enter short if flat or falling. This filters counter-trend funding arb entries.",
        "3. RAISE SCORE THRESHOLD TO 7.0: PROVE scored 5.6 and lost. Until we have 10+ trades proving scores 5-7 are viable, default to higher-quality signals only.",
    ]
    for imp in improvements:
        print(f"  {imp}")


if __name__ == "__main__":
    main()
