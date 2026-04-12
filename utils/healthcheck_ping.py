"""
Push-based uptime monitoring.
Pings an external healthcheck URL (e.g. Healthchecks.io) after each
successful scan cycle. If pings stop, the monitoring service alerts.

Opt-in: does nothing if HEALTHCHECK_PING_URL is not set.
"""

import os
import logging
import threading

logger = logging.getLogger(__name__)

HEALTHCHECK_PING_URL = os.environ.get("HEALTHCHECK_PING_URL", "").strip()


def ping_healthcheck():
    """
    Send a non-blocking ping to the healthcheck URL.
    Runs in a daemon thread so it never blocks the scan loop.
    Fails silently — monitoring should never affect trading.
    """
    if not HEALTHCHECK_PING_URL:
        return

    def _ping():
        try:
            import urllib.request
            req = urllib.request.Request(HEALTHCHECK_PING_URL, method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                resp.read()
        except Exception as e:
            logger.debug(f"Healthcheck ping failed: {e}")

    thread = threading.Thread(target=_ping, daemon=True)
    thread.start()
