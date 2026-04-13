#!/usr/bin/env python3
"""
Kill Switch — Emergency halt for all execution.

Usage:
    python -m src.execution.kill_switch activate   # Touch HALT file, stop all trades
    python -m src.execution.kill_switch deactivate  # Remove HALT file, resume trades
    python -m src.execution.kill_switch status      # Check current state
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

HALT_FILE = Path("/opt/trading/HALT")


def _send_telegram(message: str) -> bool:
    """Send Telegram alert. Returns True on success."""
    import json
    import os
    import urllib.request

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
    }).encode()

    try:
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=5)
        return True
    except Exception:
        return False


def activate(reason: str = "manual") -> bool:
    """Activate kill switch — create HALT file, send alert."""
    HALT_FILE.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()
    HALT_FILE.write_text(f"HALTED at {ts} — reason: {reason}\n")
    _send_telegram(f"<b>KILL SWITCH ACTIVATED</b>\nReason: {reason}\nTime: {ts}")
    return True


def deactivate() -> bool:
    """Deactivate kill switch — remove HALT file, send alert."""
    if HALT_FILE.exists():
        HALT_FILE.unlink()
    ts = datetime.now(timezone.utc).isoformat()
    _send_telegram(f"<b>KILL SWITCH DEACTIVATED</b>\nExecution resumed at {ts}")
    return True


def is_halted() -> bool:
    """Check if kill switch is active."""
    return HALT_FILE.exists()


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m src.execution.kill_switch [activate|deactivate|status]")
        sys.exit(1)

    cmd = sys.argv[1].lower()
    reason = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "manual"

    if cmd == "activate":
        activate(reason)
        print(f"Kill switch ACTIVATED — {HALT_FILE}")
    elif cmd == "deactivate":
        deactivate()
        print(f"Kill switch DEACTIVATED — {HALT_FILE} removed")
    elif cmd == "status":
        if is_halted():
            content = HALT_FILE.read_text().strip()
            print(f"HALTED: {content}")
        else:
            print("ACTIVE — no halt file present")
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
