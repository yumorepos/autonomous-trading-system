"""
Minimal health endpoint for external uptime monitoring.
Runs as a daemon thread inside the trading engine.
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import time
import threading
import logging

logger = logging.getLogger(__name__)

# Global reference — the engine updates this dict every scan cycle
_health_state = {
    "status": "starting",
    "last_heartbeat": 0,
    "scan_count": 0,
    "regime": "UNKNOWN",
    "open_positions": 0,
    "uptime_seconds": 0,
    "engine_start_time": 0,
}


def update_health(scan_count=None, regime=None, open_positions=None):
    """Called by trading_engine.py after each scan cycle."""
    _health_state["last_heartbeat"] = time.time()
    _health_state["status"] = "running"
    if scan_count is not None:
        _health_state["scan_count"] = scan_count
    if regime is not None:
        _health_state["regime"] = regime
    if open_positions is not None:
        _health_state["open_positions"] = open_positions
    if _health_state["engine_start_time"] > 0:
        _health_state["uptime_seconds"] = round(
            time.time() - _health_state["engine_start_time"]
        )


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/health":
            self.send_response(404)
            self.end_headers()
            return

        heartbeat_age = time.time() - _health_state["last_heartbeat"]
        # Healthy if heartbeat is less than 5 minutes old
        # (engine scans every 2 min, so 5 min gives generous margin)
        healthy = (
            _health_state["status"] == "running"
            and heartbeat_age < 300
        )

        response = {
            "healthy": healthy,
            "status": _health_state["status"],
            "heartbeat_age_seconds": round(heartbeat_age, 1),
            "scan_count": _health_state["scan_count"],
            "regime": _health_state["regime"],
            "open_positions": _health_state["open_positions"],
            "uptime_seconds": _health_state["uptime_seconds"],
        }

        self.send_response(200 if healthy else 503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(json.dumps(response).encode())

    def log_message(self, format, *args):
        """Suppress default access logging — too noisy for a polling endpoint."""
        pass


def start_health_server(port=8080):
    """Start the health HTTP server in a daemon thread."""
    _health_state["engine_start_time"] = time.time()
    _health_state["last_heartbeat"] = time.time()

    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info(f"Health server started on port {port}")
    return server
