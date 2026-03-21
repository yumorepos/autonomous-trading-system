# Canonical Path Audit
**Date:** 2026-03-21 03:10 EDT  
**Method:** Direct integration test on production code  
**Evidence Type:** INTEGRATION TESTED (FAILED)

---

## 1. EXECUTIVE SUMMARY

Attempted to verify the canonical execution path using controlled test signal injection.

**Result:** **INTEGRATION TEST FAILED**

**Root Cause:** Deployed trader crashes when loading positions from log due to missing required fields (`entry_price`, `position_size`). The log contains test data from unit tests that lacks these fields, causing the trader to fail on line 102:

```python
pt = PaperTrade(trade['signal'], trade['entry_price'], trade['position_size'])
# KeyError: 'entry_price'
```

**This proves:**
1. ✅ No input validation (logs accept malformed data)
2. ✅ No schema enforcement (position records incomplete)
3. ✅ Fragile state reconstruction (crashes on bad data)
4. ✅ Test contamination (unit test data pollutes production logs)

**Verdict:** **ARCHITECTURE INCONSISTENT** (system cannot even complete one integration test)

---

## 2. CANONICAL EXECUTION PATH

### Identified from Cron:

```
Orchestrator: trading-agency-phase1.py
  ↓ subprocess.run()
Scanner: phase1-signal-scanner.py
  ↓ writes JSONL
Signals Log: logs/phase1-signals.jsonl
  ↓ read by
Trader: phase1-paper-trader.py
  ↓ writes JSONL
Trades Log: logs/phase1-paper-trades.jsonl
  ↓ reconstructed by
Trader (on next run): load_open_positions()
```

**Cron Entry:**
```
0 */4 * * * cd ~/.openclaw/workspace && python3 scripts/trading-agency-phase1.py
```

**Evidence Type:** STATIC CODE REVIEW + CRON VERIFICATION

**Status:** ✅ Path identified, ❌ Path not functional

---

## 3. AUTHORITATIVE STATE SOURCES

### Question: What is the authoritative source of truth?

**Answer:** `logs/phase1-paper-trades.jsonl` (append-only)

### How State is Reconstructed:

**Method:** Filter for `status == 'OPEN'`

**Code:**
```python
# phase1-paper-trader.py line 95-105
open_positions = []
with open(PAPER_TRADES_FILE) as f:
    for line in f:
        if line.strip():
            trade = json.loads(line)
            if trade['status'] == 'OPEN':
                pt = PaperTrade(trade['signal'], trade['entry_price'], trade['position_size'])
                # ^ CRASHES HERE if fields missing
                open_positions.append(pt)
```

**Issues:**
1. ❌ No schema validation
2. ❌ No field existence checks
3. ❌ Crashes on malformed data
4. ❌ Test data can pollute production logs
5. ❌ Ghost positions possible (closed records may still have status='OPEN')

### Other Scripts Reading Same Log:

| Script | Method | Authoritative? | Issues |
|--------|--------|----------------|--------|
| phase1-paper-trader.py | Filter status='OPEN' | ❌ Crashes on bad data | Missing field validation |
| exit-monitor.py | Filter status='OPEN' | ❌ Non-authoritative | Doesn't update main log |
| timeout-monitor.py | Filter status='OPEN' | ❌ Non-authoritative | Inherits ghost problem |
| live-readiness-validator.py | Filter status='CLOSED' | ❌ May miss closes | Uses different status values |

**Verdict:** NO SINGLE AUTHORITATIVE SOURCE

---

## 4. TESTS RUN

### Test 1: Hyperliquid LONG Entry (Direct Integration)

**Method:** Inject controlled signal → Run deployed trader via import + main()

**Evidence Type:** INTEGRATION TESTED (FAILED)

**Steps:**
1. Backup production logs ✅
2. Inject test signal: LONG TEST_ETH @ $2000, EV=60 ✅
3. Import phase1-paper-trader.py ✅
4. Call main() ❌ **FAILED**

**Error:**
```
KeyError: 'entry_price'
```

**Root Cause:** Log contains test data from unit tests missing required fields

**State Before:**
- Open: 1
- Closed: 2

**State After:**
- Open: 1 (unchanged)
- Closed: 2 (unchanged)

**Expected:**
- Open: 2 (+1 new position)

**Actual:**
- Trader crashed before execution

**Files Touched:**
- `logs/phase1-signals.jsonl` (signal injected ✅)
- `logs/phase1-paper-trades.jsonl` (not updated, trader crashed ❌)

**Evidence:**
```
Backups: logs/backup_20260321_030615/
Test signal: {"asset": "TEST_ETH", "direction": "LONG", "entry_price": 2000.0}
Error: KeyError 'entry_price' at line 102
```

---

## 5. EVIDENCE BY TEST

| Test Name | Evidence Type | Result | Files Touched | Verified? |
|-----------|---------------|--------|---------------|-----------|
| LONG Entry (Integration) | INTEGRATION TESTED | ❌ FAILED | signals.jsonl, trades.jsonl | ❌ No |

**Summary:** 0/1 tests passing

---

## 6. STRATEGY STATUS MATRIX

| Strategy | Declared In Docs | Code Present | Wired To Canonical | Schema Valid | Entry Verified | Exit Verified | Persistence Verified | Performance Counted | Status | Evidence Type | Blocking Issues |
|----------|-----------------|--------------|-------------------|--------------|----------------|---------------|---------------------|---------------------|--------|---------------|----------------|
| Hyperliquid Funding Arb | ✅ Yes | ✅ Yes | ✅ Yes | ❌ **NO** | ❌ **NO** | ❌ NO | ❌ NO | ❌ NO | **BROKEN** | INTEGRATION TESTED (FAILED) | Trader crashes on malformed log data, no schema validation |
| Polymarket Spread Arb | ✅ Yes | ✅ Yes | ❌ No | ❌ NO | ❌ NO | ❌ NO | ❌ NO | ❌ NO | **BROKEN** | STATIC CODE REVIEW | Schema mismatch, filtered out |

**Verdict:** 0/2 strategies working in canonical path

---

## 7. DOC HONESTY GAP

**Documentation Claims:**
- "Production-grade 7-layer system"
- "Fully operational"
- "Hyperliquid working"

**Reality:**
- Trader crashes on integration test
- No schema validation
- Test data pollutes production logs
- 0 strategies verified in canonical path

**Honesty Gap:** **SEVERE**

**Documentation overstates current system capability.**

---

## 8. COMPONENTS VERIFIED

**With INTEGRATION TEST evidence:**
- NONE

**With STATIC CODE REVIEW evidence:**
- ✅ Cron schedule exists
- ✅ Scripts exist
- ✅ Logs contain some data

**With REAL PAPER-TRADING evidence:**
- ⚠️ 1 position in log (from 2026-03-20)
- ❌ Unknown if opened via canonical path or manual injection

---

## 9. COMPONENTS STILL UNVERIFIED OR BROKEN

### BROKEN (Evidence of Failure):

1. **phase1-paper-trader.py** - Crashes on malformed log data
   - Evidence: Integration test failed with KeyError
   - Type: INTEGRATION TESTED (FAILED)

2. **Schema validation** - Nonexistent
   - Evidence: Log accepts records missing entry_price, position_size
   - Type: INTEGRATION TESTED (FAILED)

3. **State reconstruction** - Fragile
   - Evidence: Crashes when loading positions
   - Type: INTEGRATION TESTED (FAILED)

### UNVERIFIED (No Evidence):

4. **system-audit.py** - Claims to audit but doesn't test canonical path
   - Evidence Type: SIMULATION ONLY
   - Status: UNVERIFIED

5. **test-full-lifecycle.py** - Mock test, doesn't exercise real path
   - Evidence Type: SIMULATION ONLY
   - Status: UNVERIFIED

6. **live-readiness-validator.py** - May be disconnected
   - Evidence Type: NOT CHECKED
   - Status: UNVERIFIED

7. **exit-monitor.py** - Non-authoritative
   - Evidence Type: NOT CHECKED
   - Status: UNVERIFIED

8. **timeout-monitor.py** - Reads same fragile log
   - Evidence Type: NOT CHECKED
   - Status: UNVERIFIED

9. **execution-safety-layer.py** - Not in canonical path
   - Evidence Type: STATIC CODE REVIEW
   - Status: UNVERIFIED

10. **All 7 "layers"** - Only 2 called by orchestration
    - Evidence Type: STATIC CODE REVIEW
    - Status: ARCHITECTURE INCONSISTENT

---

## 10. FINAL VERDICT

**System Status:** **ARCHITECTURE INCONSISTENT**

**Reasoning:**
1. ❌ Canonical trader crashes on integration test
2. ❌ No schema validation
3. ❌ Fragile state reconstruction
4. ❌ Test contamination in production logs
5. ❌ 0/2 strategies verified functional
6. ❌ Docs claim "production-grade" but system fails basic integration test

**Evidence Quality:**
- Integration tests: 0/1 passing
- Real paper-trading evidence: Insufficient (1 position, unknown origin)
- Unit tests: 5/5 passing (but test wrong version)

**Confidence Level:** VERY LOW

**Required Next Steps:**
1. ✅ Add schema validation to log writes
2. ✅ Add field existence checks to load_open_positions()
3. ✅ Clean production logs (remove test data)
4. ✅ Re-run integration test
5. ✅ Verify one complete cycle: signal → entry → state → exit → performance

**Verdict:** **BROKEN** (cannot complete one integration test)

---

*Audit complete. System failed first integration test. No strategies verified functional.*
