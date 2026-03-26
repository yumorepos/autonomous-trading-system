#!/usr/bin/env python3
"""
ATS Cycle — Unified Entry + Protection in one coordinated run.

Runs entry scan first, then guardian protection check. Single lockfile
prevents overlapping runs. Designed for unattended launchd/cron execution.

Usage:
    python scripts/ats-cycle.py                  # Paper entry + live protection
    ENTRY_MODE=live python scripts/ats-cycle.py  # Live entry + live protection
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.runtime import LOGS_DIR

CYCLE_LOG = LOGS_DIR / "ats-cycle.jsonl"
LOCK_FILE = LOGS_DIR / "ats-cycle.lock"

def log_cycle(event: dict) -> None:
    event["logged_at"] = datetime.now(timezone.utc).isoformat()
    CYCLE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(CYCLE_LOG, "a") as f:
        f.write(json.dumps(event, default=str) + "\n")

def acquire_lock() -> bool:
    if LOCK_FILE.exists():
        try:
            data = json.loads(LOCK_FILE.read_text())
            lock_time = datetime.fromisoformat(data.get("locked_at", ""))
            if lock_time.tzinfo is None:
                lock_time = lock_time.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - lock_time).total_seconds()
            if age < 300:
                return False
        except (json.JSONDecodeError, ValueError, OSError):
            pass
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.write_text(json.dumps({
        "locked_at": datetime.now(timezone.utc).isoformat(),
        "pid": os.getpid(),
    }))
    return True

def release_lock() -> None:
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except OSError:
        pass

def main():
    now = datetime.now(timezone.utc)
    entry_mode = os.environ.get("ENTRY_MODE", "paper")

    print(f"\n{'='*60}")
    print(f"  ATS CYCLE — Entry({entry_mode}) + Protection(live)")
    print(f"  {now.isoformat()}")
    print(f"{'='*60}\n")

    if not acquire_lock():
        print("⚠️ Another cycle is running. Exiting.")
        log_cycle({"event": "cycle_skipped", "reason": "lock_held", "timestamp": now.isoformat()})
        return

    try:
        cycle_result = {"timestamp": now.isoformat(), "entry_mode": entry_mode}

        # Phase 1: Entry scan
        print("━━━ PHASE 1: ENTRY SCAN ━━━\n")
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("hl_entry", REPO_ROOT / "scripts" / "hl_entry.py")
            hl_entry = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(hl_entry)
            entry_result = hl_entry.run_entry()
            cycle_result["entry"] = {
                "result": entry_result.get("result", entry_result.get("action", "unknown")),
                "asset": entry_result.get("asset"),
            }
        except Exception as e:
            print(f"  ❌ Entry error: {type(e).__name__}: {e}")
            cycle_result["entry"] = {"result": "ERROR", "error": str(e)}

        # Phase 2: Guardian protection
        print("\n━━━ PHASE 2: PROTECTION ━━━\n")

        # Remove guardian's own lock since we hold the cycle lock
        guardian_lock = LOGS_DIR / "risk-guardian.lock"
        guardian_lock.unlink(missing_ok=True)

        try:
            spec2 = importlib.util.spec_from_file_location("risk_guardian", REPO_ROOT / "scripts" / "risk-guardian.py")
            guardian = importlib.util.module_from_spec(spec2)
            spec2.loader.exec_module(guardian)
            guardian_result = guardian.run_guardian()
            cycle_result["guardian"] = {
                "positions": guardian_result.get("positions", 0),
                "closes": guardian_result.get("closes", 0),
                "circuit_breaker_ok": guardian_result.get("circuit_breaker_ok", True),
            }
        except Exception as e:
            print(f"  ❌ Guardian error: {type(e).__name__}: {e}")
            cycle_result["guardian"] = {"result": "ERROR", "error": str(e)}

        # Log full cycle
        log_cycle({"event": "cycle_complete", **cycle_result})

        print(f"\n{'='*60}")
        print(f"  CYCLE COMPLETE")
        print(f"  Entry: {cycle_result.get('entry', {}).get('result', '?')}")
        print(f"  Guardian: {cycle_result.get('guardian', {}).get('positions', '?')} positions monitored")
        print(f"{'='*60}\n")

    finally:
        release_lock()

if __name__ == "__main__":
    main()
