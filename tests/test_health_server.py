"""Tests for the HTTP health endpoint."""

import json
import time
import urllib.request
import unittest

from utils.health_server import (
    _health_state,
    start_health_server,
    update_health,
)


class TestHealthServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Use port 0 to let the OS pick a free port
        cls.server = start_health_server(port=0)
        cls.port = cls.server.server_address[1]
        cls.base = f"http://localhost:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def _get(self, path):
        req = urllib.request.Request(f"{self.base}{path}")
        try:
            resp = urllib.request.urlopen(req, timeout=5)
            return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read()
            try:
                return e.code, json.loads(body)
            except Exception:
                return e.code, None

    def test_health_returns_200_when_running(self):
        update_health(scan_count=1, regime="NORMAL", open_positions=0)
        status, body = self._get("/health")
        self.assertEqual(status, 200)
        self.assertTrue(body["healthy"])
        self.assertEqual(body["status"], "running")

    def test_health_reflects_updated_values(self):
        update_health(scan_count=42, regime="RISK_OFF", open_positions=3)
        _, body = self._get("/health")
        self.assertEqual(body["scan_count"], 42)
        self.assertEqual(body["regime"], "RISK_OFF")
        self.assertEqual(body["open_positions"], 3)

    def test_stale_heartbeat_returns_503(self):
        # Force heartbeat to 10 minutes ago
        _health_state["last_heartbeat"] = time.time() - 600
        _health_state["status"] = "running"
        status, body = self._get("/health")
        self.assertEqual(status, 503)
        self.assertFalse(body["healthy"])
        # Restore
        update_health()

    def test_404_on_other_paths(self):
        status, _ = self._get("/other")
        self.assertEqual(status, 404)

    def test_content_type_is_json(self):
        update_health()
        resp = urllib.request.urlopen(f"{self.base}/health", timeout=5)
        self.assertEqual(resp.headers["Content-Type"], "application/json")

    def test_starting_status_is_unhealthy(self):
        _health_state["status"] = "starting"
        _health_state["last_heartbeat"] = time.time()
        status, body = self._get("/health")
        self.assertEqual(status, 503)
        self.assertFalse(body["healthy"])
        # Restore
        update_health()


if __name__ == "__main__":
    unittest.main()
