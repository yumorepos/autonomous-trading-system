> **Status: ASPIRATIONAL** — describes design intent or goals, not verified current state.

# CEO DECISION ENGINE

**Purpose:** Automated decision-making based on daily update data  
**Mode:** Semi-autonomous (safety limits enforced)  
**Created:** 2026-03-26

---

## DECISION MATRIX

### State 1: IN_PROGRESS (<20 trades)
**Action:** HOLD  
**Automated:** YES  
**Execution:** System continues, no changes  
**Reason:** Insufficient data for validation

### State 2: VALIDATED (≥20 trades, exp>$0.50, WR>50%)
**Action:** SCALE  
**Automated:** YES  
**Execution:**
- Increase Tier 1: $15 → $18 (+20%)
- Increase Tier 2: $8 → $10 (+25%)
- Unlock optimization (discipline lock released)
- Notify user of changes

**Reason:** Edge proven, safe to scale

### State 3: WEAK_EDGE (≥20 trades, exp>$0, WR>45%)
**Action:** HOLD  
**Automated:** YES  
**Execution:** Continue at current sizing, accumulate 10 more trades  
**Reason:** Modest edge, need more data

### State 4: NO_EDGE (≥20 trades, exp<$0 or WR<45%)
**Action:** REVIEW  
**Automated:** NO (requires manual approval)  
**Execution:** None, notify user  
**Reason:** Strategy not working, pivot decision needed

### State 5: CIRCUIT_BREAKER (drawdown >20%)
**Action:** HALT  
**Automated:** YES  
**Execution:** Stop all new entries, notify user immediately  
**Reason:** Capital preservation

---

## AUTOMATION BOUNDARIES

### ✅ WILL Auto-Execute:
1. **HOLD** (validation in progress)
2. **SCALE** (edge validated)
3. **HALT** (circuit breaker trips)

### ❌ WILL NOT Auto-Execute:
1. **Strategy pivots** (NO_EDGE state)
2. **Capital deployment >63%** (max $61 deployed)
3. **Discipline lock overrides** (before 20 trades)
4. **New strategy additions** (before validation)

---

## SAFETY LIMITS (Non-Negotiable)

### Circuit Breakers (Auto-Halt)
1. **5 consecutive losses** → Halt 24 hours
2. **$10 loss in 1 day** → Halt 24 hours
3. **20% drawdown from peak** → Full stop, manual review required

### Discipline Lock (Enforced Until 20 Trades)
1. **NO new strategies** (even if requested)
2. **NO optimization** (thresholds, filters)
3. **NO forced rebalancing** (existing positions)
4. **Only exception:** Circuit breaker override

### Capital Preservation
1. **Max deployed:** 63% ($61 of $97)
2. **Reserve:** 37% minimum ($36)
3. **Exception:** Week 4 (Day 22-30) can deploy 100% IF edge validated

---

## EXECUTION WORKFLOW

### Daily Cycle (00:00-01:00 UTC):
1. **Run daily_update.py** → Get current state
2. **Run ceo_decision_engine.py** → Assess validation state
3. **Determine action** → HOLD / SCALE / REVIEW / HALT
4. **Execute (if automated)** → Make changes, log decision
5. **Notify user** → Post decision + reasoning to chat

### Manual Trigger:
```bash
python3 scripts/ceo_decision_engine.py
```

---

## DECISION LOG FORMAT

```
======================================================================
  CEO DECISION ENGINE
  2026-03-27 01:00 UTC
======================================================================

CURRENT STATE:
  Capital: $107.46
  Closed Trades: 0 / 20
  Win Rate: N/A
  Expectancy: N/A

VALIDATION STATE: IN_PROGRESS

RECOMMENDED ACTION:
  Action: HOLD
  Reason: Validation in progress (0/20 trades)
  Automated: YES

EXECUTION:
  ✅ System continues autonomously, no changes

======================================================================
```

---

## ESCALATION RULES

### When to Notify User:
1. **Edge validated** (20 trades, exp>$0.50, WR>50%)
   - Message: "✅ Edge validated! Scaling position sizes."
   
2. **No edge found** (20 trades, exp<$0 or WR<45%)
   - Message: "⚠️ Strategy not working. Manual review required."

3. **Circuit breaker trips** (drawdown >20%)
   - Message: "🔴 CIRCUIT BREAKER: System halted. Review immediately."

4. **Milestone hit** (Day 10, Day 20, Day 30)
   - Message: Progress summary + next phase

### When NOT to Notify:
- Daily HOLD actions (validation in progress)
- Routine guardian exits (normal operation)
- Scanner finding 0 signals (market dry)

---

## OVERRIDE PROTOCOL

### User Can Override:
**Command:** "Override discipline lock: [reason]"

**Effect:**
- Temporarily disable automation
- Allow manual strategy changes
- Log override in decision history

**Restriction:**
- Must state explicit reason
- Aiden will warn of consequences
- Override expires after 24h (must re-approve)

---

## INTEGRATION WITH EXISTING SYSTEMS

### Works With:
1. **daily_update.py** — Provides state data
2. **trade_logger.py** — Provides trade statistics
3. **tiered_scanner.py** — Modified for scaling
4. **risk_guardian.py** — Enforces circuit breakers
5. **discipline lock** — Enforced until 20 trades

### Does NOT Replace:
- Guardian exit logic (still handles SL/TP/trailing)
- Entry module (still enters on signals)
- Circuit breakers (still trip automatically)

---

## EXPECTED BEHAVIOR (30 Days)

### Week 1 (Days 1-7):
- **State:** IN_PROGRESS
- **Action:** HOLD daily
- **User sees:** "Validation in progress (X/20 trades)"

### Week 2 (Days 8-14):
- **State:** IN_PROGRESS
- **Action:** HOLD daily
- **User sees:** "Validation in progress (X/20 trades)"

### Week 3 (Days 15-21):
**IF edge validated (Day 20):**
- **State:** VALIDATED
- **Action:** SCALE (auto-execute)
- **User sees:** "✅ Edge validated! Tier 1 $15→$18, Tier 2 $8→$10"

**IF edge not validated:**
- **State:** NO_EDGE
- **Action:** REVIEW (notify user)
- **User sees:** "⚠️ Strategy not working. Manual review required."

### Week 4 (Days 22-30):
- **State:** Depends on Week 3 outcome
- **Action:** Continue scaled strategy OR pivot to alternative

---

## FILES

**Engine:** `scripts/ceo_decision_engine.py`  
**Daily Update:** `scripts/daily_update.py`  
**Documentation:** `CEO_DECISION_ENGINE.md` (this file)  
**Discipline Lock:** `.discipline-lock`

---

**Status:** ACTIVE  
**Mode:** Semi-Autonomous (safety limits enforced)  
**Next Decision:** Daily at 00:00-01:00 UTC
