#!/usr/bin/env python3
"""
MISSION VALIDATOR — Fail-safe mission continuity

Validates CURRENT_MISSION.json integrity on every load.
Auto-recovers from corruption using backups + git/logs.
Cross-checks mission state vs live engine reality.
Enters safe degraded mode on inconsistency.

Usage:
    python3 scripts/mission_validator.py
    python3 scripts/mission_validator.py --recover
"""

import argparse
import json
import shutil
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MISSION_FILE = REPO_ROOT / "CURRENT_MISSION.json"
BACKUP_DIR = REPO_ROOT / "workspace" / "mission_backups"
LOG_FILE = REPO_ROOT / "workspace" / "logs" / "trading_engine.jsonl"
STATE_FILE = REPO_ROOT / "workspace" / "logs" / "trading_engine_state.json"

BACKUP_DIR.mkdir(parents=True, exist_ok=True)

# === VALIDATION RULES ===

REQUIRED_FIELDS = {
    "mission_id": str,
    "objective": str,
    "mode": str,
    "status": str,
    "progress": dict,
    "audit_requirements": dict,
    "monitoring_protocol": dict,
    "next_session_actions": list,
}

REQUIRED_PROGRESS_FIELDS = {
    "trades_audited": int,
    "trades_required": int,
    "last_check": str,
}

VALID_STATUSES = ["active", "paused", "completed", "degraded"]
VALID_MODES = ["continuous_monitoring", "degraded"]


def backup_mission():
    """Create timestamped backup of current mission file."""
    if not MISSION_FILE.exists():
        return None
    
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"mission_backup_{timestamp}.json"
    
    shutil.copy2(MISSION_FILE, backup_path)
    
    # Keep only last 10 backups
    backups = sorted(BACKUP_DIR.glob("mission_backup_*.json"))
    for old_backup in backups[:-10]:
        old_backup.unlink()
    
    return backup_path


def validate_mission_structure(mission_data):
    """Validate mission JSON structure."""
    errors = []
    
    # Check required top-level fields
    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in mission_data:
            errors.append(f"Missing required field: {field}")
        elif not isinstance(mission_data[field], expected_type):
            errors.append(f"Field '{field}' has wrong type (expected {expected_type.__name__})")
    
    # Check progress fields
    if "progress" in mission_data:
        for field, expected_type in REQUIRED_PROGRESS_FIELDS.items():
            if field not in mission_data["progress"]:
                errors.append(f"Missing progress field: {field}")
            elif not isinstance(mission_data["progress"][field], expected_type):
                errors.append(f"Progress field '{field}' has wrong type")
    
    # Check valid enums
    if "status" in mission_data and mission_data["status"] not in VALID_STATUSES:
        errors.append(f"Invalid status: {mission_data['status']}")
    
    if "mode" in mission_data and mission_data["mode"] not in VALID_MODES:
        errors.append(f"Invalid mode: {mission_data['mode']}")
    
    return errors


def cross_check_mission_vs_reality(mission_data):
    """Cross-check mission state against live engine/logs."""
    warnings = []
    
    # Check if engine is actually running
    try:
        result = subprocess.run(
            ["pgrep", "-f", "trading_engine.py"],
            capture_output=True,
            text=True
        )
        if not result.stdout.strip():
            warnings.append("Engine not running (mission expects monitoring)")
    except:
        pass
    
    # Check state file freshness
    if STATE_FILE.exists():
        try:
            state_data = json.loads(STATE_FILE.read_text())
            if "heartbeat" in state_data:
                hb_time = datetime.fromisoformat(state_data["heartbeat"].replace('Z', '+00:00'))
                age = (datetime.now(timezone.utc) - hb_time).total_seconds()
                if age > 300:  # 5 minutes
                    warnings.append(f"Engine heartbeat stale ({age:.0f}s old)")
        except:
            warnings.append("State file corrupted or unreadable")
    
    # Check for recent log activity
    if LOG_FILE.exists():
        try:
            lines = LOG_FILE.read_text().strip().split('\n')
            if lines:
                last_line = json.loads(lines[-1])
                last_time = datetime.fromisoformat(last_line["timestamp"].replace('Z', '+00:00'))
                age = (datetime.now(timezone.utc) - last_time).total_seconds()
                if age > 300:
                    warnings.append(f"No log activity for {age/60:.0f} min")
        except:
            pass
    
    # Check mission timestamp vs current time
    if "updated" in mission_data:
        try:
            updated = datetime.fromisoformat(mission_data["updated"].replace('Z', '+00:00'))
            age = (datetime.now(timezone.utc) - updated).total_seconds()
            if age > 86400:  # 24 hours
                warnings.append(f"Mission not updated for {age/3600:.0f} hours")
        except:
            pass
    
    return warnings


def find_latest_valid_backup():
    """Find most recent valid backup."""
    backups = sorted(BACKUP_DIR.glob("mission_backup_*.json"), reverse=True)
    
    for backup in backups:
        try:
            with open(backup) as f:
                data = json.load(f)
            
            errors = validate_mission_structure(data)
            if not errors:
                return backup, data
        except:
            continue
    
    return None, None


def recover_from_git():
    """Try to recover mission file from git history."""
    try:
        # Get last committed version
        result = subprocess.run(
            ["git", "show", "HEAD:CURRENT_MISSION.json"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            errors = validate_mission_structure(data)
            if not errors:
                return data
    except:
        pass
    
    return None


def create_degraded_mission():
    """Create safe degraded-mode mission."""
    return {
        "mission_id": f"degraded-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
        "objective": "Safe degraded mode - awaiting recovery",
        "mode": "degraded",
        "status": "degraded",
        "created": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        "updated": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        "progress": {
            "trades_audited": 0,
            "trades_required": 0,
            "last_check": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        },
        "audit_requirements": {},
        "monitoring_protocol": {},
        "next_session_actions": [
            "DEGRADED MODE: Mission file was corrupted",
            "Manual recovery required",
            "Check mission_backups/ for valid backup",
            "Or run: python3 scripts/mission_validator.py --recover"
        ],
        "degraded_reason": "Mission file validation failed, auto-recovery unsuccessful"
    }


def validate_and_load():
    """Validate mission file and load, with auto-recovery."""
    
    # Backup before validation
    backup_path = backup_mission()
    
    # Try to load mission file
    if not MISSION_FILE.exists():
        print("⚠️  Mission file not found")
        return None, ["Mission file does not exist"]
    
    try:
        with open(MISSION_FILE) as f:
            mission_data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"❌ Mission file corrupted: {e}")
        return None, [f"JSON decode error: {e}"]
    except Exception as e:
        print(f"❌ Failed to read mission file: {e}")
        return None, [f"Read error: {e}"]
    
    # Validate structure
    errors = validate_mission_structure(mission_data)
    if errors:
        print("❌ Mission validation failed:")
        for error in errors:
            print(f"  - {error}")
        return None, errors
    
    # Cross-check against reality
    warnings = cross_check_mission_vs_reality(mission_data)
    if warnings:
        print("⚠️  Mission/reality consistency warnings:")
        for warning in warnings:
            print(f"  - {warning}")
    
    # Check if already in degraded mode
    if mission_data.get("mode") == "degraded":
        print("⚠️  Mission is in DEGRADED MODE")
        return mission_data, warnings
    
    # All checks passed
    print("✅ Mission validation passed")
    return mission_data, warnings


def auto_recover():
    """Attempt automatic recovery from corruption."""
    print("=" * 70)
    print("  MISSION AUTO-RECOVERY")
    print("=" * 70)
    print()
    
    # Try backup first
    print("Checking backups...")
    backup_path, backup_data = find_latest_valid_backup()
    
    if backup_data:
        print(f"✅ Found valid backup: {backup_path.name}")
        print("Restoring from backup...")
        shutil.copy2(backup_path, MISSION_FILE)
        print("✅ Mission restored from backup")
        return True
    
    # Try git recovery
    print("Checking git history...")
    git_data = recover_from_git()
    
    if git_data:
        print("✅ Found valid version in git")
        print("Restoring from git...")
        with open(MISSION_FILE, 'w') as f:
            json.dump(git_data, f, indent=2)
        print("✅ Mission restored from git")
        return True
    
    # Create degraded mode
    print("⚠️  No valid backup or git version found")
    print("Entering DEGRADED MODE...")
    
    degraded = create_degraded_mission()
    with open(MISSION_FILE, 'w') as f:
        json.dump(degraded, f, indent=2)
    
    print("✅ Degraded mode mission created")
    print()
    print("Manual recovery required:")
    print("  1. Check workspace/mission_backups/ for valid backup")
    print("  2. Or restore from git: git checkout HEAD -- CURRENT_MISSION.json")
    print("  3. Or create new mission manually")
    
    return False


def main():
    parser = argparse.ArgumentParser(description="Validate and recover mission file")
    parser.add_argument("--recover", action="store_true", help="Attempt auto-recovery")
    args = parser.parse_args()
    
    if args.recover:
        auto_recover()
        return
    
    mission_data, issues = validate_and_load()
    
    if mission_data is None:
        print()
        print("❌ MISSION VALIDATION FAILED")
        print("Run with --recover to attempt auto-recovery")
        return 1
    
    if mission_data.get("mode") == "degraded":
        print()
        print("⚠️  DEGRADED MODE ACTIVE")
        print("Manual recovery required")
        return 2
    
    print()
    print("✅ Mission validated and safe to use")
    return 0


if __name__ == "__main__":
    exit(main())
