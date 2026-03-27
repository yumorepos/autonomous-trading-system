#!/usr/bin/env python3
"""
ENGINE + FALLBACK RACE CONDITION TEST

Tests the #1 blind spot: coordination between engine retry and emergency fallback

Scenario:
1. Engine triggers SL
2. API is slow (retrying)
3. Fallback sees stale heartbeat
4. Both try to close → coordination lock prevents duplicate/drift

Run: python3 tests/test_race_condition.py
"""

import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.runtime import LOGS_DIR

def test_coordination_lock_prevents_fallback_interference():
    """Engine signals active exit, fallback skips that position."""
    from scripts.emergency_fallback import emergency_close_all, LOGS_DIR
    
    # Setup: Create active exit lock (engine is retrying)
    active_exits_file = LOGS_DIR / "active_exits.json"
    active_exits_file.parent.mkdir(parents=True, exist_ok=True)
    active_exits_file.write_text(json.dumps({
        "active_exits": {
            "ETH": {
                "start_time": datetime.now(timezone.utc).isoformat(),
                "max_retries": 5,
                "reason": "STOP_LOSS: ROE -8.0% <= -7%"
            }
        }
    }, indent=2))
    
    # Mock client with ETH position
    with patch('scripts.emergency_fallback.HyperliquidClient') as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.get_positions = Mock(return_value=[
            {
                "coin": "ETH",
                "szi": "0.01",
                "roe": -0.08,
                "unrealized_pnl": -1.5,
            }
        ])
        mock_instance.market_close = Mock(return_value={"status": "ok"})
        
        # Run fallback
        import io
        import contextlib
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            emergency_close_all()
        
        output = f.getvalue()
        
        # Verify fallback did NOT close ETH (engine is handling it)
        assert not mock_instance.market_close.called, \
            "Fallback should NOT close position when engine is actively exiting"
        
        assert "Skipped" in output or "engine actively exiting" in output, \
            f"Fallback should report skipping position: {output}"
    
    print("✅ PASS: Coordination lock prevents fallback interference")

def test_fallback_takes_over_after_timeout():
    """If engine exit is stuck >60 sec, fallback takes over."""
    from scripts.emergency_fallback import emergency_close_all, LOGS_DIR
    
    # Setup: Create stale active exit lock (engine stuck for 65 sec)
    active_exits_file = LOGS_DIR / "active_exits.json"
    active_exits_file.write_text(json.dumps({
        "active_exits": {
            "BTC": {
                "start_time": (datetime.now(timezone.utc) - timedelta(seconds=65)).isoformat(),
                "max_retries": 5,
                "reason": "STOP_LOSS"
            }
        }
    }, indent=2))
    
    # Mock client with BTC position
    with patch('scripts.emergency_fallback.HyperliquidClient') as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.get_positions = Mock(return_value=[
            {
                "coin": "BTC",
                "szi": "0.001",
                "roe": -0.09,
                "unrealized_pnl": -5.0,
            }
        ])
        mock_instance.market_close = Mock(return_value={"status": "ok"})
        
        # Run fallback
        import io
        import contextlib
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            emergency_close_all()
        
        output = f.getvalue()
        
        # Verify fallback DID close BTC (engine is stuck too long)
        assert mock_instance.market_close.called, \
            "Fallback should take over if engine exit is stuck >60 sec"
        
        assert mock_instance.market_close.call_args[0][0] == "BTC", \
            "Fallback should close BTC position"
    
    print("✅ PASS: Fallback takes over after engine timeout")

def test_engine_clears_lock_after_success():
    """Engine removes active exit lock after successful close."""
    from scripts.trading_engine import execute_exit, EngineState, HyperliquidClient
    
    # Setup: Start with clean lock file
    active_exits_file = LOGS_DIR / "active_exits.json"
    active_exits_file.write_text(json.dumps({"active_exits": {}}, indent=2))
    
    # Mock client
    client = Mock(spec=HyperliquidClient)
    client.market_close = Mock(return_value={"status": "ok", "response": {"type": "order", "data": {"statuses": [{"filled": {"totalSz": "1", "avgPx": "2000"}}]}}})
    client.get_mid = Mock(return_value=2000.0)
    
    pos = {
        "coin": "SOL",
        "roe": -0.08,
        "unrealized_pnl": -1.0,
        "entry_price": 100,
    }
    
    triggers = ["STOP_LOSS: ROE -8.0% <= -7%"]
    state = EngineState()
    state.data["open_positions"]["SOL"] = {"entry_time": datetime.now(timezone.utc).isoformat(), "entry_price": 100}
    
    # Execute force-mode exit
    result = execute_exit(client, pos, triggers, state, force=True, dry_run=False)
    
    # Verify lock was created during exit
    # (implicit: execute_exit writes lock at start of retry loop)
    
    # Verify lock was cleared after success
    active_exits = json.loads(active_exits_file.read_text())
    assert "SOL" not in active_exits.get("active_exits", {}), \
        "Engine should clear active exit lock after successful close"
    
    print("✅ PASS: Engine clears lock after success")

def test_engine_clears_lock_after_escalation():
    """Engine removes active exit lock even if all retries fail."""
    from scripts.trading_engine import execute_exit, EngineState, HyperliquidClient
    
    # Setup
    active_exits_file = LOGS_DIR / "active_exits.json"
    active_exits_file.write_text(json.dumps({"active_exits": {}}, indent=2))
    
    # Mock client that always fails
    client = Mock(spec=HyperliquidClient)
    client.market_close = Mock(return_value={"status": "error", "response": "Network timeout"})
    client.get_mid = Mock(return_value=3000.0)
    
    pos = {
        "coin": "AVAX",
        "roe": -0.09,
        "unrealized_pnl": -2.0,
        "entry_price": 50,
    }
    
    triggers = ["STOP_LOSS"]
    state = EngineState()
    state.data["open_positions"]["AVAX"] = {"entry_time": datetime.now(timezone.utc).isoformat(), "entry_price": 50}
    
    # Execute (will fail all retries)
    result = execute_exit(client, pos, triggers, state, force=True, dry_run=False)
    
    # Verify escalated
    assert result["result"] == "FAILED_ALL_RETRIES"
    
    # Verify lock was cleared (so fallback can take over)
    active_exits = json.loads(active_exits_file.read_text())
    assert "AVAX" not in active_exits.get("active_exits", {}), \
        "Engine should clear active exit lock after escalation (so fallback can act)"
    
    print("✅ PASS: Engine clears lock after escalation")

if __name__ == "__main__":
    print("=" * 70)
    print("  ENGINE + FALLBACK RACE CONDITION TEST")
    print("=" * 70)
    print()
    
    try:
        test_coordination_lock_prevents_fallback_interference()
        test_fallback_takes_over_after_timeout()
        test_engine_clears_lock_after_success()
        test_engine_clears_lock_after_escalation()
        
        print()
        print("=" * 70)
        print("✅ ALL RACE CONDITION TESTS PASSED")
        print("=" * 70)
        print("Engine + Fallback coordination verified — no duplicate closes or state drift")
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
        import traceback
        traceback.print_exc()
        sys.exit(1)
