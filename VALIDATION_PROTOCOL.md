# PERMANENT VALIDATION PROTOCOL

**Purpose:** Ensure trading system remains production-safe as it evolves.

**Philosophy:** Trust only what's verified. Test before production. Validate continuously.

---

## WHEN TO VALIDATE

### **1. Before Any Architecture Change**
- New feature → validate impact on existing paths
- Refactor → re-run core tests
- Dependency update → verify no regressions

### **2. After Any Bug Fix**
- Fix applied → re-run failed test
- Verify fix didn't break other paths
- Document what was learned

### **3. Daily (Automated)**
- Continuous validation script (6 AM daily)
- Checks: heartbeat, state, logs, reconciliation, SL logic
- Alerts if any check fails

### **4. After Every 10 Trades**
- Review edge analytics
- Check if strategy still profitable
- Validate SL/TP execution stats

---

## CORE VALIDATION TESTS

### **Must Pass Before Production:**

1. **Restart Recovery**
   - Engine reconciles orphaned positions on startup
   - No data loss, no duplicate execution

2. **Runtime Reconciliation**
   - Engine detects positions opened/closed externally
   - State stays consistent within 60 seconds

3. **Force-Mode SL Execution**
   - SL triggers when ROE breaches threshold
   - Force mode bypasses circuit breaker
   - Exit executes immediately (<5 sec)

4. **State Consistency**
   - Exchange, state file, logs all match
   - No phantom or orphaned positions

5. **Heartbeat Liveness**
   - Heartbeat updates every cycle (<2 sec)
   - External monitoring can detect stale engine

---

## TEST EXECUTION GUIDELINES

### **Controlled Testing:**
- Use smallest position size possible ($10 minimum)
- Test with real capital (paper trading doesn't catch real bugs)
- Document expected behavior before test
- Capture proof (logs, state files, screenshots)

### **When a Test Fails:**
1. **Stop immediately** — don't continue testing
2. **Document the failure** — exact scenario, logs, state
3. **Fix root cause** — not just symptoms
4. **Re-run failed test** — verify fix works
5. **Check for side effects** — run other tests
6. **Update this protocol** — document lesson learned

---

## CONTINUOUS VALIDATION SCRIPT

**File:** `scripts/continuous_validation.py`

**Schedule:** Daily at 6 AM (cron)

**Checks:**
- ✅ Heartbeat fresh (<10 sec)
- ✅ State file valid JSON
- ✅ Logs recent (<10 min)
- ✅ Reconciliation working (if positions exist)
- ✅ SL threshold correct (-7%, not test value)

**On Failure:**
- Script exits with code 1
- Logs failure reason
- User alerted via log file

---

## REGRESSION PREVENTION

### **Before Committing Code:**
1. Run `python3 scripts/continuous_validation.py`
2. Verify all checks pass
3. If any fail → fix before commit

### **Before Scaling Capital:**
1. Re-run destruction tests (DESTRUCTION_TEST_PLAN.md)
2. Verify 5+ successful trade cycles
3. Check no new failures introduced

### **After Any Downtime:**
1. Run continuous validation
2. Check engine reconciled correctly
3. Verify no stale state or orphaned positions

---

## VALIDATION HISTORY

| Date | Event | Validated | Outcome |
|------|-------|-----------|---------|
| 2026-03-27 | Restart recovery | Manual test | ✅ PASS |
| 2026-03-27 | Runtime reconciliation | Manual test | ❌ FAIL → FIXED |
| 2026-03-27 | Force-mode SL | Controlled position | ✅ PASS |
| 2026-03-27 | State consistency | Manual test | ✅ PASS |
| 2026-03-27 | Continuous validation | Automated script | ✅ PASS |

---

## MINDSET COMMITMENTS

1. **Never overclaim** — "production-safe" only when proven
2. **Test before scale** — validate at $100 before $1000
3. **Document failures** — every bug is a lesson
4. **Trust only proof** — not design, not theory, only evidence
5. **Validate continuously** — safety degrades without verification

---

## ESCALATION

If continuous validation fails:
1. **Low priority** (heartbeat 5-10 sec old) → Monitor
2. **Medium priority** (logs stale, reconciliation missing) → Investigate within 24h
3. **High priority** (SL threshold wrong, state corrupted) → Fix immediately
4. **Critical** (engine down, positions unprotected) → Emergency halt, manual intervention

---

## NEXT EVOLUTION

As system matures:
- Add more automated tests (API failure simulation, partial fills)
- Increase validation frequency (daily → hourly for critical checks)
- Add alerting (Telegram notifications on failure)
- Build test suite (pytest framework for all paths)

**But never:** Skip validation to move faster. Speed without safety is just risk.
