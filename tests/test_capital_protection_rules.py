#!/usr/bin/env python3
"""
CAPITAL PROTECTION RULES TEST

Tests that non-bypassable rules are enforced:
1. No protection → no trading (entry blocked if heartbeat stale)
2. Force-exit always dominates (SL bypasses circuit breaker)
3. No false claims (status verifies live state)

Run: pytest tests/test_capital_protection_rules.py
"""

import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

# Add parent to path
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

def test_entry_blocked_if_protection_stale():
    """RULE 1: Entry execution must be blocked if protection loop is stale."""
    from scripts.trading_engine import TradingEngine
    
    # Mock client and state
    with patch('scripts.trading_engine.HyperliquidClient'):
        engine = TradingEngine(dry_run=True)
        
        # Simulate stale protection (last reconcile >2 min ago)
        engine.last_reconcile = time.time() - 150  # 2.5 min ago
        
        signal = {
            "asset": "ETH",
            "position_size_usd": 10,
            "tier": 1,
        }
        
        # Attempt entry
        engine.execute_entry(signal)
        
        # Verify no position added
        assert "ETH" not in engine.state.data["open_positions"], \
            "FAIL: Entry executed despite stale protection"
    
    print("✅ PASS: Entry blocked when protection stale")

def test_sl_force_mode_bypasses_circuit_breaker():
    """RULE 2: SL force-exit must bypass circuit breaker."""
    from scripts.trading_engine import execute_exit, EngineState, HyperliquidClient
    
    # Create mock position
    pos = {
        "coin": "ETH",
        "roe": -0.08,  # Below SL
        "unrealized_pnl": -1.0,
        "entry_price": 2000,
    }
    
    triggers = ["STOP_LOSS: ROE -8.0% <= -7%"]
    
    # Mock client
    client = Mock(spec=HyperliquidClient)
    client.market_close = Mock(return_value={"status": "ok", "response": {"type": "order", "data": {"statuses": [{"filled": {"totalSz": "1", "avgPx": "1980"}}]}}})
    client.get_mid = Mock(return_value=1980.0)
    
    # Mock state with circuit breaker HALTED
    state = EngineState()
    state.data["circuit_breaker_halted"] = True
    state.data["halt_reason"] = "3 consecutive losses"
    
    # Execute with force=True
    result = execute_exit(client, pos, triggers, state, force=True, dry_run=False)
    
    # Verify exit executed despite circuit breaker
    assert result["result"] == "EXECUTED", \
        f"FAIL: Force-mode SL blocked by circuit breaker. Result: {result}"
    
    print("✅ PASS: Force-mode SL bypasses circuit breaker")

def test_status_verifies_protection_active():
    """RULE 3: Status check must verify protection is active before claiming operational."""
    from scripts.trading_engine import STATE_FILE, EngineState
    
    # Create state with stale heartbeat
    state = EngineState()
    state.data["heartbeat"] = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    state.save()
    
    # Run status check (captures stdout)
    import io
    import contextlib
    
    f = io.StringIO()
    with contextlib.redirect_stdout(f):
        from scripts.trading_engine import status_check
        status_check()
    
    output = f.getvalue()
    
    # Verify it says protection is OFFLINE (not ACTIVE)
    assert "OFFLINE" in output or "STALE" in output, \
        "FAIL: Status claimed protection active with stale heartbeat"
    
    print("✅ PASS: Status verifies protection before claiming operational")

def test_entry_blocked_if_unhealthy():
    """RULE 1: Entry must be blocked if system is unhealthy (circuit breaker)."""
    from scripts.trading_engine import TradingEngine
    
    with patch('scripts.trading_engine.HyperliquidClient'):
        engine = TradingEngine(dry_run=True)
        
        # Trigger circuit breaker
        engine.state.data["circuit_breaker_halted"] = True
        engine.state.data["halt_reason"] = "3 consecutive losses"
        
        # Fresh protection (should not block on this)
        engine.last_reconcile = time.time()
        
        signal = {
            "asset": "ETH",
            "position_size_usd": 10,
            "tier": 1,
        }
        
        # Attempt entry
        engine.execute_entry(signal)
        
        # Verify no position added
        assert "ETH" not in engine.state.data["open_positions"], \
            "FAIL: Entry executed despite circuit breaker halt"
    
    print("✅ PASS: Entry blocked when system unhealthy")

if __name__ == "__main__":
    print("=" * 70)
    print("  CAPITAL PROTECTION RULES TEST")
    print("=" * 70)
    print()
    
    try:
        test_entry_blocked_if_protection_stale()
        test_sl_force_mode_bypasses_circuit_breaker()
        test_status_verifies_protection_active()
        test_entry_blocked_if_unhealthy()
        
        print()
        print("=" * 70)
        print("✅ ALL TESTS PASSED — Capital protection rules enforced")
        print("=" * 70)
        sys.exit(0)
    
    except AssertionError as e:
        print()
        print("=" * 70)
        print(f"❌ TEST FAILED: {e}")
        print("=" * 70)
        sys.exit(1)
    
    except Exception as e:
        print()
        print("=" * 70)
        print(f"❌ ERROR: {e}")
        print("=" * 70)
        sys.exit(1)
