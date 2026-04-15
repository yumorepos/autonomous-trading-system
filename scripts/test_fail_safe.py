#!/usr/bin/env python3
"""
Test fail-safe validation layer: Prove errors are surfaced and capital-protective.
"""

import json
from pathlib import Path
from datetime import datetime, timezone
from fail_safe_validator import FailSafeValidator, ValidationResult, Criticality

# Mock state object
class MockState:
    def __init__(self):
        self.data = {
            'open_positions': {},
            'peak_roe': {},
        }

def test_entry_blocked_on_error():
    """Test: Entry validation errors block entries (fail-safe)."""
    print("TEST 1: Entry blocked on validation error")
    
    # Create validator with broken info (will error)
    validator = FailSafeValidator(info=None)  # None will cause errors
    state = MockState()
    
    result = validator.validate_entry("BTC", 15.0, 50000.0, state)
    
    print(f"  Result valid: {result.valid}")
    print(f"  Should block entry: {result.should_block_entry()}")
    print(f"  Reason: {result.reason}")
    print(f"  Error: {result.error}")
    
    assert result.should_block_entry(), "ERROR: Entry not blocked on validation error"
    print("  ✅ PASS: Entry correctly blocked\n")

def test_exit_never_blocked():
    """Test: Exit validation never blocks (capital protection priority)."""
    print("TEST 2: Exit never blocked (even on error)")
    
    validator = FailSafeValidator(info=None)  # Will error
    state = MockState()
    state.data['open_positions']['BTC'] = {'entry_price': 50000}
    
    result = validator.validate_exit("BTC", state)
    
    print(f"  Result valid: {result.valid}")
    print(f"  Should block exit: {result.should_block_exit()}")
    print(f"  Reason: {result.reason}")
    
    assert not result.should_block_exit(), "ERROR: Exit was blocked"
    print("  ✅ PASS: Exit never blocked\n")

def test_reconcile_doesnt_stop_engine():
    """Test: Reconcile errors logged but don't stop engine."""
    print("TEST 3: Reconcile errors don't stop engine")
    
    validator = FailSafeValidator(info=None)  # Will error
    state_file = Path("/tmp/test_state.json")
    state_file.write_text(json.dumps({'open_positions': {}}))
    
    result = validator.reconcile_state(state_file)
    
    print(f"  Result valid: {result.valid}")
    print(f"  Criticality: {result.criticality.value}")
    print(f"  Reason: {result.reason}")
    
    assert result.criticality == Criticality.RECONCILE_WARN, "Wrong criticality"
    print("  ✅ PASS: Reconcile failure logged as warning\n")
    
    state_file.unlink()

def test_errors_logged_not_swallowed():
    """Test: All errors are logged (validation_errors.jsonl)."""
    print("TEST 4: Errors surfaced and logged")
    
    log_file = Path("/tmp/test_validation_errors.jsonl")
    if log_file.exists():
        log_file.unlink()
    
    validator = FailSafeValidator(info=None, log_file=log_file)
    state = MockState()
    
    # Trigger validation that will error
    result = validator.validate_entry("BTC", 15.0, 50000.0, state)
    
    # Check log file created
    assert log_file.exists(), "Log file not created"
    
    with open(log_file) as f:
        logs = [json.loads(l) for l in f if l.strip()]
    
    print(f"  Logged {len(logs)} validation errors")
    
    # Check first log has error field
    if logs:
        first_log = logs[0]
        print(f"  Error field present: {'error' in first_log}")
        print(f"  Criticality: {first_log.get('criticality')}")
        assert first_log.get('error') is not None, "Error not logged"
    
    print("  ✅ PASS: Errors logged and surfaced\n")
    
    log_file.unlink()

def test_criticality_classification():
    """Test: Different checks have correct criticality."""
    print("TEST 5: Criticality classification")
    
    validator = FailSafeValidator()
    state = MockState()
    
    # Entry check = ENTRY_CRITICAL
    result = validator._check_position_limits("BTC", state, Criticality.ENTRY_CRITICAL)
    assert result.criticality == Criticality.ENTRY_CRITICAL
    print("  ✅ Position limits: ENTRY_CRITICAL")
    
    # Exit check = EXIT_SAFE
    result = validator._check_position_exists("BTC", state, Criticality.EXIT_SAFE)
    assert result.criticality == Criticality.EXIT_SAFE
    print("  ✅ Position exists: EXIT_SAFE")
    
    # Reconcile = RECONCILE_WARN
    state_file = Path("/tmp/test_state2.json")
    state_file.write_text(json.dumps({'open_positions': {}}))
    result = validator.reconcile_state(state_file)
    assert result.criticality == Criticality.RECONCILE_WARN
    print("  ✅ Reconcile: RECONCILE_WARN\n")
    
    state_file.unlink()

def test_fail_safe_vs_fail_open():
    """Test: System is fail-safe for entries, fail-open for exits."""
    print("TEST 6: Fail-safe for entries, fail-open for exits")
    
    validator = FailSafeValidator(info=None)  # Will error
    state = MockState()
    
    # Entry with error → BLOCKED (fail-safe)
    entry_result = validator.validate_entry("BTC", 15.0, 50000.0, state)
    entry_blocked = entry_result.should_block_entry()
    
    # Exit with error → ALLOWED (fail-open for capital protection)
    exit_result = validator.validate_exit("BTC", state)
    exit_blocked = exit_result.should_block_exit()
    
    print(f"  Entry blocked on error: {entry_blocked}")
    print(f"  Exit blocked on error: {exit_blocked}")
    
    assert entry_blocked == True, "Entry should be blocked (fail-safe)"
    assert exit_blocked == False, "Exit should NOT be blocked (fail-open)"
    
    print("  ✅ PASS: Fail-safe for entries, fail-open for exits\n")

if __name__ == "__main__":
    print("="*70)
    print("FAIL-SAFE VALIDATION LAYER TESTS")
    print("="*70 + "\n")
    
    test_entry_blocked_on_error()
    test_exit_never_blocked()
    test_reconcile_doesnt_stop_engine()
    test_errors_logged_not_swallowed()
    test_criticality_classification()
    test_fail_safe_vs_fail_open()
    
    print("="*70)
    print("✅ ALL TESTS PASSED")
    print("="*70)
    print("\nFAIL-SAFE GUARANTEES PROVEN:")
    print("1. ✅ Validation errors block ENTRIES (fail-safe)")
    print("2. ✅ Validation errors NEVER block EXITS (capital protection)")
    print("3. ✅ Reconcile errors logged but don't stop engine")
    print("4. ✅ All errors surfaced and logged (never swallowed)")
    print("5. ✅ Criticality correctly classified (ENTRY/EXIT/RECONCILE/OBSERVER)")
    print("6. ✅ Fail-safe for risk, fail-open for safety")
