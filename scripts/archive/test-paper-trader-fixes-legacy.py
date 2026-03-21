#!/usr/bin/env python3
"""
ARCHIVED LEGACY TEST -- targeted the archived alternate trader, not the canonical implementation.

Test Suite for Paper Trader Fixes
Verifies: SHORT PnL, position IDs, multi-strategy, performance persistence
"""

import json
import sys
from pathlib import Path

# Test the fixed version
sys.path.insert(0, str(Path(__file__).parent))


def test_pnl_calculation():
    """Test LONG and SHORT P&L calculations"""
    print("TEST 1: P&L Calculation")
    print("-" * 60)
    
    # Import the fixed calculate_pnl function
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "trader", 
        Path(__file__).parent / "phase1-paper-trader-FIXED.py"
    )
    trader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(trader)
    
    # Test LONG position
    entry = 100.0
    current = 110.0
    size = 1.0
    
    pnl_usd, pnl_pct = trader.calculate_pnl(entry, current, size, 'LONG')
    
    assert pnl_usd == 10.0, f"LONG P&L USD wrong: {pnl_usd} != 10.0"
    assert pnl_pct == 10.0, f"LONG P&L % wrong: {pnl_pct} != 10.0"
    print("  [OK] LONG P&L: +$10.00 (+10.0%) - CORRECT")
    
    # Test SHORT position with profit
    pnl_usd, pnl_pct = trader.calculate_pnl(entry, current, size, 'SHORT')
    
    assert pnl_usd == -10.0, f"SHORT P&L USD wrong: {pnl_usd} != -10.0"
    assert pnl_pct == -10.0, f"SHORT P&L % wrong: {pnl_pct} != -10.0"
    print("  [OK] SHORT P&L: -$10.00 (-10.0%) - CORRECT (price went up, short loses)")
    
    # Test SHORT position with loss (price goes down)
    current = 90.0
    pnl_usd, pnl_pct = trader.calculate_pnl(entry, current, size, 'SHORT')
    
    assert pnl_usd == 10.0, f"SHORT profit USD wrong: {pnl_usd} != 10.0"
    assert pnl_pct == 10.0, f"SHORT profit % wrong: {pnl_pct} != 10.0"
    print("  [OK] SHORT P&L: +$10.00 (+10.0%) - CORRECT (price went down, short wins)")
    
    print("  [OK] ALL P&L TESTS PASSED")
    print()
    return True


def test_position_id_generation():
    """Test position ID prevents ghosts"""
    print("TEST 2: Position ID Generation")
    print("-" * 60)
    
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "trader", 
        Path(__file__).parent / "phase1-paper-trader-FIXED.py"
    )
    trader_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(trader_module)
    
    # Create test signal
    test_signal = {
        'signal_type': 'funding_arbitrage',
        'asset': 'TEST',
        'direction': 'LONG',
        'entry_price': 100.0,
        'ev_score': 50
    }
    
    # Create two traders
    trader1 = trader_module.PaperTrader(test_signal)
    trader2 = trader_module.PaperTrader(test_signal)
    
    # Check IDs are unique
    assert trader1.position_id != trader2.position_id, "Position IDs should be unique"
    assert len(trader1.position_id) == 8, f"Position ID wrong length: {len(trader1.position_id)}"
    
    print(f"  [OK] Position ID 1: {trader1.position_id}")
    print(f"  [OK] Position ID 2: {trader2.position_id}")
    print("  [OK] IDs are unique (prevents ghosts)")
    print()
    return True


def test_multi_strategy_support():
    """Test both strategy types are supported"""
    print("TEST 3: Multi-Strategy Support")
    print("-" * 60)
    
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "trader", 
        Path(__file__).parent / "phase1-paper-trader-FIXED.py"
    )
    trader_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(trader_module)
    
    # Test funding_arbitrage
    signal1 = {
        'signal_type': 'funding_arbitrage',
        'asset': 'ETH',
        'direction': 'LONG',
        'entry_price': 2000.0,
        'ev_score': 50
    }
    
    trader1 = trader_module.PaperTrader(signal1)
    trade1 = trader1.execute()
    
    assert trade1 is not None, "Funding arbitrage should execute"
    assert trade1['strategy'] == 'funding_arbitrage'
    print("  [OK] funding_arbitrage: Supported")
    
    # Test spread_arbitrage (Polymarket)
    signal2 = {
        'signal_type': 'spread_arbitrage',
        'market': 'TEST_MARKET',
        'spread_pct': 5.0,
        'ev_score': 50
    }
    
    trader2 = trader_module.PaperTrader(signal2)
    trade2 = trader2.execute()
    
    # Note: Returns None because scanner doesn't provide required fields yet
    assert trade2 is None, "Polymarket execution should return None (scanner incomplete)"
    print("  [WARN]  spread_arbitrage: Recognized but disabled (scanner needs fix)")
    print("      Missing: market_id, side fields")
    
    print()
    return True


def test_performance_persistence():
    """Test performance JSON is actually written"""
    print("TEST 4: Performance File Writing")
    print("-" * 60)
    
    import tempfile
    import importlib.util
    
    # Create temp workspace
    temp_dir = Path(tempfile.mkdtemp())
    
    spec = importlib.util.spec_from_file_location(
        "trader", 
        Path(__file__).parent / "phase1-paper-trader-FIXED.py"
    )
    trader_module = importlib.util.module_from_spec(spec)
    
    # Override paths for test
    trader_module.WORKSPACE = temp_dir
    trader_module.PAPER_TRADES_FILE = temp_dir / "trades.jsonl"
    trader_module.PERFORMANCE_FILE = temp_dir / "performance.json"
    
    spec.loader.exec_module(trader_module)
    
    # Create fake closed trade
    fake_trade = {
        'status': 'CLOSED',
        'realized_pnl_usd': 10.50,
        'signal': {'asset': 'TEST'}
    }
    
    trader_module.PAPER_TRADES_FILE.parent.mkdir(exist_ok=True)
    with open(trader_module.PAPER_TRADES_FILE, 'w') as f:
        f.write(json.dumps(fake_trade) + '\n')
    
    # Calculate performance
    perf = trader_module.calculate_performance()
    
    # Check file exists
    assert trader_module.PERFORMANCE_FILE.exists(), "Performance file not created"
    
    # Check file content
    with open(trader_module.PERFORMANCE_FILE) as f:
        saved_perf = json.load(f)
    
    assert saved_perf['total_trades'] == 1, "Wrong trade count in file"
    assert saved_perf['total_pnl_usd'] == 10.50, "Wrong P&L in file"
    
    print(f"  [OK] Performance file created: {trader_module.PERFORMANCE_FILE.name}")
    print(f"  [OK] Content verified: {saved_perf}")
    
    # Cleanup
    import shutil
    shutil.rmtree(temp_dir)
    
    print()
    return True


def test_position_state_management():
    """Test position state file prevents ghosts"""
    print("TEST 5: Position State Management")
    print("-" * 60)
    
    import tempfile
    import importlib.util
    
    temp_dir = Path(tempfile.mkdtemp())
    
    spec = importlib.util.spec_from_file_location(
        "trader", 
        Path(__file__).parent / "phase1-paper-trader-FIXED.py"
    )
    trader_module = importlib.util.module_from_spec(spec)
    
    trader_module.WORKSPACE = temp_dir
    trader_module.PAPER_TRADES_FILE = temp_dir / "trades.jsonl"
    trader_module.POSITION_STATE_FILE = temp_dir / "state.json"
    
    spec.loader.exec_module(trader_module)
    
    # Create position with ID
    position = {
        'position_id': 'test123',
        'status': 'OPEN',
        'signal': {'asset': 'TEST'}
    }
    
    # Log as OPEN
    trader_module.log_trade(position)
    
    # Verify state file created
    state = trader_module.load_position_state()
    assert state['test123'] == 'OPEN', "State not saved"
    print("  [OK] Position opened, state saved")
    
    # Close position
    closed_position = {**position, 'status': 'CLOSED'}
    trader_module.log_trade(closed_position)
    
    # Verify state updated
    state = trader_module.load_position_state()
    assert state['test123'] == 'CLOSED', "State not updated"
    print("  [OK] Position closed, state updated")
    
    # Load open positions (should be empty)
    open_positions = trader_module.load_open_positions()
    assert len(open_positions) == 0, f"Ghost position! Found {len(open_positions)} open"
    print("  [OK] No ghost positions after reload")
    
    # Cleanup
    import shutil
    shutil.rmtree(temp_dir)
    
    print()
    return True


def main():
    """Run all tests"""
    print("=" * 80)
    print("PAPER TRADER FIX VERIFICATION")
    print("=" * 80)
    print()
    
    tests = [
        test_pnl_calculation,
        test_position_id_generation,
        test_multi_strategy_support,
        test_performance_persistence,
        test_position_state_management
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
        except Exception as e:
            print(f"  [FAIL] FAILED: {e}")
            print()
            failed += 1
    
    print("=" * 80)
    print(f"RESULTS: {passed}/{len(tests)} tests passed")
    
    if failed > 0:
        print(f"[WARN]  {failed} test(s) failed")
        sys.exit(1)
    else:
        print("[OK] ALL TESTS PASSED")
        sys.exit(0)


if __name__ == "__main__":
    main()
