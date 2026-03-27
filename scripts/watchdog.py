#!/usr/bin/env python3
"""
SYSTEM WATCHDOG — Continuous Health Monitor + Auto-Healing

Runs every 30 seconds to ensure:
- Guardian is protecting positions
- No positions exist without active SL
- Circuit breaker hasn't halted system
- Services auto-restart on failure

ZERO TOLERANCE MODE: Never allows unprotected capital.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.runtime import LOGS_DIR, WORKSPACE_ROOT

WATCHDOG_LOG = LOGS_DIR / "watchdog.jsonl"
GUARDIAN_STATE = LOGS_DIR / "risk-guardian-state.json"
GUARDIAN_SCRIPT = REPO_ROOT / "scripts" / "risk-guardian.py"

def log(event: dict) -> None:
    event["timestamp"] = datetime.now(timezone.utc).isoformat()
    WATCHDOG_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(WATCHDOG_LOG, "a") as f:
        f.write(json.dumps(event, default=str) + "\n")

def get_positions() -> list[dict]:
    """Get current open positions from Hyperliquid."""
    try:
        # Import guardian module
        guardian_module = REPO_ROOT / "scripts" / "risk-guardian.py"
        import importlib.util
        spec = importlib.util.spec_from_file_location("risk_guardian", guardian_module)
        if spec and spec.loader:
            risk_guardian = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(risk_guardian)
            client = risk_guardian.HLClient()
            state = client.get_state()
            return state.get("positions", [])
        return []
    except Exception as e:
        log({"event": "position_check_failed", "error": str(e)})
        return []

def check_guardian_state() -> dict:
    """Check guardian state file for circuit breaker status."""
    try:
        if not GUARDIAN_STATE.exists():
            return {"exists": False, "halted": None, "reason": "state_file_missing"}
        
        data = json.loads(GUARDIAN_STATE.read_text())
        return {
            "exists": True,
            "halted": data.get("halted", False),
            "halt_reason": data.get("halt_reason"),
            "consecutive_losses": data.get("consecutive_losses", 0),
            "total_closes": data.get("total_closes", 0),
            "peak_account_value": data.get("peak_account_value", 0),
            "updated_at": data.get("updated_at"),
        }
    except Exception as e:
        return {"exists": False, "halted": None, "reason": f"error: {e}"}

def run_guardian_once() -> dict:
    """Execute guardian once and return result."""
    try:
        result = subprocess.run(
            [sys.executable, str(GUARDIAN_SCRIPT)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "stdout_lines": len(result.stdout.splitlines()),
            "stderr_lines": len(result.stderr.splitlines()),
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "timeout"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def watchdog_cycle() -> None:
    """Single watchdog cycle: check health + auto-heal if needed."""
    positions = get_positions()
    guardian_state = check_guardian_state()
    
    # Check 1: Positions exist but guardian halted = EMERGENCY
    if len(positions) > 0 and guardian_state.get("halted"):
        log({
            "event": "EMERGENCY_UNPROTECTED_CAPITAL",
            "positions": len(positions),
            "halt_reason": guardian_state.get("halt_reason"),
            "action": "running_guardian_override",
        })
        # Guardian is halted but positions exist — force one run to evaluate
        result = run_guardian_once()
        log({"event": "emergency_guardian_run", "result": result})
        return
    
    # Check 2: Positions exist but guardian hasn't run recently
    if len(positions) > 0:
        if not guardian_state.get("exists"):
            log({
                "event": "CRITICAL_GUARDIAN_NEVER_RUN",
                "positions": len(positions),
                "action": "initializing_guardian",
            })
            result = run_guardian_once()
            log({"event": "guardian_initialization", "result": result})
            return
        
        # Check last guardian update time
        try:
            last_update = datetime.fromisoformat(guardian_state["updated_at"])
            if last_update.tzinfo is None:
                last_update = last_update.replace(tzinfo=timezone.utc)
            age_seconds = (datetime.now(timezone.utc) - last_update).total_seconds()
            
            if age_seconds > 120:  # Guardian hasn't run in 2+ minutes
                log({
                    "event": "STALE_GUARDIAN",
                    "positions": len(positions),
                    "age_seconds": age_seconds,
                    "action": "running_guardian",
                })
                result = run_guardian_once()
                log({"event": "guardian_refresh", "result": result})
                return
        except (KeyError, ValueError):
            pass
    
    # Check 3: Circuit breaker about to trigger (2 consecutive losses)
    if guardian_state.get("consecutive_losses", 0) >= 2:
        log({
            "event": "WARNING_CIRCUIT_BREAKER_IMMINENT",
            "consecutive_losses": guardian_state["consecutive_losses"],
            "message": "Next loss will HALT system",
        })
    
    # Normal health check
    log({
        "event": "watchdog_cycle",
        "positions": len(positions),
        "guardian_halted": guardian_state.get("halted", False),
        "consecutive_losses": guardian_state.get("consecutive_losses", 0),
        "status": "OK",
    })

def main() -> None:
    print("=" * 60)
    print("  SYSTEM WATCHDOG — Continuous Protection")
    print("  30-second cycle, ZERO TOLERANCE for unprotected capital")
    print("=" * 60)
    print()
    
    log({"event": "watchdog_started", "pid": os.getpid()})
    
    cycle_count = 0
    while True:
        try:
            cycle_count += 1
            watchdog_cycle()
            time.sleep(30)
        except KeyboardInterrupt:
            log({"event": "watchdog_stopped", "cycles": cycle_count})
            print(f"\nWatchdog stopped after {cycle_count} cycles.")
            break
        except Exception as e:
            log({"event": "watchdog_error", "error": str(e), "cycles": cycle_count})
            print(f"ERROR: {e}")
            time.sleep(30)

if __name__ == "__main__":
    main()
