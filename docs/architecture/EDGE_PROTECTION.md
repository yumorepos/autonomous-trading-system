> **Status: ASPIRATIONAL** — describes design intent or goals, not verified current state.

# EDGE PROTECTION SYSTEM

**Purpose:** Ensure velocity optimizations don't degrade edge  
**Mode:** Continuous monitoring + automatic revert  
**Created:** 2026-03-26

---

## PROBLEM

We optimized for trade velocity (faster exits, lower thresholds) to accelerate validation from 30 days → 15 days.

**Risk:** Faster ≠ better if edge degrades. We might complete 20 trades quickly but with negative expectancy.

**Solution:** Monitor edge continuously, revert if degraded.

---

## PROTECTION RULES

### Two-Tier Safety System

**Tier 1: Early Warning (3-5 Trades)**
- **Expectancy warning:** < $0.30 per trade
- **Win rate warning:** < 40%
- **Action:** MONITOR (no revert yet, just alert)
- **Purpose:** Pre-emptive awareness of deterioration

**Tier 2: Automatic Revert (10+ Trades)**
- **Expectancy threshold:** Must be ≥ $0.50 per trade
- **Win rate threshold:** Must be ≥ 50%
- **Action:** AUTO-REVERT to conservative parameters
- **Purpose:** Preserve edge over speed

### Why Two Tiers?

**Early Warning (3-5 trades):**
- Catches problems early
- No automatic action (avoids overreacting to noise)
- Gives heads-up before full revert

**Automatic Revert (10 trades):**
- Enough data to be statistically meaningful
- Not too late (still have 10 more trades to go)
- Auto-corrects without human intervention

---

## PARAMETERS

### Conservative (Pre-Velocity)
- **Stop-loss:** -10%
- **Take-profit:** +15%
- **Timeout:** 12 hours
- **Tier 1 funding:** ≥150%

### Optimized (Post-Velocity)
- **Stop-loss:** -7%
- **Take-profit:** +10%
- **Timeout:** 8 hours
- **Tier 1 funding:** ≥100%

**Revert = go back to Conservative if edge degrades**

---

## MONITORING WORKFLOW

### Daily Check (00:00-01:00 UTC)
1. Run `edge_monitor.py`
2. Count closed trades
3. **IF < 10 trades:** Continue with optimizations
4. **IF ≥ 10 trades:** Check expectancy + win rate
   - **IF degraded:** Auto-revert, notify user
   - **IF intact:** Continue optimizations

### Manual Check
```bash
python3 scripts/edge_monitor.py
```

---

## REVERT CONDITIONS

### Condition 1: Low Expectancy
- **Threshold:** < $0.50 per trade
- **Reason:** Not profitable enough (fees eat gains)
- **Action:** Revert to wider SL/TP

### Condition 2: Low Win Rate
- **Threshold:** < 50%
- **Reason:** Losing more than winning (even if expectancy positive)
- **Action:** Revert to higher Tier 1 threshold

### Condition 3: Both Low
- **Critical:** Edge likely broken
- **Action:** Revert + recommend manual review

---

## EXECUTION (Automated)

### When Degradation Detected:

**1. Revert Parameters**
```
risk-guardian.py:
  STOP_LOSS_ROE: -0.07 → -0.10
  TAKE_PROFIT_ROE: 0.10 → 0.15
  TIMEOUT_HOURS: 8 → 12

tiered_scanner.py:
  TIER1_MIN_FUNDING: 1.00 → 1.50
```

**2. Notify User**
```
⚠️ EDGE DEGRADATION DETECTED
Expectancy: $0.42 (below $0.50 min)
Win rate: 45% (below 50% min)

ACTION: Reverted to conservative parameters
  - SL: -7% → -10%
  - TP: +10% → +15%
  - Timeout: 8h → 12h
  - Tier 1: ≥100% → ≥150%

REASON: Edge preservation > trade frequency
```

**3. Log Decision**
- Record in memory file
- Commit parameter changes
- Update STATUS.md

---

## EXPECTED SCENARIOS

### Scenario 1: Edge Intact (Most Likely)
- 10 trades closed
- Expectancy: $0.70/trade
- Win rate: 55%
- **Action:** Continue with velocity optimizations
- **Result:** 20 trades by Day 15 (as planned)

### Scenario 2: Marginal Edge
- 10 trades closed
- Expectancy: $0.48/trade
- Win rate: 49%
- **Action:** Revert to conservative
- **Result:** 20 trades by Day 25 (slower but safer)

### Scenario 3: No Edge
- 10 trades closed
- Expectancy: -$0.10/trade
- Win rate: 40%
- **Action:** Revert + flag for manual review
- **Result:** Strategy may not work (review needed)

---

## INTEGRATION

### Works With:
- **daily_update.py** — Provides trade statistics
- **trade_logger.py** — Sources expectancy/win rate data
- **ceo_decision_engine.py** — Coordinates decisions
- **HEARTBEAT.md** — Runs daily automatically

### Does NOT Replace:
- Circuit breakers (still trip on 5 losses / $10 loss / 20% drawdown)
- Guardian exit logic (still manages SL/TP/trailing)
- Discipline lock (still blocks new strategies)

---

## TRADE-OFFS

### With Edge Protection:
✅ Safety net if velocity hurts performance  
✅ Automatic correction (no manual intervention)  
✅ Preserves capital over speed  
❌ May slow validation if revert needed  

### Without Edge Protection:
✅ Faster validation (no reverts)  
❌ Risk of validating with broken parameters  
❌ Could complete 20 trades with negative edge  
❌ Manual monitoring required  

**Conclusion:** Edge protection is worth the trade-off.

---

## MANUAL OVERRIDE

**User can override if:**
- Believes sample size too small
- Sees temporary variance (not edge degradation)
- Wants to continue velocity optimizations anyway

**Command:**
```
Override edge protection: continue velocity optimizations
```

**Aiden will:**
- Warn of risks
- Log override decision
- Continue with optimized parameters
- Re-check at 15 trades

---

## METRICS TO TRACK

### Primary
- **Expectancy:** $ per trade (target: >$0.50)
- **Win rate:** % wins (target: >50%)

### Secondary
- **Avg win:** $ per winning trade
- **Avg loss:** $ per losing trade
- **Trade frequency:** trades/day

### Tier Performance
- **Tier 1 expectancy:** $ per Tier 1 trade
- **Tier 2 expectancy:** $ per Tier 2 trade
- **Degradation:** Has velocity optimization hurt specific tier?

---

## FILES

**Monitor:** `scripts/edge_monitor.py`  
**Daily Update:** `scripts/daily_update.py`  
**Trade Logger:** `scripts/trade_logger.py`  
**Documentation:** `EDGE_PROTECTION.md` (this file)

---

## FINAL REMINDER

**Velocity optimization goal:** Get to 20 trades faster  
**Edge protection goal:** Ensure those 20 trades are profitable  

**Priority:** Edge > speed

If forced to choose:
- ✅ Slower validation with positive edge
- ❌ Faster validation with broken edge

---

**Status:** ACTIVE  
**Mode:** Continuous monitoring (daily checks)  
**First Check:** After 10th trade closes  
**Action:** Auto-revert if expectancy <$0.50 or win rate <50%
