# Authoritative State Map
**Date:** 2026-03-21 03:12 EDT  
**Purpose:** Document single source of truth for all system state

---

## QUESTION: What is authoritative?

**Answer:** NOTHING is truly authoritative. Multiple scripts reconstruct state independently from same append-only log.

---

## STATE SOURCES (All Non-Authoritative)

### 1. Position State

**Claimed Source:** `logs/phase1-paper-trades.jsonl`

**Method:** Append-only JSONL, filtered on read

**Reconstruction Logic:**
```python
# phase1-paper-trader.py
open_positions = []
with open(PAPER_TRADES_FILE) as f:
    for line in f:
        trade = json.loads(line)
        if trade['status'] == 'OPEN':
            open_positions.append(trade)
```

**Issues:**
- ❌ No schema validation
- ❌ Crashes if fields missing
- ❌ Ghost positions (old OPEN records remain after close)
- ❌ Test data pollution

**Authoritative?** ❌ NO

---

### 2. Performance Metrics

**Claimed Source:** `logs/phase1-performance.json`

**Method:** Calculated and written by trader

**Code:**
```python
# phase1-paper-trader.py
performance = {
    'total_trades': len(closed_trades),
    'win_rate': win_rate,
    'total_pnl': total_pnl
}
# MISSING: f.write()
```

**Issue:** File not written in deployed version (bug)

**Authoritative?** ❌ NO (never updated)

---

### 3. Readiness Metrics

**Claimed Source:** `logs/phase1-paper-trades.jsonl` (via live-readiness-validator.py)

**Method:** Count trades with `status == 'CLOSED'`

**Issue:** Deployed trader uses different status values (`STOP_LOSS`, `TAKE_PROFIT`, `TIME_EXIT`)

**Code:**
```python
# phase1-paper-trader.py line 62
self.status = reason  # 'STOP_LOSS' | 'TAKE_PROFIT' | 'TIME_EXIT'

# live-readiness-validator.py (assumed)
closed = [t for t in trades if t['status'] == 'CLOSED']
```

**Mismatch:** Validator may never count Hyperliquid closes

**Authoritative?** ❌ NO (disconnected)

---

### 4. Signals State

**Source:** `logs/phase1-signals.jsonl`

**Method:** Append-only, filtered by timestamp (last 5 hours)

**Code:**
```python
# phase1-paper-trader.py
cutoff = datetime.now(timezone.utc).timestamp() - (5 * 3600)
recent = [s for s in signals if parse_time(s['timestamp']) > cutoff]
```

**Authoritative?** ⚠️ PARTIAL (append-only works, no validation)

---

## SCRIPTS READING STATE

| Script | State Type | Source File | Method | Issues |
|--------|------------|-------------|--------|--------|
| phase1-paper-trader.py | Open positions | phase1-paper-trades.jsonl | Filter status='OPEN' | Crashes on missing fields |
| phase1-paper-trader.py | Performance | phase1-performance.json | Read JSON | Never written (bug) |
| exit-monitor.py | Open positions | phase1-paper-trades.jsonl | Filter status='OPEN' | Non-authoritative, doesn't update |
| timeout-monitor.py | Open positions | phase1-paper-trades.jsonl | Filter status='OPEN' | Inherits ghost problem |
| live-readiness-validator.py | Closed trades | phase1-paper-trades.jsonl | Filter status='CLOSED' | May miss Hyperliquid closes |
| trading-agency-phase1.py | Open positions | phase1-paper-trades.jsonl | Filter status='OPEN' | Duplicates logic |

**Total scripts reading state:** 5+

**Scripts writing authoritative updates:** 0 (all write new records, none update existing)

---

## EVIDENCE OF NON-AUTHORITATIVE STATE

### Proof 1: Integration Test Crash

**Test:** Inject signal → Run trader

**Result:** Crash on line 102

**Error:** `KeyError: 'entry_price'`

**Cause:** Log contains test data missing required fields

**Evidence:** Trader has no schema validation, accepts any JSONL

---

### Proof 2: Ghost Positions

**Observation:** Closed positions may remain as OPEN in log

**Cause:** Append-only design

**Example:**
```
Line 1: {"status": "OPEN", "asset": "ETH", ...}
Line 2: {"status": "CLOSED", "asset": "ETH", ...}
```

**Problem:** Scripts filter for status='OPEN' → Line 1 still matches

---

### Proof 3: Status Mismatch

**Trader writes:**
```python
self.status = 'STOP_LOSS'  # or 'TAKE_PROFIT' or 'TIME_EXIT'
```

**Validator expects:**
```python
if trade['status'] == 'CLOSED':  # Never matches
```

**Result:** Validator may never count any closes

---

### Proof 4: Performance File Never Written

**Code:**
```python
# line ~240
perf_json = json.dumps(performance, indent=2)
# MISSING: with open(PERFORMANCE_FILE, 'w') as f: f.write(perf_json)
```

**Evidence:** File last modified days ago, not updated by recent runs

---

## REQUIRED FIXES

### Fix 1: Add Dedicated State File

**Current:** Append-only log, reconstructed on read

**Needed:** `position-state.json` with current positions only

**Format:**
```json
{
  "positions": {
    "position_id_1": {
      "status": "OPEN",
      "asset": "ETH",
      "entry_price": 2000.0,
      ...
    }
  },
  "last_updated": "2026-03-21T07:00:00Z"
}
```

**Benefits:**
- ✅ Single source of truth
- ✅ Atomic updates
- ✅ No ghost positions
- ✅ Schema enforceable

---

### Fix 2: Add Schema Validation

**Enforce on write:**
```python
REQUIRED_FIELDS = ['position_id', 'asset', 'entry_price', 'position_size', 'status', 'entry_time']

def validate_trade(trade):
    for field in REQUIRED_FIELDS:
        if field not in trade:
            raise ValueError(f"Missing required field: {field}")
```

---

### Fix 3: Unify Status Values

**Current:** Multiple status values (OPEN, CLOSED, STOP_LOSS, TAKE_PROFIT, TIME_EXIT)

**Needed:** Consistent status + separate close_reason

**Format:**
```json
{
  "status": "CLOSED",
  "close_reason": "STOP_LOSS",
  ...
}
```

---

### Fix 4: Fix Performance Write

**Add:**
```python
with open(PERFORMANCE_FILE, 'w') as f:
    json.dump(performance, f, indent=2)
```

---

## CURRENT STATE MAP

```
AUTHORITATIVE SOURCES: NONE

RECONSTRUCTED SOURCES:
  phase1-paper-trades.jsonl (append-only, fragile)
    ↓ read independently by 5+ scripts
    ↓ no coordination
    ↓ inconsistent interpretations
    ↓ crashes on bad data

RESULT: ARCHITECTURE INCONSISTENT
```

---

## HONEST VERDICT

**Question:** What is the single source of truth for open positions?

**Answer:** **NONE EXISTS**

**Evidence:**
1. ❌ No dedicated state file
2. ❌ Multiple scripts reconstruct independently
3. ❌ No schema validation
4. ❌ Crashes on malformed data
5. ❌ Test data pollutes production
6. ❌ Ghost positions possible

**Verdict:** **NO AUTHORITATIVE STATE**

---

*State map complete. No authoritative source found. Architecture inconsistent.*
