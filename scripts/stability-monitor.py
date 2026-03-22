#!/usr/bin/env python3
"""
24-Hour Stability Monitor
Support-only observability script for paper-trading operations.
Tracks: crashes, cron health, API failures, canonical state corruption, anomalies.
"""

import json
import sys
import time
import psutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.runtime import (
    WORKSPACE_ROOT as WORKSPACE,
    LOGS_DIR,
    DATA_DIR,
    TRADING_MODE,
    mode_includes_hyperliquid,
    mode_includes_polymarket,
)
STABILITY_LOG = LOGS_DIR / "stability-monitor.jsonl"
STABILITY_STATE = LOGS_DIR / "stability-state.json"
STABILITY_REPORT = WORKSPACE / "STABILITY_REPORT.md"

class StabilityMonitor:
    """Monitor system stability over 24 hours"""
    
    def __init__(self):
        self.start_time = datetime.now(timezone.utc)
        self.state = self.load_state()
        self.events = []
        
    def load_state(self) -> Dict:
        """Load previous state"""
        if STABILITY_STATE.exists():
            with open(STABILITY_STATE) as f:
                return json.load(f)
        
        return {
            'start_time': datetime.now(timezone.utc).isoformat(),
            'total_checks': 0,
            'errors': 0,
            'warnings': 0,
            'api_failures': 0,
            'cron_misses': 0,
            'crashes': 0,
            'memory_leaks': 0,
            'last_cron_times': {},
            'uptime_seconds': 0
        }
    
    def save_state(self):
        """Save current state"""
        with open(STABILITY_STATE, 'w') as f:
            json.dump(self.state, f, indent=2)
    
    def log_event(self, level: str, component: str, message: str, data: Dict = None):
        """Log stability event"""
        event = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'level': level,
            'component': component,
            'message': message,
            'data': data or {}
        }
        
        self.events.append(event)
        
        # Append to log file
        with open(STABILITY_LOG, 'a') as f:
            f.write(json.dumps(event) + '\n')
        
        # Update counters
        if level == 'ERROR':
            self.state['errors'] += 1
        elif level == 'WARNING':
            self.state['warnings'] += 1
    
    def check_cron_health(self):
        """Check if cron jobs are running on schedule"""
        try:
            # Get cron schedule
            result = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
            cron_lines = [line for line in result.stdout.split('\n') 
                         if 'python3' in line and not line.strip().startswith('#')]
            
            # Expected scripts
            expected_scripts = [
                'data-integrity-layer.py',
                'trading-agency-phase1.py',
                'supervisor-governance.py',
                'alpha-intelligence-layer.py',
                'execution-safety-layer.py',
                'portfolio-allocator.py',
                'live-readiness-validator.py'
            ]
            
            # Check each script has log output
            now = datetime.now(timezone.utc)
            
            for script in expected_scripts:
                log_file = LOGS_DIR / f"{script.replace('.py', '')}.log"
                
                if not log_file.exists():
                    self.log_event('WARNING', 'cron', f'Log file missing: {log_file.name}')
                    continue
                
                # Check last modification time
                mtime = datetime.fromtimestamp(log_file.stat().st_mtime, tz=timezone.utc)
                age_hours = (now - mtime).total_seconds() / 3600
                
                # Most jobs run every 4 hours
                max_age = 5 if script != 'live-readiness-validator.py' else 25
                
                if age_hours > max_age:
                    self.log_event('ERROR', 'cron', f'Cron job stale: {script}', {
                        'last_run_hours_ago': age_hours,
                        'max_age_hours': max_age
                    })
                    self.state['cron_misses'] += 1
                else:
                    self.log_event('INFO', 'cron', f'Cron job healthy: {script}', {
                        'last_run_hours_ago': age_hours
                    })
            
        except Exception as e:
            self.log_event('ERROR', 'cron', f'Cron health check failed: {e}')
    
    def check_api_health(self):
        """Check API connectivity"""
        import requests
        
        apis = {}
        if mode_includes_hyperliquid(TRADING_MODE):
            apis['Hyperliquid'] = 'https://api.hyperliquid.xyz/info'
        if mode_includes_polymarket(TRADING_MODE):
            apis['Polymarket'] = 'https://gamma-api.polymarket.com/markets'
        
        for name, url in apis.items():
            try:
                start = time.time()
                
                if name == 'Hyperliquid':
                    r = requests.post(url, json={'type': 'allMids'}, timeout=5)
                else:
                    r = requests.get(url, timeout=5)
                
                latency = (time.time() - start) * 1000
                
                if r.status_code == 200:
                    self.log_event('INFO', 'api', f'{name} healthy', {
                        'latency_ms': latency,
                        'status': 200
                    })
                else:
                    self.log_event('WARNING', 'api', f'{name} returned {r.status_code}', {
                        'latency_ms': latency,
                        'status': r.status_code
                    })
                    self.state['api_failures'] += 1
                    
            except Exception as e:
                self.log_event('ERROR', 'api', f'{name} failed: {e}')
                self.state['api_failures'] += 1
    
    def check_state_corruption(self):
        """Check for corrupted state files"""
        state_files = [
            'data-integrity-state.json',
            'execution-safety-state.json',
            'alpha-intelligence-state.json',
            'portfolio-allocation.json',
            'strategy-registry.json',
        ]
        for file_name in state_files:
            file_path = LOGS_DIR / file_name
            
            if not file_path.exists():
                continue
            
            try:
                with open(file_path) as f:
                    json.load(f)
                self.log_event('INFO', 'state', f'{file_name} valid')
            except json.JSONDecodeError as e:
                self.log_event('ERROR', 'state', f'{file_name} corrupted: {e}')
                self.state['crashes'] += 1
    
    def check_memory_usage(self):
        """Check for memory leaks"""
        try:
            mem = psutil.virtual_memory()
            
            # Get Python processes
            python_procs = [p for p in psutil.process_iter(['name', 'memory_info']) 
                           if 'python' in p.info['name'].lower()]
            
            total_python_mem_mb = sum(p.info['memory_info'].rss for p in python_procs) / 1024 / 1024
            
            self.log_event('INFO', 'memory', 'Memory usage check', {
                'system_used_pct': mem.percent,
                'python_total_mb': total_python_mem_mb
            })
            
            # Alert if Python using > 500 MB
            if total_python_mem_mb > 500:
                self.log_event('WARNING', 'memory', 'High Python memory usage', {
                    'python_total_mb': total_python_mem_mb
                })
                self.state['memory_leaks'] += 1
                
        except Exception as e:
            self.log_event('ERROR', 'memory', f'Memory check failed: {e}')
    
    def check_disk_usage(self):
        """Check disk usage"""
        try:
            disk = psutil.disk_usage(str(WORKSPACE))
            
            self.log_event('INFO', 'disk', 'Disk usage check', {
                'used_pct': disk.percent,
                'free_gb': disk.free / 1024 / 1024 / 1024
            })
            
            if disk.percent > 90:
                self.log_event('ERROR', 'disk', 'Disk nearly full', {
                    'used_pct': disk.percent
                })
                
        except Exception as e:
            self.log_event('ERROR', 'disk', f'Disk check failed: {e}')
    
    def run_check(self):
        """Run complete stability check"""
        print(f"=== Stability Check {self.state['total_checks'] + 1} ===")
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        self.state['total_checks'] += 1
        
        self.check_cron_health()
        self.check_api_health()
        self.check_state_corruption()
        self.check_memory_usage()
        self.check_disk_usage()
        
        self.save_state()
        self.generate_report()
        
        print(f"Errors: {self.state['errors']}")
        print(f"Warnings: {self.state['warnings']}")
        print(f"API Failures: {self.state['api_failures']}")
        print(f"Cron Misses: {self.state['cron_misses']}")
        print()
    
    def generate_report(self):
        """Generate stability report"""
        elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(self.state['start_time'])).total_seconds()
        elapsed_hours = elapsed / 3600
        
        # Calculate uptime %
        total_possible_checks = self.state['total_checks']
        failed_checks = self.state['errors'] + self.state['crashes']
        uptime_pct = ((total_possible_checks - failed_checks) / max(total_possible_checks, 1)) * 100
        
        report = f"""# 24-Hour Stability Report
**Started:** {self.state['start_time']}
**Elapsed:** {elapsed_hours:.1f} hours
**Status:** {"[OK] STABLE" if self.state['errors'] < 5 else "[WARN] UNSTABLE" if self.state['errors'] < 10 else "[FAIL] CRITICAL"}
**Trading Mode Scope:** {TRADING_MODE}

---

## Summary

**Uptime:** {uptime_pct:.1f}%
**Total Checks:** {self.state['total_checks']}
**Errors:** {self.state['errors']}
**Warnings:** {self.state['warnings']}

---

## Component Health

| Component | Failures | Status |
|-----------|----------|--------|
| API | {self.state['api_failures']} | {"[OK]" if self.state['api_failures'] < 5 else "[WARN]" if self.state['api_failures'] < 10 else "[FAIL]"} |
| Cron | {self.state['cron_misses']} | {"[OK]" if self.state['cron_misses'] == 0 else "[WARN]" if self.state['cron_misses'] < 3 else "[FAIL]"} |
| State | {self.state['crashes']} | {"[OK]" if self.state['crashes'] == 0 else "[FAIL]"} |
| Memory | {self.state['memory_leaks']} | {"[OK]" if self.state['memory_leaks'] == 0 else "[WARN]"} |

---

## Recent Events (Last 10)

"""
        
        # Add recent events
        recent = self.events[-10:] if len(self.events) > 10 else self.events
        
        for event in recent:
            timestamp = datetime.fromisoformat(event['timestamp']).strftime('%H:%M:%S')
            report += f"- **{event['level']}** [{timestamp}] {event['component']}: {event['message']}\n"
        
        report += f"""
---

## Next Check

Every 15 minutes. Target: 96 checks over 24 hours.

**Progress:** {self.state['total_checks']}/96 ({(self.state['total_checks']/96)*100:.1f}%)

---

*Stability monitoring reflects the currently selected paper-trading mode. Polymarket checks are included only when the selected mode enables them.*
"""
        
        with open(STABILITY_REPORT, 'w') as f:
            f.write(report)


def main():
    """Run stability check"""
    monitor = StabilityMonitor()
    monitor.run_check()
    
    print(f"[OK] Stability check complete")
    print(f"[STATS] Report: {STABILITY_REPORT}")
    print(f"[NOTE] Log: {STABILITY_LOG}")


if __name__ == "__main__":
    main()
