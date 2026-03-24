#!/usr/bin/env python3
"""Offline isolated proof for the canonical Hyperliquid agency runtime."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SUPPORT_SITECUSTOMIZE = REPO_ROOT / "tests" / "support" / "offline_requests_sitecustomize.py"


def load_json(path: Path):
    return json.loads(path.read_text())


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def write_fixture(path: Path, *, mid_price: float) -> None:
    payload = {
        "hyperliquid": {
            "universe_size": 100,
            "signal_asset": "BTC",
            "entry_price": 50_000.0,
            "funding": -0.0005,
            "dayNtlVlm": 2_000_000.0,
            "openInterest": 20.0,
            "all_mids": {"BTC": mid_price},
            "l2_books": {"BTC": {"bid": 49_990.0, "ask": 50_010.0}},
        },
        "polymarket": {
            "markets": [],
        },
    }
    path.write_text(json.dumps(payload, indent=2))


def build_env(workspace_root: Path, fixture_path: Path, patch_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["OPENCLAW_WORKSPACE"] = str(workspace_root)
    env["OPENCLAW_TRADING_MODE"] = "hyperliquid_only"
    env["OPENCLAW_OFFLINE_FIXTURE"] = str(fixture_path)
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(patch_dir) if not existing_pythonpath else f"{patch_dir}:{existing_pythonpath}"
    return env


def run_agency_cycle(workspace_root: Path, fixture_path: Path, patch_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", "scripts/trading-agency-phase1.py"],
        cwd=REPO_ROOT,
        env=build_env(workspace_root, fixture_path, patch_dir),
        capture_output=True,
        text=True,
        timeout=120,
    )


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="openclaw-agency-hl-") as temp_dir:
        workspace_root = Path(temp_dir)
        logs_dir = workspace_root / "logs"
        patch_dir = workspace_root / "patches"
        patch_dir.mkdir(parents=True, exist_ok=True)
        (patch_dir / "sitecustomize.py").write_text(SUPPORT_SITECUSTOMIZE.read_text())

        fixture_path = workspace_root / "offline-fixture.json"

        write_fixture(fixture_path, mid_price=50_000.0)
        cycle_one = run_agency_cycle(workspace_root, fixture_path, patch_dir)
        assert cycle_one.returncode == 0, cycle_one.stderr or cycle_one.stdout

        trades_path = logs_dir / "phase1-paper-trades.jsonl"
        positions_path = logs_dir / "position-state.json"
        performance_path = logs_dir / "phase1-performance.json"
        safety_path = logs_dir / "execution-safety-state.json"
        report_path = logs_dir / "agency-phase1-report.json"
        cycle_summary_path = logs_dir / "agency-cycle-summary.json"
        runtime_events_path = logs_dir / "runtime-events.jsonl"
        timeout_report_path = workspace_root / "TIMEOUT_MONITOR_REPORT.md"
        cycle_summary_markdown_path = workspace_root / "AGENCY_CYCLE_SUMMARY.md"

        trades_after_entry = load_jsonl(trades_path)
        assert len(trades_after_entry) == 1, trades_after_entry
        entry_trade = trades_after_entry[0]
        assert entry_trade["status"] == "OPEN"
        assert entry_trade["exchange"] == "Hyperliquid"
        assert entry_trade["strategy"] == "funding_arbitrage"
        assert entry_trade["symbol"] == "BTC"
        assert entry_trade["side"] == "LONG"
        assert entry_trade["entry_price"] == 50_000.0
        assert entry_trade["paper_only"] is True

        position_state = load_json(positions_path)
        open_positions = list(position_state["positions"].values())
        assert len(open_positions) == 1, open_positions
        open_position = open_positions[0]
        assert open_position["trade_id"] == entry_trade["trade_id"]
        assert open_position["exchange"] == "Hyperliquid"
        assert open_position["strategy"] == "funding_arbitrage"
        assert open_position["status"] == "OPEN"
        assert open_position["symbol"] == "BTC"
        assert open_position["side"] == "LONG"

        performance_after_entry = load_json(performance_path)
        assert performance_after_entry["total_trades"] == 0, performance_after_entry

        safety_state_after_entry = load_json(safety_path)
        assert safety_state_after_entry["runtime_enforcement"]["last_transition"] == "TRADE_OUTCOME_RECORDED"
        assert safety_state_after_entry["runtime_enforcement"]["last_persisted_trade_count"] == 1

        agency_report_entry = load_json(report_path)
        cycle_summary_entry = load_json(cycle_summary_path)
        assert agency_report_entry["execution_results"]["bootstrap"] == "SUCCESS"
        assert agency_report_entry["execution_results"]["data_integrity"] == "SUCCESS"
        assert agency_report_entry["execution_results"]["signal_scanner"] == "SUCCESS"
        assert agency_report_entry["execution_results"]["safety_validation"] == "SUCCESS"
        assert agency_report_entry["execution_results"]["trader"] == "SUCCESS"
        assert agency_report_entry["execution_results"]["authoritative_state_update"] == "SUCCESS"
        assert agency_report_entry["execution_results"]["monitors"] == "SUCCESS"
        assert agency_report_entry["runtime_summary"] == cycle_summary_entry
        assert cycle_summary_entry["cycle_result"] == "ENTRY_EXECUTED"
        assert cycle_summary_entry["entry_outcome"]["status"] == "executed"
        assert cycle_summary_entry["exit_outcome"]["status"] == "no_open_positions"
        assert cycle_summary_markdown_path.exists(), "AGENCY_CYCLE_SUMMARY.md missing after entry cycle"
        assert timeout_report_path.exists(), "timeout monitor report missing after entry cycle"
        assert runtime_events_path.exists(), "runtime-events.jsonl missing after entry cycle"

        write_fixture(fixture_path, mid_price=55_001.0)
        cycle_two = run_agency_cycle(workspace_root, fixture_path, patch_dir)
        assert cycle_two.returncode == 0, cycle_two.stderr or cycle_two.stdout

        trades_after_exit = load_jsonl(trades_path)
        assert [record["status"] for record in trades_after_exit] == ["OPEN", "CLOSED"], trades_after_exit
        closed_trade = trades_after_exit[-1]
        assert closed_trade["trade_id"] == entry_trade["trade_id"]
        assert closed_trade["exchange"] == "Hyperliquid"
        assert closed_trade["strategy"] == "funding_arbitrage"
        assert closed_trade["exit_reason"] == "take_profit"
        assert closed_trade["exit_price"] == 55_001.0
        assert closed_trade["realized_pnl_usd"] > 0
        assert closed_trade["realized_pnl_pct"] > 0

        position_state_after_exit = load_json(positions_path)
        assert position_state_after_exit["positions"] == {}, position_state_after_exit

        performance_after_exit = load_json(performance_path)
        assert performance_after_exit["total_trades"] == 1, performance_after_exit
        assert performance_after_exit["winners"] == 1, performance_after_exit
        assert performance_after_exit["exchange_breakdown"]["Hyperliquid"]["total_trades"] == 1
        assert performance_after_exit["exchange_breakdown"]["Hyperliquid"]["total_pnl_usd"] == closed_trade["realized_pnl_usd"]

        safety_state_after_exit = load_json(safety_path)
        assert safety_state_after_exit["runtime_enforcement"]["last_transition"] == "TRADE_OUTCOME_RECORDED"
        assert safety_state_after_exit["runtime_enforcement"]["last_persisted_trade_count"] == 1

        agency_report_exit = load_json(report_path)
        cycle_summary_exit = load_json(cycle_summary_path)
        assert agency_report_exit["execution_results"]["safety_validation"] == "SKIPPED"
        assert agency_report_exit["execution_results"]["trader"] == "SUCCESS"
        assert agency_report_exit["execution_results"]["authoritative_state_update"] == "SUCCESS"
        assert agency_report_exit["performance_summary"]["total_trades"] == 1
        assert agency_report_exit["current_state"]["open_positions"] == 0
        assert agency_report_exit["runtime_summary"] == cycle_summary_exit
        assert cycle_summary_exit["cycle_result"] == "EXIT_EXECUTED"
        assert cycle_summary_exit["entry_outcome"]["status"] == "skipped"
        assert cycle_summary_exit["exit_outcome"]["status"] == "executed"

        os.environ["OPENCLAW_WORKSPACE"] = str(workspace_root)
        os.environ["OPENCLAW_TRADING_MODE"] = "hyperliquid_only"
        sys.modules.pop("config.runtime", None)
        dashboard_module = load_module("performance_dashboard_agency_test", REPO_ROOT / "scripts" / "support" / "performance-dashboard.py")
        dashboard = dashboard_module.PerformanceDashboard()
        assert dashboard.calculate_stats(dashboard.hl_trades)["closed"] == 1
        assert dashboard.calculate_stats(dashboard.pm_trades)["closed"] == 0
        assert dashboard.open_positions == []

        print("[OK] Canonical Hyperliquid trading agency path proven offline")
        print(f"[OK] Workspace artifact root: {workspace_root}")
