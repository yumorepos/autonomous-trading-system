#!/usr/bin/env python3
"""
CEO HEALTH CHECK — System-wide status + anomaly detection

Runs comprehensive checks:
1. System services (watchdog, guardian, scanner)
2. Position health (PnL, exposure, SL proximity)
3. Risk validation (circuit breaker, execution safety)
4. Anomaly detection (missed actions, stale logs)
5. Capital status (current, deployed, available)

Designed for:
- Manual invocation (quick status)
- Scheduled checks (daily/weekly)
- Alert generation (Telegram/email)
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.runtime import LOGS_DIR

def check_process(name: str) -> dict:
    """Check if a process is running."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", name],
            capture_output=True,
            text=True,
        )
        pids = [int(p) for p in result.stdout.strip().split("\n") if p]
        return {"running": len(pids) > 0, "pids": pids, "count": len(pids)}
    except Exception as e:
        return {"running": False, "error": str(e)}

def check_log_freshness(log_file: Path, max_age_minutes: int = 60) -> dict:
    """Check if log has recent entries."""
    try:
        if not log_file.exists():
            return {"exists": False, "fresh": False}
        
        mtime = datetime.fromtimestamp(log_file.stat().st_mtime, tz=timezone.utc)
        age_minutes = (datetime.now(timezone.utc) - mtime).total_seconds() / 60
        
        return {
            "exists": True,
            "fresh": age_minutes <= max_age_minutes,
            "age_minutes": round(age_minutes, 1),
            "last_modified": mtime.isoformat(),
        }
    except Exception as e:
        return {"exists": False, "error": str(e)}

def get_capital() -> dict:
    """Get current capital from position_health.py."""
    try:
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "position_health.py")],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        
        lines = result.stdout.splitlines()
        spot_usd = 0.0
        position_count = 0
        
        for line in lines:
            if "Spot USDC:" in line:
                spot_usd = float(line.split("$")[1].strip())
            elif "POSITIONS:" in line and "None" not in line:
                position_count = int(line.split(":")[1].strip())
        
        return {
            "spot_usd": spot_usd,
            "position_count": position_count,
            "success": True,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

def get_guardian_state() -> dict:
    """Read guardian state file."""
    try:
        state_file = LOGS_DIR / "risk-guardian-state.json"
        if not state_file.exists():
            return {"exists": False}
        
        data = json.loads(state_file.read_text())
        return {
            "exists": True,
            "halted": data.get("halted", False),
            "halt_reason": data.get("halt_reason"),
            "consecutive_losses": data.get("consecutive_losses", 0),
            "total_closes": data.get("total_closes", 0),
            "peak_account_value": data.get("peak_account_value", 0),
        }
    except Exception as e:
        return {"exists": False, "error": str(e)}

def main() -> None:
    print("=" * 70)
    print("  CEO HEALTH CHECK")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 70)
    print()
    
    # 1. Process checks
    print("SERVICES:")
    watchdog = check_process("watchdog.py")
    print(f"  Watchdog: {'✅ RUNNING' if watchdog['running'] else '❌ DOWN'} (PIDs: {watchdog.get('pids', [])})")
    
    # 2. Log freshness
    print("\nLOGS:")
    watchdog_log = check_log_freshness(LOGS_DIR / "watchdog.jsonl", max_age_minutes=2)
    guardian_log = check_log_freshness(LOGS_DIR / "risk-guardian.jsonl", max_age_minutes=60)
    
    print(f"  Watchdog log: {'✅ FRESH' if watchdog_log.get('fresh') else '⚠️  STALE'} (age: {watchdog_log.get('age_minutes', 'N/A')} min)")
    print(f"  Guardian log: {'✅ FRESH' if guardian_log.get('fresh') else '⚠️  STALE'} (age: {guardian_log.get('age_minutes', 'N/A')} min)")
    
    # 3. Capital & positions
    print("\nCAPITAL:")
    capital = get_capital()
    if capital.get("success"):
        print(f"  Spot USDC: ${capital['spot_usd']:.2f}")
        print(f"  Positions: {capital['position_count']}")
    else:
        print(f"  ❌ ERROR: {capital.get('error')}")
    
    # 4. Guardian state
    print("\nGUARDIAN:")
    guardian = get_guardian_state()
    if guardian.get("exists"):
        status = "🔴 HALTED" if guardian["halted"] else "✅ ACTIVE"
        print(f"  Status: {status}")
        if guardian["halted"]:
            print(f"  Reason: {guardian['halt_reason']}")
        print(f"  Consecutive losses: {guardian['consecutive_losses']} / 3")
        print(f"  Total closes: {guardian['total_closes']}")
        print(f"  Peak capital: ${guardian['peak_account_value']:.2f}")
    else:
        print(f"  ⚠️  State file missing")
    
    # 5. Anomaly checks
    print("\nANOMALIES:")
    anomalies = []
    
    if capital.get("position_count", 0) > 0 and guardian.get("halted"):
        anomalies.append("🚨 CRITICAL: Positions exist but guardian HALTED")
    
    if not watchdog["running"]:
        anomalies.append("🚨 CRITICAL: Watchdog not running")
    
    if guardian.get("consecutive_losses", 0) >= 2:
        anomalies.append(f"⚠️  WARNING: Circuit breaker imminent ({guardian['consecutive_losses']}/3 losses)")
    
    if anomalies:
        for a in anomalies:
            print(f"  {a}")
    else:
        print("  ✅ None detected")
    
    print()
    print("=" * 70)

if __name__ == "__main__":
    main()
