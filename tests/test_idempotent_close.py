#!/usr/bin/env python3
"""
IDEMPOTENT CLOSE + PARTIAL FILL TESTS

Tests the final distributed-systems hardening:
1. Exit ownership prevents concurrent actors
2. Re-query detects unknown success
3. Partial fills handled until flat
4. Ledger/state stay canonical

Run: python3 tests/test_idempotent_close.py
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.runtime import LOGS_DIR
from scripts.exit_ownership import claim_exit, release_exit, get_exit_state

def test_ownership_prevents_concurrent_close():
    """Only one actor can own an exit at a time."""
    
    # Engine claims ownership
    success_engine = claim_exit("ETH", "hl-eth-2026-03-27", "engine", "0.01", "STOP_LOSS")
    assert success_engine, "Engine should claim ownership first"
    
    # Fallback tries to claim (should fail)
    success_fallback = claim_exit("ETH", "hl-eth-2026-03-27", "fallback", "0.01", "EMERGENCY")
    assert not success_fallback, "Fallback should NOT claim when engine owns"
    
    # Release and re-claim
    release_exit("ETH", "hl-eth-2026-03-27")
    
    success_fallback_2 = claim_exit("ETH", "hl-eth-2026-03-27", "fallback", "0.01", "EMERGENCY")
    assert success_fallback_2, "Fallback should claim after engine releases"
    
    # Cleanup
    release_exit("ETH", "hl-eth-2026-03-27")
    
    print("✅ PASS: Ownership prevents concurrent close")

def test_requery_detects_unknown_success():
    """Re-query before retry detects if first attempt actually succeeded."""
    from scripts.idempotent_exit import execute_exit_idempotent
    from scripts.trading_engine import EngineState, HyperliquidClient
    
    # Mock client that:
    # 1. Returns error on first close attempt
    # 2. Returns no position on re-query (close actually succeeded)
    client = Mock(spec=HyperliquidClient)
    
    call_count = [0]
    
    def mock_get_positions():
        call_count[0] += 1
        if call_count[0] == 1:
            # First query: position exists
            return [{"coin": "BTC", "szi": "0.001", "roe": -0.08, "unrealized_pnl": -5}]
        else:
            # Second query: position flat (unknown success)
            return []
    
    client.get_positions = mock_get_positions
    client.market_close = Mock(return_value={"status": "error", "response": "timeout"})
    client.get_mid = Mock(return_value=50000.0)
    client.get_state = Mock(return_value={"account_value": 100})
    
    pos = {
        "coin": "BTC",
        "szi": "0.001",
        "roe": -0.08,
        "unrealized_pnl": -5.0,
        "entry_price": 50000,
    }
    
    state = EngineState()
    state.data["open_positions"]["BTC"] = {"entry_time": datetime.now(timezone.utc).isoformat(), "entry_price": 50000}
    
    result = execute_exit_idempotent(client, pos, ["STOP_LOSS"], state, force=True, dry_run=False)
    
    # Should detect unknown success via re-query
    assert result["result"] == "EXECUTED", f"Should detect unknown success: {result}"
    assert result.get("already_flat") == True, "Should mark as already_flat"
    
    print("✅ PASS: Re-query detects unknown success")

def test_partial_fill_loop():
    """Exit loops until position is flat (handles partial fills)."""
    from scripts.idempotent_exit import execute_exit_idempotent
    from scripts.trading_engine import EngineState, HyperliquidClient
    
    # Mock client with partial fill behavior:
    # 1. First query: 0.01 size
    # 2. First close: success
    # 3. Second query: 0.005 remaining (partial fill)
    # 4. Second close: success
    # 5. Third query: 0 (flat)
    
    client = Mock(spec=HyperliquidClient)
    
    query_count = [0]
    
    def mock_get_positions():
        query_count[0] += 1
        if query_count[0] <= 2:
            return [{"coin": "SOL", "szi": "0.01", "roe": -0.09}]
        elif query_count[0] <= 4:
            return [{"coin": "SOL", "szi": "0.005", "roe": -0.09}]  # Partial fill after first close
        else:
            return []  # Flat after second close
    
    client.get_positions = mock_get_positions
    client.market_close = Mock(return_value={"status": "ok", "response": {"type": "order"}})
    client.get_mid = Mock(return_value=100.0)
    client.get_state = Mock(return_value={"account_value": 100})
    
    pos = {
        "coin": "SOL",
        "szi": "0.01",
        "roe": -0.09,
        "unrealized_pnl": -2.0,
        "entry_price": 100,
    }
    
    state = EngineState()
    state.data["open_positions"]["SOL"] = {"entry_time": datetime.now(timezone.utc).isoformat(), "entry_price": 100}
    
    result = execute_exit_idempotent(client, pos, ["STOP_LOSS"], state, force=True, dry_run=False)
    
    # Should loop and close all
    assert result["result"] == "EXECUTED", f"Should handle partial fill: {result}"
    assert client.market_close.call_count >= 2, f"Should retry for partial fill (called {client.market_close.call_count}x)"
    
    print("✅ PASS: Partial fill loop handles until flat")

def test_ownership_released_after_success():
    """Ownership is released after successful close."""
    from scripts.idempotent_exit import execute_exit_idempotent
    from scripts.trading_engine import EngineState, HyperliquidClient
    
    client = Mock(spec=HyperliquidClient)
    client.get_positions = Mock(return_value=[])  # Already flat
    client.get_mid = Mock(return_value=3000.0)
    client.get_state = Mock(return_value={"account_value": 100})
    
    pos = {
        "coin": "AVAX",
        "szi": "1.0",
        "roe": -0.08,
        "unrealized_pnl": -1.0,
        "entry_price": 50,
    }
    
    state = EngineState()
    state.data["open_positions"]["AVAX"] = {"entry_time": "2026-03-27T12:00:00+00:00", "entry_price": 50}
    
    result = execute_exit_idempotent(client, pos, ["STOP_LOSS"], state, force=True, dry_run=False)
    
    # Should release ownership
    exit_state = get_exit_state("AVAX", "hl-avax-2026-03-27")
    assert exit_state is None, "Ownership should be released after success"
    
    print("✅ PASS: Ownership released after success")

if __name__ == "__main__":
    print("=" * 70)
    print("  IDEMPOTENT CLOSE + PARTIAL FILL TESTS")
    print("=" * 70)
    print()
    
    try:
        test_ownership_prevents_concurrent_close()
        test_requery_detects_unknown_success()
        test_partial_fill_loop()
        test_ownership_released_after_success()
        
        print()
        print("=" * 70)
        print("✅ ALL IDEMPOTENT CLOSE TESTS PASSED")
        print("=" * 70)
        print("Messy-exit races eliminated — capital protection remains canonical")
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
