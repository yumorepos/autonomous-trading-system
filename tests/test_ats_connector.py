"""Tests for ATSConnector — JSONL file tailing and event parsing."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.bridge.ats_connector import ATSConnector
from src.models import RegimeTier


@pytest.fixture
def tmp_dir(tmp_path):
    """Create temp directory with empty JSONL and state files."""
    jsonl = tmp_path / "engine.jsonl"
    jsonl.touch()
    state = tmp_path / "regime_state.json"
    state.write_text(json.dumps({
        "regime": "HIGH_FUNDING",
        "max_funding_apy": 1.50,
        "top_assets": [{"asset": "ETH", "exchange": "hyperliquid", "funding_apy": 1.50}],
        "updated_at": "2026-04-13T12:00:00Z",
    }))
    return tmp_path, jsonl, state


def _make_event(prev="MODERATE", new="HIGH_FUNDING", apy=1.50, ts="2026-04-13T12:00:00Z"):
    return json.dumps({
        "event": "regime_updated",
        "previous_regime": prev,
        "new_regime": new,
        "max_funding_apy": apy,
        "pct_above_100": 0.15,
        "thresholds": {"tier1_min_funding": 0.5, "tier2_min_funding": 1.0},
        "timestamp": ts,
    })


class TestParseEvent:
    def test_valid_regime_updated(self, tmp_dir):
        _, jsonl, state = tmp_dir
        connector = ATSConnector(jsonl_path=jsonl, state_path=state)
        line = _make_event()
        event = connector.parse_event(line)

        assert event is not None
        assert event.new_regime == RegimeTier.HIGH_FUNDING
        assert event.previous_regime == RegimeTier.MODERATE
        assert event.max_apy_annualized == 150.0  # 1.50 * 100
        assert event.asset == "ETH"  # from regime_state.json
        assert event.exchange == "hyperliquid"

    def test_ignores_non_regime_events(self, tmp_dir):
        _, jsonl, state = tmp_dir
        connector = ATSConnector(jsonl_path=jsonl, state_path=state)
        line = json.dumps({"event": "scan_complete", "assets_scanned": 50})
        assert connector.parse_event(line) is None

    def test_ignores_invalid_json(self, tmp_dir):
        _, jsonl, state = tmp_dir
        connector = ATSConnector(jsonl_path=jsonl, state_path=state)
        assert connector.parse_event("not json at all") is None
        assert connector.parse_event("") is None

    def test_unknown_regime_returns_none(self, tmp_dir):
        _, jsonl, state = tmp_dir
        connector = ATSConnector(jsonl_path=jsonl, state_path=state)
        line = _make_event(prev="UNKNOWN_TIER", new="HIGH_FUNDING")
        assert connector.parse_event(line) is None

    def test_decimal_to_percentage_conversion(self, tmp_dir):
        _, jsonl, state = tmp_dir
        connector = ATSConnector(jsonl_path=jsonl, state_path=state)
        line = _make_event(apy=0.3258)
        event = connector.parse_event(line)
        assert event is not None
        assert abs(event.max_apy_annualized - 32.58) < 0.01

    def test_fallback_when_no_state_file(self, tmp_path):
        jsonl = tmp_path / "engine.jsonl"
        jsonl.touch()
        state = tmp_path / "nonexistent.json"
        connector = ATSConnector(jsonl_path=jsonl, state_path=state)
        line = _make_event()
        event = connector.parse_event(line)
        assert event is not None
        assert event.asset == "UNKNOWN"
        assert event.exchange == "hyperliquid"  # default


class TestFileReading:
    def test_read_new_lines(self, tmp_dir):
        _, jsonl, state = tmp_dir
        connector = ATSConnector(jsonl_path=jsonl, state_path=state)

        # Write 3 lines
        with open(jsonl, "w") as f:
            f.write(_make_event() + "\n")
            f.write(_make_event(prev="LOW_FUNDING", new="MODERATE") + "\n")
            f.write(json.dumps({"event": "scan_complete"}) + "\n")

        lines = connector.read_new_lines()
        assert len(lines) == 3

        # No new lines on second read
        assert connector.read_new_lines() == []

    def test_incremental_reads(self, tmp_dir):
        _, jsonl, state = tmp_dir
        connector = ATSConnector(jsonl_path=jsonl, state_path=state)

        # First batch
        with open(jsonl, "w") as f:
            f.write(_make_event() + "\n")
        assert len(connector.read_new_lines()) == 1

        # Append more
        with open(jsonl, "a") as f:
            f.write(_make_event(new="MODERATE") + "\n")
        assert len(connector.read_new_lines()) == 1

    def test_seek_to_end_skips_existing(self, tmp_dir):
        _, jsonl, state = tmp_dir

        with open(jsonl, "w") as f:
            f.write(_make_event() + "\n")
            f.write(_make_event() + "\n")

        connector = ATSConnector(jsonl_path=jsonl, state_path=state)
        connector.seek_to_end()
        assert connector.read_new_lines() == []

        # New line after seek
        with open(jsonl, "a") as f:
            f.write(_make_event() + "\n")
        assert len(connector.read_new_lines()) == 1

    def test_handles_file_truncation(self, tmp_dir):
        _, jsonl, state = tmp_dir
        connector = ATSConnector(jsonl_path=jsonl, state_path=state)

        # Write a lot then read
        with open(jsonl, "w") as f:
            for _ in range(10):
                f.write(_make_event() + "\n")
        connector.read_new_lines()

        # Truncate (simulate log rotation)
        with open(jsonl, "w") as f:
            f.write(_make_event() + "\n")

        lines = connector.read_new_lines()
        assert len(lines) == 1


class TestPollOnce:
    def test_poll_returns_only_regime_events(self, tmp_dir):
        _, jsonl, state = tmp_dir
        connector = ATSConnector(jsonl_path=jsonl, state_path=state)

        with open(jsonl, "w") as f:
            f.write(_make_event() + "\n")
            f.write(json.dumps({"event": "scan_complete"}) + "\n")
            f.write(_make_event(prev="HIGH_FUNDING", new="MODERATE") + "\n")

        events = connector.poll_once()
        assert len(events) == 2
        assert events[0].new_regime == RegimeTier.HIGH_FUNDING
        assert events[1].new_regime == RegimeTier.MODERATE

    def test_callback_invoked(self, tmp_dir):
        _, jsonl, state = tmp_dir
        connector = ATSConnector(jsonl_path=jsonl, state_path=state)

        received = []
        connector.on_event(lambda e: received.append(e))

        with open(jsonl, "w") as f:
            f.write(_make_event() + "\n")

        connector.poll_once()
        assert len(received) == 1
        assert received[0].new_regime == RegimeTier.HIGH_FUNDING
