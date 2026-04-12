"""Tests for push-based healthcheck ping."""

import time
import utils.healthcheck_ping as hc


class TestHealthcheckPing:
    def test_noop_when_url_empty(self):
        """With no URL set, ping returns immediately without error."""
        original = hc.HEALTHCHECK_PING_URL
        try:
            hc.HEALTHCHECK_PING_URL = ""
            hc.ping_healthcheck()  # Should return immediately, no error
        finally:
            hc.HEALTHCHECK_PING_URL = original

    def test_silent_failure_on_bogus_url(self):
        """With a bogus URL, ping fails silently in background thread."""
        original = hc.HEALTHCHECK_PING_URL
        try:
            hc.HEALTHCHECK_PING_URL = "http://localhost:99999/bogus"
            hc.ping_healthcheck()
            time.sleep(0.5)  # Let thread finish — should not crash
        finally:
            hc.HEALTHCHECK_PING_URL = original

    def test_non_blocking(self):
        """ping_healthcheck() returns near-instantly (spawns daemon thread)."""
        original = hc.HEALTHCHECK_PING_URL
        try:
            hc.HEALTHCHECK_PING_URL = "http://localhost:99999/bogus"
            start = time.monotonic()
            hc.ping_healthcheck()
            elapsed = time.monotonic() - start
            assert elapsed < 0.01, f"ping_healthcheck() took {elapsed:.3f}s, expected < 0.01s"
        finally:
            hc.HEALTHCHECK_PING_URL = original
