#!/usr/bin/env python3
"""
CHECK MISSION — Auto-load and resume monitoring

Called on startup to check for active missions and resume monitoring.

Usage:
    python3 scripts/check_mission.py
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MISSION_FILE = REPO_ROOT / "CURRENT_MISSION.json"

def load_mission():
    """Load current mission if exists (with validation)."""
    # Run validator first
    import subprocess
    validator_script = REPO_ROOT / "scripts" / "mission_validator.py"
    
    result = subprocess.run(
        [sys.executable, str(validator_script)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT
    )
    
    if result.returncode == 1:
        # Validation failed, attempt recovery
        print("⚠️  Mission validation failed, attempting recovery...")
        recover_result = subprocess.run(
            [sys.executable, str(validator_script), "--recover"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT
        )
        if recover_result.returncode != 0:
            print("❌ Auto-recovery failed")
            return None
        print("✅ Mission recovered")
    
    if not MISSION_FILE.exists():
        return None
    
    try:
        with open(MISSION_FILE) as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️  Failed to load mission: {e}")
        return None

def check_mission():
    """Check mission status and report."""
    mission = load_mission()
    
    if not mission:
        print("No active mission")
        return
    
    # Check for degraded mode
    if mission.get("mode") == "degraded":
        print("=" * 70)
        print("  ⚠️  DEGRADED MODE")
        print("=" * 70)
        print()
        print(f"Reason: {mission.get('degraded_reason', 'Unknown')}")
        print()
        print("Actions:")
        for action in mission.get("next_session_actions", []):
            print(f"  - {action}")
        print()
        return
    
    if mission.get("status") != "active":
        print(f"Mission status: {mission.get('status')}")
        return
    
    # Mission active, report status
    progress = mission.get("progress", {})
    audited = progress.get("trades_audited", 0)
    required = progress.get("trades_required", 10)
    
    print("=" * 70)
    print("  ACTIVE MISSION")
    print("=" * 70)
    print()
    print(f"Objective: {mission.get('objective')}")
    print(f"Progress: {audited}/{required} trades audited")
    print(f"Last check: {progress.get('last_check')}")
    print()
    print("Next actions:")
    for action in mission.get("next_session_actions", []):
        print(f"  - {action}")
    print()
    
    if audited >= required:
        print("✅ MISSION COMPLETE")
        print(f"Report: {mission['completion_criteria']['report_file']}")
    else:
        print(f"⏳ MONITORING ({required - audited} trades remaining)")

if __name__ == "__main__":
    check_mission()
