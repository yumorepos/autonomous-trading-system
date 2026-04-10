"""
ALERTING — Push notifications for trade events and system health.

Supports Telegram. Add more backends (Discord, SMS) by adding send functions.

Setup:
  1. Message @BotFather on Telegram -> /newbot -> save token
  2. Get chat_id: curl https://api.telegram.org/bot<TOKEN>/getUpdates
  3. Set env vars: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timezone

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

_LEVEL_PREFIX = {
    "INFO": "\u2139\ufe0f",
    "WARN": "\u26a0\ufe0f",
    "CRITICAL": "\U0001f6a8",
}


def send_alert(message: str, level: str = "INFO") -> bool:
    """Send alert via Telegram. Returns True on success.

    Levels: INFO, WARN, CRITICAL
    Silently returns False if credentials are not configured.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    prefix = _LEVEL_PREFIX.get(level, "")
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    text = f"{prefix} <b>ATS</b> [{ts}]\n{message}"

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = json.dumps({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    }).encode()

    try:
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Convenience helpers for common events
# ---------------------------------------------------------------------------

def alert_entry(coin: str, direction: str, size_usd: float, tier: int, price: float) -> bool:
    return send_alert(
        f"ENTRY: {coin} {direction} ${size_usd:.2f} (T{tier}) @ {price}",
        "INFO",
    )


def alert_exit(coin: str, reason: str, pnl_usd: float, pnl_pct: float) -> bool:
    level = "INFO" if pnl_usd >= 0 else "WARN"
    return send_alert(
        f"EXIT: {coin} — {reason}\nPnL: ${pnl_usd:+.4f} ({pnl_pct:+.2%})",
        level,
    )


def alert_circuit_breaker(reason: str) -> bool:
    return send_alert(f"CIRCUIT BREAKER TRIPPED\n{reason}", "CRITICAL")


def alert_engine_event(event: str) -> bool:
    return send_alert(event, "INFO")


def alert_error(context: str, error: str) -> bool:
    return send_alert(f"ERROR in {context}\n{error}", "CRITICAL")
