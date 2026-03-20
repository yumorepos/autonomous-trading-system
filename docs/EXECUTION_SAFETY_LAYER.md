# Execution Safety & Reliability Layer
**Version:** 1.0  
**Deployed:** 2026-03-20 19:13 EDT  
**Status:** ✅ OPERATIONAL

---

## Purpose

**Critical safety layer between portfolio allocator and live execution.**

Prevents unsafe trades through:
- Pre-trade validation
- Circuit breakers
- Emergency kill switches
- Market condition checks
- Data integrity validation

**No trade reaches live execution without passing ALL safety checks.**

---

## Architecture Position

```
Portfolio Allocator
      ↓
      ↓ Proposed Trades
      ↓
┌─────▼──────────────────┐
│ EXECUTION SAFETY LAYER │ ← You are here
│  • Pre-trade validation│
│  • Circuit breakers    │
│  • Kill switches       │
│  • Health checks       │
│  • Block unsafe trades │
└─────┬──────────────────┘
      ↓ Validated Trades Only
      ↓
Live Execution (Hyperliquid API)
```

**Safety Guarantee:** All trades must pass validation before execution eligibility

---

## System Status States

### 🟢 SAFE
- All systems operational
- No circuit breakers triggered
- Exchange healthy
- Data integrity confirmed
- **Trading allowed**

### 🟡 CAUTION
- Non-critical issues detected
- Exchange slow but responsive
- Minor data staleness
- Recent warnings
- **Trading restricted** (extra validation)

### 🔴 HALT
- Critical issues detected
- Circuit breakers triggered
- Exchange down
- Data integrity compromised
- Kill switch active
- **All trading halted**

---

## Pre-Trade Validation Checks

Every proposed trade must pass **ALL** checks:

### 1. Signal Freshness ⏱️
**Threshold:** 5 minutes max signal age

**Check:**
```python
signal_age = now() - signal_timestamp
passed = signal_age <= 300 seconds
```

**Reason:** Prevents stale signals, market conditions change rapidly

**Severity:** CRITICAL (blocks trade)

---

### 2. Duplicate Order Prevention 🚫
**Threshold:** 60 second deduplication window

**Check:**
- Same asset
- Same direction (LONG/SHORT)
- Opened within last 60 seconds
- Still open

**Reason:** Prevents accidental double-execution

**Severity:** CRITICAL (blocks trade)

---

### 3. Position Size Limits 💰
**Threshold:** $20 max per position

**Check:**
```python
passed = position_size_usd <= 20
```

**Reason:** Capital preservation, prevents oversized bets

**Severity:** CRITICAL (blocks trade)

---

### 4. Exchange Health 🏥
**Threshold:** 1000ms max API latency

**Check:**
- API responds
- Latency < 1 second
- No errors

**Reason:** Prevents execution during outages or degraded performance

**Severity:** CRITICAL if DOWN, WARNING if SLOW

---

### 5. Liquidity Check 💧
**Threshold:** $10,000 min 24h volume

**Check:**
```python
passed = volume_24h >= 10000
```

**Reason:** Ensures sufficient liquidity for entry/exit

**Severity:** WARNING (caution but allow)

---

### 6. Spread Check 📊
**Threshold:** 1% max bid-ask spread

**Check:**
```python
spread_pct = (ask - bid) / bid * 100
passed = spread_pct <= 1.0
```

**Reason:** Prevents execution during illiquid conditions

**Severity:** WARNING (caution but allow)

---

### 7. Circuit Breakers 🔌
**Thresholds:**
- 5 consecutive losses → HALT
- $10 daily loss → HALT
- $3 hourly loss → HALT
- 20% drawdown from peak → HALT
- 60 seconds min between trades

**Reason:** Prevent catastrophic loss, enforce cooling periods

**Severity:** CRITICAL (halt system)

---

### 8. Kill Switch 🛑
**Manual emergency stop**

**Check:**
```python
passed = not kill_switch_active
```

**Reason:** Human override for any reason

**Severity:** CRITICAL (halt all trading)

---

### 9. Data Integrity ✅
**Checks:**
- Portfolio allocation file exists
- Strategy registry exists
- Data freshness < 6 hours

**Reason:** Prevents execution with stale/missing data

**Severity:** WARNING (allow with caution)

---

## Circuit Breaker Details

### Consecutive Loss Breaker
**Trigger:** 5 losses in a row  
**Action:** HALT system  
**Reset:** Manual intervention required  
**Cooldown:** Review required before restart

### Daily Loss Breaker
**Trigger:** $10 cumulative daily loss  
**Action:** HALT system  
**Reset:** Next trading day (00:00 UTC)  
**Cooldown:** 24 hours

### Hourly Loss Breaker
**Trigger:** $3 cumulative hourly loss  
**Action:** HALT system  
**Reset:** Next hour  
**Cooldown:** 1 hour

### Drawdown Breaker
**Trigger:** 20% decline from peak balance  
**Action:** HALT system  
**Reset:** Manual review required  
**Cooldown:** Until balance recovers or manual override

### Trade Frequency Breaker
**Trigger:** < 60 seconds since last trade  
**Action:** Block trade (not full halt)  
**Reset:** Automatic after cooldown  
**Cooldown:** 60 seconds

---

## Emergency Kill Switch

**Purpose:** Immediate halt of all trading activity

**Activation:**
- Manual (human override)
- Triggered by critical incident
- Portfolio-level risk threshold

**Effect:**
- All trades blocked
- System status → HALT
- Requires manual intervention to reactivate

**How to Activate:**
```bash
# Edit state file manually
nano ~/.openclaw/workspace/logs/execution-safety-state.json

# Set:
"kill_switch_active": true

# Or via script (future):
python3 scripts/emergency-stop.py
```

**How to Deactivate:**
```bash
# Review incident log first
cat logs/incident-log.jsonl | tail -10

# If safe to resume:
"kill_switch_active": false
```

---

## Incident Logging

**All safety events logged to:** `logs/incident-log.jsonl`

**Severity Levels:**
- **INFO:** Routine check passed
- **WARNING:** Non-critical issue, trade allowed with caution
- **CRITICAL:** Trade blocked, system halted

**Incident Structure:**
```json
{
  "timestamp": "2026-03-20T23:15:00Z",
  "severity": "CRITICAL",
  "message": "Circuit breaker triggered: 5 consecutive losses",
  "data": {
    "consecutive_losses": 5,
    "last_trade": "ZETA LONG -$2.50"
  }
}
```

**Retention:** Last 100 incidents kept in memory

---

## Blocked Actions Log

**All rejected trades logged to:** `logs/blocked-actions.jsonl`

**Structure:**
```json
{
  "timestamp": "2026-03-20T23:15:00Z",
  "proposal": {
    "strategy": "funding_arbitrage",
    "asset": "ZETA",
    "direction": "LONG",
    "entry_price": 0.0558,
    "position_size_usd": 4.89,
    "signal_timestamp": "2026-03-20T23:10:00Z"
  },
  "reason": "Signal too stale (8 minutes old)",
  "validations": [
    {
      "check_name": "signal_freshness",
      "passed": false,
      "severity": "CRITICAL",
      "reason": "Signal age: 480s (max: 300s)"
    }
  ]
}
```

**Use:** Audit trail, debugging, review false positives

---

## Safety Report

**File:** `EXECUTION_SAFETY_REPORT.md`  
**Updated:** Every 4 hours (before and after allocation)

**Contents:**
1. **System Status** (SAFE/CAUTION/HALT)
2. **Circuit Breaker Status** (all thresholds)
3. **Exchange Health** (UP/SLOW/DOWN + latency)
4. **Recent Incidents** (last 5)
5. **Emergency Controls** (kill switch, manual override)

**Example:**
```markdown
# EXECUTION SAFETY REPORT
**Generated:** 2026-03-20 19:15 EDT
**System Status:** SAFE

🟢 **SAFE** — All systems operational, trading allowed

## Circuit Breakers
- Consecutive Losses: 0/5
- Daily Loss: $0.00/$10.00
- Hourly Loss: $0.00/$3.00
- Drawdown from Peak: 0.0%/20.0%

## Exchange Health
### 🟢 Hyperliquid
**Status:** UP
**Latency:** 621ms
**Last Check:** 2026-03-20T23:12:53Z

## Emergency Controls
- Kill Switch: 🟢 OFF
- Manual Override: NO
```

---

## Schedule

**Safety checks run:**
- **XX:25** — Before allocation (pre-validation)
- **XX:35** — After allocation (post-validation)

**Full cycle:**
```
XX:00 → Trading Agency (scan + trade)
XX:15 → Governance Supervisor (evaluate + decide)
XX:25 → Safety Layer (pre-validation) ← NEW
XX:30 → Portfolio Allocator (assign capital)
XX:35 → Safety Layer (post-validation) ← NEW
```

**Next checks:** 20:25 EDT, 20:35 EDT

---

## Integration with System

### With Portfolio Allocator
- Safety layer runs **before** allocator
- Validates system health before capital allocation
- If HALT → allocator should not propose trades
- Allocator reads safety state before proceeding

### With Live Execution (Future)
- Safety layer validates **every** proposed trade
- No trade bypasses validation
- Blocked trades logged with full reason
- Human can review blocked trades

### With Governance Supervisor
- Supervisor can trigger circuit breakers
- Strategy demotions may trigger safety review
- Incident log feeds supervisor decisions

---

## Safety Guarantees

1. **No Stale Signals**
   - Max 5 minutes old
   - Prevents execution on outdated data

2. **No Duplicate Orders**
   - 60 second deduplication
   - Prevents double-execution bugs

3. **Position Size Limits**
   - Max $20 per trade
   - Caps single-trade risk

4. **Exchange Health Required**
   - API must be responsive
   - Prevents execution during outages

5. **Circuit Breakers Enforced**
   - Automatic halt on loss thresholds
   - Prevents runaway losses

6. **Kill Switch Available**
   - Instant manual stop
   - No questions asked

7. **Full Audit Trail**
   - Every check logged
   - Every blocked trade documented
   - Full incident history

---

## Future Enhancements

### Slippage Protection (Planned)
- Pre-execution slippage estimate
- Block if estimated slippage > 0.5%
- Compare expected vs actual execution price

### Portfolio-Level Exposure (Planned)
- Track total capital deployed
- Enforce max 50% portfolio exposure
- Prevent over-allocation

### Correlation Monitoring (Planned)
- Real-time correlation tracking
- Reduce exposure to correlated assets during execution
- Dynamic position sizing

### Adaptive Thresholds (Planned)
- Adjust limits based on market conditions
- Tighter limits during high volatility
- Relaxed limits during calm markets

---

## Files & Locations

| File | Purpose | Updated |
|------|---------|---------|
| `scripts/execution-safety-layer.py` | Safety engine | Every 4h |
| `logs/execution-safety-state.json` | Current state | Every 4h |
| `logs/blocked-actions.jsonl` | Rejected trades | On block |
| `logs/incident-log.jsonl` | Safety incidents | On event |
| `EXECUTION_SAFETY_REPORT.md` | Human report | Every 4h |

---

## Operational Procedures

### Daily Review
1. Check `EXECUTION_SAFETY_REPORT.md`
2. Verify system status is SAFE
3. Review any CAUTION flags
4. Check incident log for patterns

### After Incident
1. Review `logs/incident-log.jsonl`
2. Identify root cause
3. Check if circuit breaker triggered
4. Decide: resume or investigate further

### Kill Switch Activation
1. Immediate: set `kill_switch_active: true`
2. Review all open positions
3. Assess risk exposure
4. Determine if manual intervention needed
5. Document reason in incident log

### Kill Switch Deactivation
1. Review incident log thoroughly
2. Verify root cause resolved
3. Confirm system health checks pass
4. Set `kill_switch_active: false`
5. Monitor closely for 1 hour

---

**Safety layer operational. All proposed trades must pass validation before execution eligibility.**

*Zero tolerance for safety violations. Capital preservation is paramount.*
