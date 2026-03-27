#!/usr/bin/env python3
"""
EXIT OWNERSHIP MANAGER

Ensures only one actor (engine or fallback) owns a risk exit at a time.

Prevents:
- Duplicate close attempts from concurrent actors
- Unknown-success double-execution
- Partial fill confusion
- State/ledger drift during messy exits

Usage:
    from scripts.exit_ownership import claim_exit, release_exit, get_exit_state
"""

from __future__ import annotations

import json
import fcntl
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Use REPO_ROOT if available, otherwise construct path
try:
    from config.runtime import LOGS_DIR
    EXIT_OWNERSHIP_FILE = LOGS_DIR / "exit_ownership.json"
except ImportError:
    # Fallback for standalone testing
    EXIT_OWNERSHIP_FILE = Path(__file__).parent.parent / "workspace" / "logs" / "exit_ownership.json"

def _read_ownership() -> dict:
    """Read ownership file with file lock."""
    EXIT_OWNERSHIP_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    if not EXIT_OWNERSHIP_FILE.exists():
        EXIT_OWNERSHIP_FILE.write_text(json.dumps({"exits": {}}, indent=2))
    
    with open(EXIT_OWNERSHIP_FILE, 'r+') as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            data = json.load(f)
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    
    return data

def _write_ownership(data: dict) -> None:
    """Write ownership file with file lock."""
    with open(EXIT_OWNERSHIP_FILE, 'w') as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            json.dump(data, f, indent=2)
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

def claim_exit(symbol: str, trade_id: str, owner: str, original_size: str, reason: str) -> bool:
    """
    Claim ownership of an exit.
    
    Returns True if claim succeeded, False if another actor already owns it.
    """
    data = _read_ownership()
    
    exit_key = f"{symbol}-{trade_id}"
    
    # Check if already owned
    if exit_key in data["exits"]:
        existing = data["exits"][exit_key]
        
        # Allow same owner to re-claim (idempotent)
        if existing["owner"] == owner:
            return True
        
        # Check if existing ownership is stale (>5 min)
        start_time = datetime.fromisoformat(existing["start_time"])
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        
        age_sec = (datetime.now(timezone.utc) - start_time).total_seconds()
        
        if age_sec < 300:  # 5 minutes
            # Another actor owns this exit
            return False
        # Else: stale ownership, take over
    
    # Claim ownership
    data["exits"][exit_key] = {
        "symbol": symbol,
        "trade_id": trade_id,
        "owner": owner,
        "state": "retrying",
        "start_time": datetime.now(timezone.utc).isoformat(),
        "attempts": [],
        "original_size": original_size,
        "remaining_size": original_size,
        "reason": reason,
    }
    
    _write_ownership(data)
    return True

def record_attempt(symbol: str, trade_id: str, result: str, response: dict, remaining_size: Optional[str] = None) -> None:
    """Record an exit attempt."""
    data = _read_ownership()
    
    exit_key = f"{symbol}-{trade_id}"
    
    if exit_key not in data["exits"]:
        return  # Exit not owned
    
    attempt = {
        "time": datetime.now(timezone.utc).isoformat(),
        "result": result,  # "ok", "error", "unknown", "partial"
        "response": response,
    }
    
    data["exits"][exit_key]["attempts"].append(attempt)
    
    if remaining_size is not None:
        data["exits"][exit_key]["remaining_size"] = remaining_size
    
    if result == "ok":
        data["exits"][exit_key]["state"] = "completed"
    
    _write_ownership(data)

def release_exit(symbol: str, trade_id: str) -> None:
    """Release ownership of an exit."""
    data = _read_ownership()
    
    exit_key = f"{symbol}-{trade_id}"
    
    if exit_key in data["exits"]:
        del data["exits"][exit_key]
        _write_ownership(data)

def get_exit_state(symbol: str, trade_id: str) -> Optional[dict]:
    """Get current state of an exit."""
    data = _read_ownership()
    
    exit_key = f"{symbol}-{trade_id}"
    
    return data["exits"].get(exit_key)

def list_active_exits() -> dict:
    """List all active exits."""
    data = _read_ownership()
    return data["exits"]
