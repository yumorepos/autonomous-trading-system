> **Status: ASPIRATIONAL** — describes design intent or goals, not verified current state.

# EXPANSION ROADMAP — Multi-Venue Trading System

**Created:** 2026-04-06  
**30-Day Goal:** $97 → $194 via Hyperliquid funding arbitrage (ends 2026-04-25)

---

## **PHASED EXPANSION STRATEGY**

### **PHASE 1: Hyperliquid Validation (Days 1-10)**

**Status:** ✅ IN PROGRESS  
**Started:** 2026-03-27  
**Current:** 0/10 trades audited

**Objectives:**
- Validate production execution under real market conditions
- Prove capital protection under stress
- Establish baseline reliability metrics

**Exit Criteria (ALL REQUIRED):**
- ✅ 10+ closed trades
- ✅ At least 2 losing trades (stop-loss execution validated)
- ✅ At least 1 partial fill (idempotent close validated)
- ✅ At least 1 retry scenario (backoff/jitter validated)
- ✅ Zero state drift over 7 consecutive days
- ✅ Zero duplicate execution events
- ✅ Emergency fallback tested (simulated heartbeat loss)

**Hard Rules:**
- NO strategy changes until validation complete
- NO threshold relaxation
- NO scaling until all gates passed

---

### **PHASE 2: Polymarket Sandbox (Days 11-15)**

**Status:** ⏳ NOT STARTED  
**Prerequisite:** Phase 1 complete

**Objectives:**
- Build fully isolated Polymarket paper trading system
- Separate state, logs, capital bucket
- Zero interaction with Hyperliquid

**Architecture:**
```
polymarket_engine/
├── polymarket_state.json       # Separate state
├── polymarket_logs/           # Separate logs
├── probability_engine.py      # EV/fair odds calculator
├── paper_trader.py           # Paper execution only
└── capital_bucket_polymarket  # Separate capital tracking
```

**Isolation Rules:**
- ❌ No shared execution path
- ❌ No shared position state
- ❌ No shared mission file
- ❌ No shared risk counters
- ❌ No effect on Hyperliquid engine

**Deliverables:**
- Paper trading infrastructure
- Probability engine (fair odds estimator)
- EV scoring system
- Calibration tracker

---

### **PHASE 3: Paper Edge Validation (Days 16-20)**

**Status:** ⏳ NOT STARTED  
**Prerequisite:** Phase 2 complete

**Objectives:**
- Prove edge exists before risking capital
- Establish calibration baseline
- Test signal sources in paper mode

**Success Metrics (ALL REQUIRED):**
- ✅ 100+ paper trades logged
- ✅ Calibration error <10% (predicted vs actual EV)
- ✅ Sharpe ratio >1.5 (after fees/slippage)
- ✅ Win rate >55% (if binary bets)
- ✅ Edge persists across 3+ market conditions
- ✅ Model beats random coin flip by >10%

**Hard Rules:**
- NO live execution until all metrics hit
- NO relaxing thresholds to pass faster
- NO cherry-picking favorable periods

---

### **PHASE 4: Signal Source Isolation (Days 21-25)**

**Status:** ⏳ NOT STARTED  
**Prerequisite:** Phase 3 complete

**Objectives:**
- Add news/X ingestion as research inputs (NOT execution triggers)
- Build event → EV update pipeline
- Maintain human-readable rationale

**Pipeline:**
1. Source event (news/X/feed)
2. Parser (extract structured data)
3. Confidence score (0-100)
4. Human-readable rationale
5. Paper EV update (log only)

**Never:**
- ❌ "Tweet seen → trade"

**Always:**
- ✅ "Tweet seen → model update → EV recomputed → logged"

**Deliverables:**
- Event parser
- Confidence scorer
- Rationale generator
- Paper EV update logger

---

### **PHASE 5: Tiny Live Exploration (Post-30-Day)**

**Status:** ⏳ NOT STARTED  
**Prerequisite:** Phase 4 complete + 30-day goal achieved

**Objectives:**
- Test execution under real Polymarket conditions
- Validate fill quality, latency, state consistency
- Goal is execution truth, not profit

**Capital Allocation:**
```
Polymarket live bucket: $20 max (separate wallet)
Per-position limit:     $2 max
Daily loss limit:       $5 max
Positions at once:      1 max
```

**Circuit Breakers:**
- If daily loss hit → paper-only for 48 hours
- If calibration drifts >15% → halt, review model
- If duplicate execution → rollback to paper

**Hard Rules:**
- ❌ NO threshold relaxation until baseline proven
- ❌ NO scaling on "looks promising"
- ❌ NO shared capital with Hyperliquid

---

### **PHASE 6: Live Audit (Post-Validation)**

**Status:** ⏳ NOT STARTED  
**Prerequisite:** Phase 5 complete (10+ live Polymarket trades)

**Audit Checklist:**
- ✅ Fill quality (slippage vs expected)
- ✅ Latency (order → fill time)
- ✅ State consistency (ledger/state/exchange match)
- ✅ Duplicate prevention (ownership logic working)
- ✅ Market resolution handling (correct settlement)
- ✅ Exit/hedge behavior (correct timing)
- ✅ Model-vs-market drift (calibration stable)

**Scale ONLY if both true:**
- ✅ Execution is clean
- ✅ Edge is real

---

### **PHASE 7: Multi-Venue Orchestration (Future)**

**Status:** ⏳ NOT STARTED  
**Prerequisite:** Both Hyperliquid AND Polymarket independently stable

**Objectives:**
- Build portfolio allocator above both systems
- Unified risk management
- Cross-venue capital optimization

**Until then:**
- Hyperliquid = one system
- Polymarket = separate system

**Hard Rules:**
- ❌ Never share fallback/exit ownership logic until separately proven
- ❌ Never let Polymarket changes modify Hyperliquid behavior
- ❌ Never merge capital buckets before both proven

---

## **CAPITAL ALLOCATION**

```
Hyperliquid bucket:    $97 USDC (current, live)
Polymarket bucket:     $20 USDC (future, separate wallet)
Emergency reserve:     $50 USDC (never touch)

NEVER merge buckets until both proven
```

---

## **ROLLBACK PROTOCOL**

**If at any phase:**
- State drift detected → rollback to previous phase
- Duplicate execution → rollback to paper
- Unresolved anomaly >24 hours → halt all new entries
- Capital loss >10% in 7 days → freeze, audit, review
- Calibration drift >15% → halt, review model

---

## **TIMELINE INTEGRATION WITH 30-DAY GOAL**

**30-Day Goal (2026-03-27 to 2026-04-25):**
- Target: $97 → $194 (100% gain) via Hyperliquid funding arbitrage
- Focus: Validate + scale Hyperliquid only
- Polymarket: Build paper engine in parallel (no live)

**Post-30-Day (2026-04-26+):**
- Hyperliquid: Proven, running
- Polymarket: Transition from paper → tiny live exploration
- Goal: Prove second edge before scaling

---

## **CURRENT STATUS (2026-04-06)**

**Active Phase:** Phase 1 (Hyperliquid Validation)  
**Progress:** 0/10 trades audited  
**Days Remaining:** ~20 days  
**Capital:** $95.67 USDC  
**Next Gate:** Complete 10+ validated trades

**Action:** Monitor Hyperliquid for natural trades, audit each one, complete Phase 1 validation before expanding.

---

## **HARD RULES (PERMANENT)**

1. **Never mix validation and expansion**
2. **Never relax thresholds before proving the engine**
3. **Never let Polymarket changes modify Hyperliquid behavior**
4. **Never share fallback/exit ownership logic across venues until separately proven**
5. **Never scale on "looks promising"**
6. **Always validate with real money before scaling**
7. **Always maintain separate state/logs/capital until proven**
8. **Always require ALL exit criteria before advancing phase**

---

**Next Review:** After Phase 1 completion (10+ trades validated)
