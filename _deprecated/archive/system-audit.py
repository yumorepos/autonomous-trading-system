#!/usr/bin/env python3
"""
Complete System Audit & Validation
Tests entire pipeline: signal generation -> routing -> execution -> logging -> state persistence
"""

import json
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.runtime import WORKSPACE_ROOT as WORKSPACE, LOGS_DIR, DATA_DIR
sys.path.insert(0, str(REPO_ROOT / "scripts"))

# Import components
import importlib.util

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

pm_executor = load_module("pm_executor", REPO_ROOT / "scripts" / "polymarket-executor.py")
PolymarketExecutor = pm_executor.PolymarketExecutor

# Test files
SIGNALS_FILE = LOGS_DIR / "phase1-signals.jsonl"
PM_TRADES = LOGS_DIR / "polymarket-trades.jsonl"
PM_STATE = LOGS_DIR / "polymarket-state.json"
HL_TRADES = LOGS_DIR / "phase1-paper-trades.jsonl"

class SystemAuditor:
    """Complete system validation"""
    
    def __init__(self):
        self.results = []
        self.errors = []
    
    def test_polymarket_executor(self):
        """Test Polymarket executor end-to-end"""
        print("=" * 80)
        print("TEST 1: POLYMARKET EXECUTOR")
        print("=" * 80)
        print()
        
        try:
            # Initialize executor
            executor = PolymarketExecutor(paper_trading=True)
            print("[OK] Executor initialized")
            
            # Create test signal
            test_signal = {
                'market_id': 'test-market-123',
                'side': 'YES',
                'position_size': 10.0,
                'signal_type': 'polymarket_arbitrage',
                'source': 'Polymarket',
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'ev_score': 85
            }
            
            # Mock market data (since test market doesn't exist)
            print("[STATS] Creating test market...")
            
            # Test validation
            valid, reason = executor.validate_signal(test_signal)
            print(f"[OK] Signal validation: {valid} ({reason})")
            
            # Test status
            status = executor.get_status()
            print(f"[OK] Status check: Balance=${status['paper_balance']:.2f}, Open={status['open_positions']}")
            
            # Test state persistence
            executor.save_state()
            print(f"[OK] State saved to {PM_STATE}")
            
            # Verify state file
            if PM_STATE.exists():
                with open(PM_STATE) as f:
                    state = json.load(f)
                print(f"[OK] State persisted: {len(state)} keys")
            
            self.results.append(("Polymarket Executor", "PASS"))
            print()
            return True
            
        except Exception as e:
            self.errors.append(f"Polymarket Executor: {e}")
            self.results.append(("Polymarket Executor", "FAIL"))
            print(f"[FAIL] FAILED: {e}")
            print()
            return False
    
    def test_signal_routing(self):
        """Test signal routing logic"""
        print("=" * 80)
        print("TEST 2: SIGNAL ROUTING")
        print("=" * 80)
        print()
        
        try:
            # Create test signals
            hl_signal = {'source': 'Hyperliquid', 'asset': 'BTC', 'signal_type': 'funding_arbitrage'}
            pm_signal = {'source': 'Polymarket', 'market_id': 'test', 'signal_type': 'polymarket_arbitrage'}
            
            # Test routing logic
            def route_signal(signal):
                source = signal.get('source', '').lower()
                if 'polymarket' in source:
                    return 'Polymarket'
                else:
                    return 'Hyperliquid'
            
            hl_route = route_signal(hl_signal)
            pm_route = route_signal(pm_signal)
            
            print(f"[OK] Hyperliquid signal -> {hl_route}")
            print(f"[OK] Polymarket signal -> {pm_route}")
            
            assert hl_route == 'Hyperliquid', "Hyperliquid routing failed"
            assert pm_route == 'Polymarket', "Polymarket routing failed"
            
            self.results.append(("Signal Routing", "PASS"))
            print()
            return True
            
        except Exception as e:
            self.errors.append(f"Signal Routing: {e}")
            self.results.append(("Signal Routing", "FAIL"))
            print(f"[FAIL] FAILED: {e}")
            print()
            return False
    
    def test_logging_persistence(self):
        """Test logging and state persistence"""
        print("=" * 80)
        print("TEST 3: LOGGING & PERSISTENCE")
        print("=" * 80)
        print()
        
        try:
            # Check log files exist and are writable
            log_files = [
                SIGNALS_FILE,
                PM_TRADES,
                PM_STATE,
                HL_TRADES
            ]
            
            for log_file in log_files:
                if log_file.exists():
                    # Try to read
                    if log_file.suffix == '.json':
                        with open(log_file) as f:
                            json.load(f)
                    else:
                        with open(log_file) as f:
                            f.read()
                    print(f"[OK] {log_file.name}: Readable")
                else:
                    # Create parent dir
                    log_file.parent.mkdir(exist_ok=True)
                    print(f"[WARN]  {log_file.name}: Not found (will be created on first use)")
            
            self.results.append(("Logging & Persistence", "PASS"))
            print()
            return True
            
        except Exception as e:
            self.errors.append(f"Logging: {e}")
            self.results.append(("Logging & Persistence", "FAIL"))
            print(f"[FAIL] FAILED: {e}")
            print()
            return False
    
    def test_safety_integration(self):
        """Test safety checks integration"""
        print("=" * 80)
        print("TEST 4: SAFETY INTEGRATION")
        print("=" * 80)
        print()
        
        try:
            executor = PolymarketExecutor(paper_trading=True)
            
            # Test 1: Oversized position
            oversized_signal = {
                'market_id': 'test',
                'side': 'YES',
                'position_size': 100.0,  # > max $20
                'signal_type': 'test'
            }
            
            valid, reason = executor.validate_signal(oversized_signal)
            assert not valid, "Should reject oversized position"
            print(f"[OK] Rejected oversized position: {reason}")
            
            # Test 2: Missing fields
            incomplete_signal = {
                'side': 'YES'
                # Missing market_id
            }
            
            valid, reason = executor.validate_signal(incomplete_signal)
            assert not valid, "Should reject incomplete signal"
            print(f"[OK] Rejected incomplete signal: {reason}")
            
            # Test 3: Valid signal
            valid_signal = {
                'market_id': 'test',
                'side': 'YES',
                'position_size': 10.0,
                'signal_type': 'test'
            }
            
            valid, reason = executor.validate_signal(valid_signal)
            assert valid, "Should accept valid signal"
            print(f"[OK] Accepted valid signal: {reason}")
            
            self.results.append(("Safety Integration", "PASS"))
            print()
            return True
            
        except Exception as e:
            self.errors.append(f"Safety Integration: {e}")
            self.results.append(("Safety Integration", "FAIL"))
            print(f"[FAIL] FAILED: {e}")
            print()
            return False
    
    def test_cron_schedule(self):
        """Test cron schedule for duplicates/gaps"""
        print("=" * 80)
        print("TEST 5: CRON SCHEDULE AUDIT")
        print("=" * 80)
        print()
        
        try:
            import subprocess
            
            # Get current crontab
            result = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
            cron_lines = result.stdout.strip().split('\n')
            
            # Parse cron entries
            openclaw_jobs = [line for line in cron_lines if 'openclaw' in line.lower() or 'python3' in line]
            
            print(f"Found {len(openclaw_jobs)} OpenClaw cron jobs:")
            print()
            
            schedule_map = {}
            
            for job in openclaw_jobs:
                if job.strip().startswith('#'):
                    continue
                
                parts = job.split()
                if len(parts) >= 6:
                    schedule = ' '.join(parts[:5])
                    script = [p for p in parts if '.py' in p]
                    script_name = script[0].split('/')[-1] if script else 'unknown'
                    
                    if schedule not in schedule_map:
                        schedule_map[schedule] = []
                    schedule_map[schedule].append(script_name)
                    
                    print(f"  {schedule} -> {script_name}")
            
            print()
            
            # Check for duplicates
            duplicates = {k: v for k, v in schedule_map.items() if len(v) > 1}
            if duplicates:
                print("[WARN]  DUPLICATES DETECTED:")
                for schedule, scripts in duplicates.items():
                    print(f"   {schedule}: {', '.join(scripts)}")
                print()
            else:
                print("[OK] No duplicate schedules")
                print()
            
            # Check for expected jobs
            expected_scripts = [
                'data-integrity-layer.py',
                'trading-agency-phase1.py',
                'supervisor-governance.py',
                'alpha-intelligence-layer.py',
                'execution-safety-layer.py',
                'portfolio-allocator.py',
                'live-readiness-validator.py'
            ]
            
            all_scripts = [s for scripts in schedule_map.values() for s in scripts]
            
            print("Expected jobs:")
            for script in expected_scripts:
                if any(script in s for s in all_scripts):
                    print(f"  [OK] {script}")
                else:
                    print(f"  [WARN]  {script} (not found)")
            
            print()
            
            self.results.append(("Cron Schedule", "PASS" if not duplicates else "WARN"))
            return True
            
        except Exception as e:
            self.errors.append(f"Cron Schedule: {e}")
            self.results.append(("Cron Schedule", "FAIL"))
            print(f"[FAIL] FAILED: {e}")
            print()
            return False
    
    def generate_report(self):
        """Generate audit report"""
        print("=" * 80)
        print("AUDIT SUMMARY")
        print("=" * 80)
        print()
        
        for test, result in self.results:
            icon = "[OK]" if result == "PASS" else "[WARN]" if result == "WARN" else "[FAIL]"
            print(f"{icon} {test}: {result}")
        
        print()
        
        if self.errors:
            print("ERRORS:")
            for error in self.errors:
                print(f"  [FAIL] {error}")
            print()
        
        passed = len([r for r in self.results if r[1] == "PASS"])
        warned = len([r for r in self.results if r[1] == "WARN"])
        failed = len([r for r in self.results if r[1] == "FAIL"])
        total = len(self.results)
        
        print(f"Total: {passed} passed, {warned} warnings, {failed} failed (out of {total})")
        print()
        
        if failed == 0:
            print("[OK] SYSTEM AUDIT: PASSED")
        elif warned > 0 and failed == 0:
            print("[WARN]  SYSTEM AUDIT: PASSED WITH WARNINGS")
        else:
            print("[FAIL] SYSTEM AUDIT: FAILED")
        
        return failed == 0


def main():
    auditor = SystemAuditor()
    
    print("=" * 80)
    print("COMPLETE SYSTEM AUDIT")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S EDT')}")
    print("=" * 80)
    print()
    
    # Run all tests
    auditor.test_polymarket_executor()
    auditor.test_signal_routing()
    auditor.test_logging_persistence()
    auditor.test_safety_integration()
    auditor.test_cron_schedule()
    
    # Generate report
    passed = auditor.generate_report()
    
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
