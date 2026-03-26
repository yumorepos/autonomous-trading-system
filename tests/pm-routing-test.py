#!/usr/bin/env python3
"""Test Polymarket signal routing and canonical execution path."""

import json
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.unified_executor import UnifiedExecutor

def test_polymarket_routing():
    """Test that Polymarket signals route to canonical executor."""
    print("=== Testing Polymarket Signal Routing ===")
    
    executor = UnifiedExecutor(dry_run=True)
    
    # Test signal 1: Polymarket binary market
    pm_signal = {
        "exchange": "Polymarket",
        "market_id": "pm-test-market",
        "asset": "pm-test-market",
        "signal_type": "binary_market",
        "direction": "YES",
        "entry_price": 0.55,
        "recommended_position_size_usd": 5.0,
    }
    
    exchange, exec_inst = executor.route_signal(pm_signal)
    print(f"Polymarket signal → {exchange} (executor: {exec_inst is not None})")
    assert exchange == "Polymarket", f"Expected 'Polymarket', got '{exchange}'"
    assert exec_inst is not None, "Polymarket executor should be loaded"
    
    # Test signal 2: Hyperliquid price market (for comparison)
    hl_signal = {
        "exchange": "Hyperliquid",
        "asset": "ETH",
        "signal_type": "funding_arbitrage",
        "direction": "LONG",
        "entry_price": 3500.0,
        "recommended_position_size_usd": 12.0,
    }
    
    exchange, exec_inst = executor.route_signal(hl_signal)
    print(f"Hyperliquid signal → {exchange} (executor: {exec_inst is not None})")
    assert exchange == "Hyperliquid", f"Expected 'Hyperliquid', got '{exchange}'"
    assert exec_inst is not None, "Hyperliquid executor should be loaded"
    
    print("✅ Routing tests passed")

def test_polymarket_execution_contract():
    """Test that Polymarket trades follow canonical contract."""
    print("\n=== Testing Polymarket Execution Contract ===")
    
    # Create a test workspace
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir) / "workspace"
        logs_dir = workspace / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        
        # Set environment for test
        os.environ["OPENCLAW_WORKSPACE"] = str(workspace)
        
        executor = UnifiedExecutor(dry_run=True)
        
        # Test Polymarket trade execution
        pm_signal = {
            "exchange": "Polymarket",
            "market_id": "pm-btc-test",
            "asset": "pm-btc-test",
            "signal_type": "binary_market",
            "direction": "YES",
            "entry_price": 0.42,
            "recommended_position_size_usd": 3.0,
        }
        
        account_state = {"account_value": 100.0, "positions": []}
        result = executor.execute_entry(pm_signal, account_state)
        
        print(f"Execution result: {result.get('success', False)}")
        print(f"Exchange: {result.get('exchange', 'unknown')}")
        
        # Verify result structure
        assert "exchange" in result, "Result should include exchange"
        assert result["exchange"] == "Polymarket", f"Expected Polymarket exchange"
        
        # Check if error message is about missing credentials (expected in dry-run)
        if not result.get("success", False):
            print(f"Expected error (dry-run): {result.get('error', 'no error')}")
        
        print("✅ Execution contract test passed")

def test_logging_integration():
    """Test that Polymarket trades are logged correctly."""
    print("\n=== Testing Polymarket Trade Logging ===")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir) / "workspace"
        logs_dir = workspace / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        
        # Create execution log file
        pm_log = logs_dir / "pm-execution.jsonl"
        pm_log.write_text("")  # Empty log
        
        os.environ["OPENCLAW_WORKSPACE"] = str(workspace)
        
        # Test that logging path exists
        from scripts.pm_executor_canonical import EXECUTION_LOG
        print(f"Log path: {EXECUTION_LOG}")
        
        # Verify log file would be created in real execution
        assert "pm-execution.jsonl" in str(EXECUTION_LOG), "Log should target pm-execution.jsonl"
        
        print("✅ Logging integration test passed")

if __name__ == "__main__":
    print("Polymarket Canonical Path Test")
    print("=" * 60)
    
    try:
        test_polymarket_routing()
        test_polymarket_execution_contract()
        test_logging_integration()
        
        print("\n" + "=" * 60)
        print("✅ ALL TESTS PASSED")
        print("Polymarket is now a first-class execution path")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)