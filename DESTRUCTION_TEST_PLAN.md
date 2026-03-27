# DESTRUCTION TEST PLAN

**Purpose:** Validate trading engine under failure conditions BEFORE production scaling.

**Status:** NOT YET EXECUTED (engine is architecturally correct but unproven)

---

## TESTING PHILOSOPHY

Real trading systems fail in ways you don't predict.

The only way to know your system is safe:
1. Build it correctly (✅ DONE — single loop, force SL, unified control)
2. **Break it intentionally** (⏳ THIS PHASE)
3. Verify it recovers safely (⏳ NEXT PHASE)

If you can't break it, it's safe. If you can break it, fix it before real money scales.

---

## TEST CATEGORIES

### CATEGORY 1: ENGINE CRASH SCENARIOS

**Test 1.1: Kill engine with open position**
```bash
# Setup: Open a position manually
# Action: kill -9 <engine_pid>
# Expected: On restart, engine reconciles position and continues protection
# Fail criteria: Position orphaned, SL not enforced after restart
```

**Test 1.2: Kill engine during exit execution**
```bash
# Setup: Trigger SL exit programmatically
# Action: kill -9 <engine_pid> IMMEDIATELY after exit starts
# Expected: On restart, engine detects position closed or retries exit
# Fail criteria: Position stuck open, exit never completes
```

**Test 1.3: Repeated crash/restart under load**
```bash
# Setup: Open multiple positions
# Action: kill/restart engine 5 times in 30 seconds
# Expected: Engine reconciles state each time, no data loss
# Fail criteria: State corruption, positions lost, duplicate exits
```

---

### CATEGORY 2: STATE CORRUPTION SCENARIOS

**Test 2.1: Corrupt state file (invalid JSON)**
```bash
# Setup: Open position, wait for heartbeat
# Action: echo "CORRUPTED" > workspace/logs/trading_engine_state.json
# Expected: Engine detects corruption, fails safe (halts or rebuilds from live API)
# Fail criteria: Engine crashes, continues with wrong state
```

**Test 2.2: Stale state file (old timestamp)**
```bash
# Setup: Stop engine, manually edit state file timestamp to 1 hour ago
# Action: Restart engine
# Expected: Engine detects staleness, reconciles with live API
# Fail criteria: Engine uses stale data, misses SL triggers
```

**Test 2.3: State file deleted mid-run**
```bash
# Setup: Engine running with positions
# Action: rm workspace/logs/trading_engine_state.json
# Expected: Engine rebuilds state on next save cycle
# Fail criteria: Engine crashes, protection stops
```

---

### CATEGORY 3: API FAILURE SCENARIOS

**Test 3.1: API timeout during position fetch**
```bash
# Setup: Open position
# Action: Block API endpoint via firewall (iptables or proxy)
# Expected: Engine retries, logs error, halts new entries (keeps trying protection)
# Fail criteria: Engine crashes, assumes position closed
```

**Test 3.2: API returns error during SL exit**
```bash
# Setup: Position at SL threshold
# Action: Mock API to return {"status": "error"}
# Expected: Engine retries exit, logs failure, alerts
# Fail criteria: Engine gives up, position stays open
```

**Test 3.3: Partial fill on exit**
```bash
# Setup: Large position
# Action: Mock API to return partial fill (50% closed)
# Expected: Engine detects partial, retries remaining size
# Fail criteria: Engine marks as fully closed, leaves 50% open
```

**Test 3.4: Rate limit during critical exit**
```bash
# Setup: Position at SL
# Action: Mock API to return 429 (rate limited)
# Expected: Engine waits, retries with backoff, eventually succeeds
# Fail criteria: Engine stops trying, position bleeds further
```

---

### CATEGORY 4: DATA INTEGRITY SCENARIOS

**Test 4.1: Price data missing (API returns null)**
```bash
# Setup: Open position
# Action: Mock API to return null price for coin
# Expected: Engine uses last known price or skips cycle, does not assume position safe
# Fail criteria: Engine treats as "no trigger", misses SL
```

**Test 4.2: Price data stale (1 hour old)**
```bash
# Setup: Open position
# Action: Mock API to freeze price timestamp
# Expected: Engine detects staleness, halts new entries, keeps monitoring
# Fail criteria: Engine uses stale price, misses real SL breach
```

**Test 4.3: Conflicting data (API says closed, but live fetch shows open)**
```bash
# Setup: Close position via engine
# Action: Mock next API call to show position still open
# Expected: Engine detects conflict, reconciles (trusts live data)
# Fail criteria: Engine desyncs, believes wrong state
```

---

### CATEGORY 5: CIRCUIT BREAKER SCENARIOS

**Test 5.1: Force-mode SL bypasses circuit breaker**
```bash
# Setup: Trigger circuit breaker (3 consecutive losses)
# Action: Open position, breach SL
# Expected: Engine exits despite circuit breaker (force mode)
# Fail criteria: Position stays open because circuit breaker blocks exit
```

**Test 5.2: Circuit breaker blocks new entries (not exits)**
```bash
# Setup: Trigger circuit breaker
# Action: Scanner finds signal
# Expected: Engine blocks entry, logs "system_unhealthy"
# Fail criteria: Engine opens position despite halt
```

**Test 5.3: Circuit breaker recovery**
```bash
# Setup: Trigger circuit breaker
# Action: Manually reset consecutive_losses = 0 in state file
# Expected: Engine resumes normal operation
# Fail criteria: Engine stays halted even after reset
```

---

### CATEGORY 6: RACE CONDITION SCENARIOS

**Test 6.1: Simultaneous entry + exit (impossible state)**
```bash
# Setup: Position very close to SL
# Action: Scanner triggers entry for same coin during exit
# Expected: Engine blocks duplicate entry (already_open check)
# Fail criteria: Duplicate position opens
```

**Test 6.2: Heartbeat lag detection**
```bash
# Setup: Engine running
# Action: Artificially pause Python process (kill -STOP <pid>)
# Expected: External monitoring detects stale heartbeat, alerts
# Fail criteria: No detection, system looks healthy
```

---

### CATEGORY 7: EDGE CASE SCENARIOS

**Test 7.1: Position size rounding errors**
```bash
# Setup: Very small position ($5 instead of $20)
# Action: Trigger SL
# Expected: Engine closes full size, no dust remains
# Fail criteria: Partial close, dust left open
```

**Test 7.2: Leverage != 1 (if ever used)**
```bash
# Setup: Position with 2x leverage
# Action: Trigger SL
# Expected: Engine calculates ROE correctly with leverage
# Fail criteria: Wrong ROE calculation, SL missed or premature
```

**Test 7.3: Negative funding (we pay, not earn)**
```bash
# Setup: Position open when funding flips positive
# Action: Wait for funding payment
# Expected: Engine continues monitoring, SL still enforced
# Fail criteria: Engine assumes negative is always earnings
```

---

## EXECUTION PROTOCOL

### PHASE 1: CONTROLLED ENVIRONMENT TESTS (FIRST)

Run tests 1.1 - 7.3 in **dry-run mode** on testnet or with **micro capital** ($5 positions).

**Before each test:**
1. Document expected behavior
2. Set up monitoring (logs, heartbeat, state file)
3. Execute failure injection
4. Observe recovery

**After each test:**
1. Verify state consistency
2. Check logs for errors
3. Confirm capital protected
4. Document actual behavior vs expected

### PHASE 2: LIVE VALIDATION (SECOND)

Run tests on **real positions** with **current capital** ($95).

**Acceptance criteria:**
- ✅ Engine recovers from all failures
- ✅ Capital always protected (SL never missed)
- ✅ State stays consistent (no desyncs)
- ✅ Logs are accurate (audit trail complete)

### PHASE 3: CONTINUOUS TESTING (ONGOING)

Add tests to **automated suite** (run weekly):
- Random engine restarts
- Random API timeouts
- Random state corruption
- Verify recovery time < 5 seconds

---

## FAILURE HANDLING CHECKLIST

When a test fails:

1. **Do NOT ignore it** — every failure is a production bug waiting to happen
2. **Document the failure** — exact scenario, logs, state
3. **Fix the root cause** — not just the symptom
4. **Re-run the test** — verify fix works
5. **Add regression test** — ensure it never breaks again

---

## SUCCESS CRITERIA

Engine is **production-safe** when:

- ✅ All Category 1-7 tests pass
- ✅ 5 real trade cycles complete without issues
- ✅ No state desyncs detected
- ✅ SL execution time < 2 seconds (99th percentile)
- ✅ Recovery time < 5 seconds after any crash

**Only then:** Claim "production-validated" and scale capital.

---

## RISK ACKNOWLEDGMENT

**If you skip this phase:**
- You will encounter these failures in production (not test)
- Capital will be at risk during recovery
- Debugging will be harder (real money pressure)
- Trust in system will erode

**If you execute this phase:**
- You know exactly how system fails
- You've fixed failure modes before production
- You have confidence in recovery
- You can scale safely

---

## CURRENT STATUS

- Architecture: ✅ Correct (single loop, force SL)
- Testing: ❌ NOT YET EXECUTED
- Production-safe: ❌ NO

**Next step:** Execute Category 1 tests (engine crash scenarios)
