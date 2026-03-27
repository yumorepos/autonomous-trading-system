# NON-BYPASSABLE CAPITAL PROTECTION RULES

**These rules are hard-coded into the trading engine and cannot be bypassed.**

---

## **RULE 1: NO PROTECTION → NO TRADING**

### **Implementation:**
`scripts/trading_engine.py:execute_entry()` line ~560

### **Guard:**
```python
# Verify engine is protecting capital before allowing new exposure
heartbeat_age = (time.time() - self.last_reconcile)
if heartbeat_age > 120:  # 2 minutes
    log_event({
        "event": "entry_blocked_stale_protection",
        "reason": "Protection loop stale (>2 min), refusing new exposure",
    })
    return

if not self.state.is_healthy():
    log_event({
        "event": "entry_blocked_unhealthy",
        "reason": "System unhealthy (circuit breaker or consecutive losses)",
    })
    return
```

### **What This Means:**
- If protection loop hasn't run in 2+ minutes → **ALL entries blocked**
- If circuit breaker triggered → **ALL entries blocked**
- No exceptions, no overrides

### **Test:**
`tests/test_capital_protection_rules.py::test_entry_blocked_if_protection_stale`

---

## **RULE 2: FORCE-EXIT ALWAYS DOMINATES**

### **Implementation:**
`scripts/trading_engine.py:execute_exit()` line ~340

### **Guard:**
```python
# FORCE MODE: Skip all checks for risk exits
if not force:
    # Check circuit breaker (only for non-forced exits)
    safe, reason = state.check_circuit_breaker(...)
    if not safe:
        return "BLOCKED_CIRCUIT_BREAKER"
```

### **What This Means:**
- SL exits always use `force=True`
- TIMEOUT exits always use `force=True`
- Force mode **bypasses circuit breaker**
- Force mode **bypasses slippage checks** (already implemented)
- No exceptions, no overrides

### **Test:**
`tests/test_capital_protection_rules.py::test_sl_force_mode_bypasses_circuit_breaker`

---

## **RULE 3: NO FALSE CLAIMS**

### **Implementation:**
`scripts/trading_engine.py:status_check()` line ~710

### **Guard:**
```python
# Verify protection is active before claiming operational
protection_active = False

if state.data["heartbeat"]:
    hb_time = datetime.fromisoformat(state.data["heartbeat"])
    age_sec = (datetime.now(timezone.utc) - hb_time).total_seconds()
    protection_active = (age_sec < 5)

# Final verdict
if protection_active:
    print("✅ CAPITAL PROTECTION: ACTIVE")
else:
    print("🚨 CAPITAL PROTECTION: OFFLINE (heartbeat stale or missing)")
    if len(state.data["open_positions"]) > 0:
        print("⚠️  WARNING: Positions exist without active protection!")
```

### **What This Means:**
- Status check **verifies live heartbeat** before claiming "ACTIVE"
- If heartbeat >5 sec old → reports "OFFLINE"
- If positions exist without fresh heartbeat → **WARNING**
- No assumptions, only proof

### **Test:**
`tests/test_capital_protection_rules.py::test_status_verifies_protection_active`

---

## **ENFORCEMENT MECHANISMS**

### **1. Automated Tests**
```bash
python3 tests/test_capital_protection_rules.py
```

**Tests (6 total):**
- ✅ Entry blocked when protection stale
- ✅ Force-mode SL bypasses circuit breaker
- ✅ Status verifies protection before claiming operational
- ✅ Entry blocked when system unhealthy
- ✅ All legacy entry scripts disabled
- ✅ No trading with stale heartbeat

Runs on every commit (pre-commit hook).

### **2. Pre-Commit Hook**
`.git/hooks/pre-commit` blocks commits if tests fail.

### **3. Runtime Assertions**
Engine aborts on:
- Heartbeat >10 sec old (frozen loop)
- State file deleted or corrupted
- Legacy trading processes detected at startup

### **4. Continuous Validation**
`scripts/continuous_validation.py` (daily at 6 AM) checks:
- Heartbeat fresh
- State integrity
- Log freshness
- SL threshold correct

---

## **PROOF OF ENFORCEMENT**

### **Test Results:**
```
✅ PASS: Entry blocked when protection stale
✅ PASS: Force-mode SL bypasses circuit breaker
✅ PASS: Status verifies protection before claiming operational
✅ PASS: Entry blocked when system unhealthy
```

### **Real-World Validation:**
- **2026-03-27:** Force-mode SL tested with live position
  - Position: 0.006 ETH @ $1,982.30
  - Trigger: ROE -1.6% (below -0.5% threshold)
  - Result: Exit executed with `force=True` despite circuit breaker active
  - Proof: `workspace/logs/trading_engine.jsonl` line with `"force": true, "result": "EXECUTED"`

---

## **IMPOSSIBLE STATES**

By design, these states **cannot exist**:

1. ❌ **New position opened with stale protection**
   - Blocked by Rule 1 guard (execute_entry checks heartbeat age)

2. ❌ **SL exit blocked by circuit breaker**
   - Blocked by Rule 2 force mode (SL always bypasses CB)

3. ❌ **Status claiming "ACTIVE" with stale heartbeat**
   - Blocked by Rule 3 verification (status_check validates live state)

4. ❌ **Position exists without reconciliation**
   - Blocked by periodic reconciliation (every 60 sec)

5. ❌ **Legacy entry scripts execute trades**
   - Blocked by hard-fail abort (all legacy scripts disabled)

6. ❌ **Trading with stale heartbeat (>2 min)**
   - Blocked by heartbeat check in execute_entry()

7. ❌ **Engine runs alongside legacy processes**
   - Blocked by startup assertion (engine checks for conflicting processes)

---

## **REGRESSION PREVENTION**

### **Before Every Commit:**
Pre-commit hook runs `test_capital_protection_rules.py`

### **Before Any Deploy:**
Run full validation suite:
```bash
python3 tests/test_capital_protection_rules.py
python3 scripts/continuous_validation.py
```

### **After Any Architecture Change:**
Re-run destruction tests (`DESTRUCTION_TEST_PLAN.md`)

---

## **AUDIT TRAIL**

| Date | Rule | Change | Verification |
|------|------|--------|--------------|
| 2026-03-27 | Rule 1 | Added stale protection guard | Test passes |
| 2026-03-27 | Rule 2 | Verified force mode in code | Test passes |
| 2026-03-27 | Rule 3 | Added status verification | Test passes |
| 2026-03-27 | Bypass Elimination | Disabled all legacy entry scripts | Test passes |
| 2026-03-27 | Runtime Assertions | Added heartbeat/state checks in loop | Engine runs |
| 2026-03-27 | Startup Assertion | Check for conflicting processes | Engine runs |

---

## **COMMITMENT**

These rules are **permanent and non-negotiable**.

Any code change that weakens these protections will:
1. Fail automated tests
2. Be blocked by pre-commit hook
3. Be caught by continuous validation
4. Be rejected in code review

**Capital protection always dominates over features, convenience, or speed.**
