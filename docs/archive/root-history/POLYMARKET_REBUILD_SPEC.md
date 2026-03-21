# Polymarket Rebuild Specification

**Status:** DISABLED - awaiting complete rebuild  
**Target:** Match verified Hyperliquid architecture  
**Estimated effort:** 6-8 hours

---

## 1. Normalized Schema

### Scanner Output (phase1-signal-scanner.py)

**Required fields:**
```json
{
  "timestamp": "2026-03-21T08:00:00+00:00",
  "source": "Polymarket",
  "signal_type": "spread_arbitrage",
  "asset": "TRUMP-2024-WIN",           // NEW: Market identifier
  "direction": "LONG",                  // NEW: BUY or SELL
  "entry_price": 0.45,                  // NEW: Expected entry price
  "market_id": "0x1234...",            // NEW: Contract address
  "side": "YES",                        // NEW: YES or NO
  "bid": 0.44,
  "ask": 0.46,
  "spread_pct": 4.5,
  "ev_score": 45.0,
  "conviction": "HIGH"
}
```

**Changes required:**
1. Add `asset` field (market slug or title)
2. Add `direction` field (LONG=BUY YES, SHORT=BUY NO)
3. Add `entry_price` field (mid-price or best bid/ask)
4. Add `market_id` field (contract address from Gamma API)
5. Add `side` field (YES or NO)

---

## 2. Trader Execution (phase1-paper-trader.py)

### Entry Logic

**Current (BROKEN):**
```python
def execute_polymarket(self):
    return None  # Not implemented
```

**Required:**
```python
def execute_polymarket(self):
    """Execute Polymarket spread arbitrage"""
    signal = self.signal
    
    # Validate required fields
    required = ['market_id', 'side', 'entry_price', 'asset', 'direction']
    if not all(signal.get(f) for f in required):
        return None
    
    market_id = signal['market_id']
    side = signal['side']
    entry_price = signal['entry_price']
    
    # Calculate position size (same as Hyperliquid)
    position_size_usd = calculate_position_size()
    position_size = position_size_usd / entry_price
    
    # Generate position ID
    position_id = generate_position_id()
    
    # Create trade record
    trade = {
        'position_id': position_id,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'signal': signal,
        'exchange': 'Polymarket',
        'strategy': 'spread_arbitrage',
        'market_id': market_id,
        'side': side,
        'entry_price': entry_price,
        'position_size': position_size,
        'position_size_usd': position_size_usd,
        'direction': signal['direction'],
        'entry_time': datetime.now(timezone.utc).isoformat(),
        'status': 'OPEN',
        'stop_loss_pct': STOP_LOSS_PCT,
        'take_profit_pct': TAKE_PROFIT_PCT,
        'timeout_hours': TIMEOUT_HOURS
    }
    
    return trade
```

### Exit Logic

**Required additions to check_exit():**

```python
def check_exit(position: dict) -> tuple[bool, str]:
    """Check if position should exit"""
    # Existing validation...
    
    exchange = position.get('exchange')
    
    if exchange == 'Polymarket':
        # Get current market price
        market_id = position.get('market_id')
        side = position.get('side')
        current_price = get_polymarket_price(market_id, side)
    else:
        # Hyperliquid logic...
        current_price = get_current_price(asset)
    
    # Common exit logic (TP/SL/timeout)
    # Works for both exchanges...
```

**New function required:**
```python
def get_polymarket_price(market_id: str, side: str) -> float:
    """Get current Polymarket market price"""
    try:
        r = requests.get(
            f"https://clob.polymarket.com/book?token_id={market_id}",
            timeout=5
        )
        book = r.json()
        
        if side == 'YES':
            # Best bid for YES
            return float(book['bids'][0]['price']) if book['bids'] else 0
        else:
            # Best bid for NO
            return float(book['asks'][0]['price']) if book['asks'] else 0
    except:
        return 0
```

---

## 3. Authoritative State

**Current:** position-state.json works for both exchanges

**No changes required** - position_id system is exchange-agnostic

---

## 4. Validator Compatibility

**Current:** Validator already supports realized_pnl_usd schema

**Required verification:**
- Test validator with Polymarket closed trades
- Ensure exchange field doesn't break metrics
- Verify cost estimation for Polymarket (0.15% vs Hyperliquid)

---

## 5. Monitor Compatibility

**Exit Monitor:** Already reads from authoritative state - no changes needed

**Timeout Monitor:** Already reads from authoritative state - no changes needed

**Required verification:**
- Test monitors with mixed Hyperliquid + Polymarket positions
- Ensure price fetching works for both exchanges

---

## 6. Replay Prevention

**Current:** filter_unconsumed_signals() is exchange-agnostic

**No changes required** - signal timestamp deduplication works for all sources

---

## 7. Orchestrator Integration

**Current:** trading-agency-phase1.py already calls scanner

**Required verification:**
- Test orchestrator with Polymarket signals enabled
- Verify report generation includes both exchanges

---

## 8. Test Plan

### Phase 1: Scanner Tests

```python
# test-polymarket-scanner.py
def test_scanner_schema():
    """Verify scanner emits normalized schema"""
    signals = scan_polymarket_spreads()
    for sig in signals:
        assert 'asset' in sig
        assert 'direction' in sig
        assert 'entry_price' in sig
        assert 'market_id' in sig
        assert 'side' in sig
```

### Phase 2: Entry Tests

```python
# test-polymarket-entry.py
def test_polymarket_entry():
    """Verify Polymarket entry creates correct trade record"""
    # Inject Polymarket signal
    # Run trader
    # Verify trade log has OPEN record with market_id, side
    # Verify position-state.json updated
```

### Phase 3: Exit Tests

```python
# test-polymarket-tp-exit.py
def test_polymarket_take_profit():
    """Verify Polymarket TP exit works"""
    # Open position
    # Monkeypatch get_polymarket_price() to trigger TP
    # Run trader
    # Verify CLOSED record with exit_reason='take_profit'

# test-polymarket-sl-exit.py (same pattern)
# test-polymarket-timeout-exit.py (same pattern)
```

### Phase 4: Integration Tests

```python
# test-polymarket-integration.py
def test_full_lifecycle():
    """End-to-end Polymarket lifecycle"""
    # Scanner → signal → entry → exit → performance
    # Verify all components consistent

def test_mixed_exchanges():
    """Verify Hyperliquid + Polymarket coexist"""
    # Open 1 Hyperliquid, 1 Polymarket
    # Close both
    # Verify state/logs/validators handle both
```

### Phase 5: Orchestrator Tests

```python
# test-orchestrator-polymarket.py
def test_orchestrator_polymarket():
    """Verify orchestrator handles Polymarket"""
    # Run orchestrator cycle
    # Verify report includes Polymarket signals/trades
```

---

## 9. Acceptance Criteria

**Before re-enabling Polymarket:**

1. ✅ Scanner emits normalized schema (all required fields)
2. ✅ Trader executes Polymarket entries (OPEN records created)
3. ✅ Trader executes Polymarket exits (all 3 triggers: TP/SL/timeout)
4. ✅ State file manages Polymarket positions
5. ✅ Validator counts Polymarket trades correctly
6. ✅ Exit monitor tracks Polymarket positions
7. ✅ Timeout monitor tracks Polymarket positions
8. ✅ Replay prevention works for Polymarket signals
9. ✅ Orchestrator handles mixed exchange signals
10. ✅ All 10 integration tests passing

**Test coverage required:** 10 tests (5 unit, 5 integration)

**Evidence type:** VERIFIED IN PAPER-TRADING FLOW (real code paths)

---

## 10. Implementation Order

1. **Scanner normalization** (30 min)
   - Add asset, direction, entry_price, market_id, side fields
   - Test scanner output schema

2. **Trader entry logic** (45 min)
   - Implement execute_polymarket()
   - Test entry creates correct records

3. **Price fetching** (30 min)
   - Implement get_polymarket_price()
   - Test price API connectivity

4. **Exit integration** (45 min)
   - Add Polymarket branch to check_exit()
   - Test all 3 exit paths (TP/SL/timeout)

5. **Integration tests** (90 min)
   - Test full lifecycle
   - Test mixed exchanges
   - Test orchestrator

6. **Validation** (60 min)
   - Run all 10 tests
   - Verify validator/monitors
   - Document results

**Total: 6-7 hours**

---

## 11. Current Blocker

**Scanner schema incomplete:**
- Missing: asset, direction, entry_price, market_id, side
- Trader cannot execute without these fields
- System correctly rejects incomplete signals

**Status:** Polymarket disabled until scanner fixed

---

## 12. API References

- **Gamma API:** `https://gamma-api.polymarket.com/markets`
- **CLOB API:** `https://clob.polymarket.com/book?token_id={market_id}`
- **Data API:** `https://data-api.polymarket.com/trades`

---

*This spec defines the complete rebuild path. Do NOT re-enable Polymarket until all 10 tests pass.*
