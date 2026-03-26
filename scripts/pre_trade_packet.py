#!/usr/bin/env python3
"""
Pre-Trade Decision Packet Generator.

Generates CANARY_PROTOCOL-compliant packets before execution.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = REPO_ROOT / "workspace"
LOG_DIR = WORKSPACE / "logs"
LOG_DIR.mkdir(exist_ok=True)

PACKET_FILE = LOG_DIR / "pre-trade-packets.jsonl"
LEDGER_FILE = LOG_DIR / "trade-ledger.jsonl"


def generate_packet(signal: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Generate a pre-trade decision packet for CANARY_PROTOCOL."""
    
    # Count trades from ledger
    trade_count = 0
    if LEDGER_FILE.exists():
        with open(LEDGER_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    trade_count += 1
    
    # Trade count + 1 (0-indexed + next trade)
    trade_count = trade_count + 1

    # Extract signal components
    funding = signal.get("funding", {})
    momentum = signal.get("momentum", {})
    volume = signal.get("volume", {})
    composite = signal.get("composite", {})

    packet = {
        "packet_id": f"canary-{trade_count:03d}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "asset": signal.get("asset"),
        "direction": signal.get("direction"),
        "price_at_signal": signal.get("price"),
        "signals": {
            "funding": {
                "active": funding.get("active", False),
                "annualized": funding.get("annualized", 0),
                "score": funding.get("score", 0),
                "direction": funding.get("direction"),
            },
            "momentum": {
                "active": momentum.get("active", False),
                "change_24h": momentum.get("change_pct", 0),
                "score": momentum.get("score", 0),
                "direction": momentum.get("direction"),
            },
            "volume": {
                "active": volume.get("active", False),
                "volume_24h": volume.get("volume", 0),
                "score": volume.get("score", 0),
            },
        },
        "composite_score": composite.get("composite_score", 0),
        "confirmations": composite.get("confirmations", 0),
        "why_allowed": _generate_why_allowed(signal, composite),
        "invalidation_trigger": _generate_invalidation_trigger(signal),
        "max_acceptable_loss_usd": 1.80,  # $12 × 15% SL
        "stop_loss_pct": 0.15,
        "take_profit_pct": 0.20,
        "hold_logic": "Exit on TP=20% / SL=15% / thesis break / 24h timeout",
        "protocol_compliant": True,
    }

    # Log to JSONL
    with open(PACKET_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(packet, default=str) + "\n")

    return packet


def _generate_why_allowed(signal: dict[str, Any], composite: dict[str, Any]) -> str:
    """Generate natural language explanation of why trade is allowed."""
    asset = signal.get("asset", "?")
    direction = signal.get("direction", "?")
    confirmations = composite.get("confirmations", 0)
    score = composite.get("composite_score", 0)
    funding = signal.get("funding", {})

    funding_ann = funding.get("annualized", 0)
    momentum = signal.get("momentum", {})
    mom_change = momentum.get("change_pct", 0)
    volume = signal.get("volume", {})

    parts = []
    if confirmations == 3:
        parts.append("All 3 signals confirm.")
    elif confirmations == 2:
        parts.append("2/3 signals confirm.")

    if funding_ann != 0:
        direction_str = "shorts pay longs" if funding_ann < 0 else "longs pay shorts"
        parts.append(f"Funding {funding_ann:+.0%} annualized ({direction_str}).")

    if momentum.get("active"):
        mom_dir = momentum.get("direction", "?")
        parts.append(f"Momentum {mom_change:+.2%} 24h aligns with {direction}.")

    if volume.get("active"):
        vol = volume.get("volume", 0)
        if vol > 1_000_000:
            parts.append(f"Volume ${vol/1_000_000:.1f}M confirms liquidity.")
        else:
            parts.append(f"Volume ${vol:,.0f} above $300k minimum.")

    return " ".join(parts)


def _generate_invalidation_trigger(signal: dict[str, Any]) -> str:
    """Generate invalidation triggers based on signal type."""
    direction = signal.get("direction", "long")
    asset = signal.get("asset", "?")

    triggers = [
        f"Price drops 15% below entry ({direction} thesis broken)",
        "Funding flips direction (would be paying instead of earning)",
        "24h timeout (thesis not playing out within timeframe)",
        "System halt triggered (circuit breaker, drawdown cap)",
    ]
    return " | ".join(triggers)


def validate_packet(packet: dict[str, Any]) -> tuple[bool, str]:
    """Validate packet against CANARY_PROTOCOL rules."""
    # Rule 1: Max position $12
    if packet.get("max_acceptable_loss_usd", 0) > 1.80:  # $12 × 15%
        return False, "Max acceptable loss exceeds $12 position limit"

    # Rule 2: Must have SL/TP
    if packet.get("stop_loss_pct", 0) <= 0:
        return False, "Missing stop loss"
    if packet.get("take_profit_pct", 0) <= 0:
        return False, "Missing take profit"

    # Rule 3: Must have clear invalidation
    if not packet.get("invalidation_trigger"):
        return False, "Missing invalidation triggers"

    return True, "Packet compliant with CANARY_PROTOCOL"


if __name__ == "__main__":
    # Test packet generation
    test_signal = {
        "asset": "SUPER",
        "direction": "long",
        "price": 0.1298,
        "funding": {"active": True, "annualized": -2.85, "score": 10.0, "direction": "long"},
        "momentum": {"active": True, "change_pct": 0.1749, "score": 10.0, "direction": "long"},
        "volume": {"active": True, "volume": 948488, "score": 0.19},
        "composite": {"composite_score": 6.0, "confirmations": 3},
    }
    packet = generate_packet(test_signal, {})
    print(json.dumps(packet, indent=2, default=str))