#!/usr/bin/env python3
"""Test Polymarket executor integration."""

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.pm_executor import PolymarketExecutor

def test_executor_initialization():
    """Test executor loads correctly."""
    print("=== Testing Polymarket Executor Initialization ===")
    
    executor = PolymarketExecutor(dry_run=True)
    
    print(f"Live mode: {executor.live_mode}")
    print(f"Signature type: {executor.signature_type}")
    print(f"Dry run: {executor.dry_run}")
    
    # Verify environment variable references
    assert executor.private_key == "" or executor.private_key == os.environ.get("PM_PRIVATE_KEY", "")
    assert executor.funder_address == "" or executor.funder_address == os.environ.get("PM_FUNDER_ADDRESS", "")
    
    print("✅ Executor initialization test passed")

def test_executor_logging():
    """Test execution logging."""
    print("\n=== Testing Polymarket Execution Logging ===")
    
    executor = PolymarketExecutor(dry_run=True)
    
    # Test execution
    result = executor.execute_order(
        token_id="test-token-123",
        side="YES",
        size=5.0,
        price=0.55
    )
    
    print(f"Execution result: {result.get('success', False)}")
    print(f"Dry run: {result.get('dry_run', False)}")
    
    # Verify result structure
    assert "success" in result
    assert "token_id" in result
    assert "side" in result
    
    print("✅ Execution logging test passed")

def test_security():
    """Test that no secrets are exposed."""
    print("\n=== Testing Security ===")
    
    # Check executor file for hardcoded secrets
    with open("scripts/pm_executor.py", "r") as f:
        content = f.read()
    
    # Should NOT have hardcoded private keys
    assert "0xf1e9" not in content
    assert "0x7D806806f810Db1187228744970c0f5cb1F803c1" not in content
    
    # Should reference environment variables
    assert "PM_PRIVATE_KEY" in content
    assert "PM_FUNDER_ADDRESS" in content
    assert "os.environ.get" in content
    
    print("✅ Security test passed")

if __name__ == "__main__":
    print("Polymarket Executor Security Integration Test")
    print("=" * 60)
    
    try:
        test_executor_initialization()
        test_executor_logging()
        test_security()
        
        print("\n" + "=" * 60)
        print("✅ ALL TESTS PASSED")
        print("Polymarket executor verified and secure")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)