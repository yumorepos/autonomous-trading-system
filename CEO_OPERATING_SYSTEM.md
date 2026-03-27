# CEO OPERATING SYSTEM

> **Mission:** Double $97 → $194 in 30 days through disciplined capital allocation, systematic execution, and continuous optimization.

---

## I. CAPITAL ALLOCATION ENGINE

### Current State (2026-03-26)
- **Total Capital:** $97.14
- **Deployed:** $30 (31%) in 2 positions
- **Idle:** $67 (69%)
- **Target:** >70% deployed when opportunities exist

### Multi-Strategy Portfolio

| Strategy | Capital | Expected Daily | Status |
|---|---|---|---|
| **Tier 1 Funding Arb** | $30 (2×$15) | $0.12 | ✅ Active |
| **Tier 2 Funding Arb** | $0 | $0 | ⏸️ Standby |
| **Premium Reversion** | $0 | $0 | ⏸️ Standby |
| **Polymarket** | $0 ($43 separate) | $0 | ⏸️ Standby |
| **Total** | **$30** | **$0.12** | **In Progress** |

### Target Allocation (When Signals Exist)
- Tier 1 Funding: $45 max (3 positions × $15)
- Tier 2 Funding: $16 max (2 positions × $8)
- Premium Reversion: $10 max (1 position)
- **Total Target:** $71 (73% deployed)

---

## II. DAILY EXECUTION PLAN

### Morning Scan (00:00 UTC)
- [ ] Review overnight positions (ROE, funding earned)
- [ ] Check for new signals (Tier 1 priority)
- [ ] Verify guardian status (SL/TP triggers)
- [ ] Update capital allocation plan

### Afternoon Scan (12:00 UTC)
- [ ] Mid-day position check
- [ ] Scan for Tier 2 opportunities
- [ ] Review trade logger (any new closes?)
- [ ] Adjust deployment if market conditions change

### Evening Review (20:00 UTC)
- [ ] Daily P&L summary
- [ ] Funding earned vs expected
- [ ] Position health check
- [ ] Tomorrow's priority list

### Continuous (Every 30 Min)
- ✅ Auto-scan via launchd
- ✅ Guardian monitors positions
- ✅ Auto-entry on qualifying signals
- ✅ Auto-exit on SL/TP/trailing/thesis-decay

---

## III. PERFORMANCE TRACKING

### Daily Metrics
- **Total P&L:** Unrealized + Realized
- **Funding Earned:** Actual vs Expected
- **Capital Utilization:** Deployed / Total
- **Signal Hit Rate:** Entries / Scans
- **Guardian Efficiency:** Exits / Reasons

### Weekly Review (Every Sunday)
- Closed trades this week
- Win rate trend
- Expectancy trend
- Tier 1 vs Tier 2 performance
- Threshold calibration needs

### Monthly Milestone (Day 30)
- **Target:** $194 (100% gain)
- **Required:** 2.3% daily compound
- **Validation:** ≥20 closed trades for statistical significance

---

## IV. RISK CONTROLS (Non-Negotiable)

### Position Limits
- Max 3 Tier 1 positions ($15 each)
- Max 2 Tier 2 positions ($8 each)
- Max 1 Premium Reversion ($10)
- **Hard cap:** $71 deployed (73% of capital)

### Circuit Breakers
- **5 consecutive losses:** Halt 24h
- **$10 loss in 1 day:** Halt 24h
- **$3 loss in 1 hour:** Halt 1h
- **20% drawdown from peak:** Full stop, manual review

### Exit Discipline
- **Stop-loss:** -10% ROE (auto-exit)
- **Take-profit:** +15% ROE (auto-exit)
- **Trailing:** Activates +2%, trails 2% behind
- **Timeout:** 12h max hold
- **Thesis decay:** Funding drops >40% from entry + ROE < 0 → exit

---

## V. OPPORTUNITY RANKING (Real-Time EV)

### Ranking Formula
```
EV Score = (Expected Profit × Win Probability) - (Max Loss × Loss Probability)
         + (Funding Income × Hold Time)
         - (Opportunity Cost)
```

### Example:
**Tier 1 Signal (PROVE @ 151% funding, -0.8% premium):**
- Expected profit: $2.25 (TP +15%)
- Win probability: 50%
- Max loss: $1.50 (SL -10%)
- Loss probability: 10%
- Funding: $0.06/day × 3 days = $0.18
- **EV = (2.25 × 0.5) - (1.50 × 0.1) + 0.18 = $1.19**

**Tier 2 Signal (84% funding, -0.5% premium):**
- Expected profit: $0.60 (TP +8%)
- Win probability: 45%
- Max loss: $0.64 (SL -8%)
- Loss probability: 15%
- Funding: $0.03/day × 2 days = $0.06
- **EV = (0.60 × 0.45) - (0.64 × 0.15) + 0.06 = $0.20**

**Polymarket (Near-expiry convergence @ 97%):**
- Expected profit: $0.30 (3% gap to $1.00)
- Win probability: 95%
- Max loss: $10 (full position)
- Loss probability: 5%
- Hold time: <24h
- **EV = (0.30 × 0.95) - (10 × 0.05) = -$0.22** (REJECT)

---

## VI. LEARNING LOOP (Post-Trade 20)

### After 20 Closed Trades:

#### 1. Measure Realized Performance
- Actual win rate vs expected
- Actual expectancy vs model
- Funding earned vs price P&L ratio
- Tier 1 vs Tier 2 ROI

#### 2. Calibrate Thresholds
**If Tier 1 outperforms Tier 2 by >2x:**
- Raise Tier 1 requirements (150% → 175% funding)
- Lower Tier 2 allocation ($8 → $5)

**If Funding > 80% of total P&L:**
- Optimize for hold time (lower TP, higher tolerance)

**If Win rate < 50%:**
- Tighten entry filters (require 3+ confirmations)

#### 3. Dynamic Scaling
**If 10+ consecutive profitable days:**
- Scale Tier 1 size: $15 → $18
- Scale max positions: 3 → 4

**If drawdown > 10%:**
- Reduce Tier 1 size: $15 → $12
- Pause Tier 2 entries

---

## VII. CURRENT EXECUTION STATUS

### Live Positions (2026-03-26 20:00 UTC)
1. **SUPER LONG**
   - Entry: $0.11927 (126 coins)
   - Current: $0.11911
   - ROE: -0.13%
   - Tier: 2 (was Tier 1 at entry — funding decayed)
   - Guardian: Active (SL/TP/trailing)
   - Expected hold: 1-5 days

2. **PROVE LONG**
   - Entry: $0.27336 (55 coins)
   - Current: $0.27478
   - ROE: +0.52%
   - Tier: 2 (was Tier 1 at entry — funding decayed)
   - Guardian: Active
   - Expected hold: 1-5 days

### Next Scan: 20:30 UTC (30 min)
- Looking for: Tier 1 signals (deploy up to $45 more)
- Backup: Tier 2 signals (deploy up to $16 more)

### Tomorrow's Plan (2026-03-27)
1. **00:00 UTC:** Morning review
2. **Continuous:** Scanner running every 30 min
3. **Target:** Deploy 2-3 more positions (reach 60-70% utilization)
4. **Goal:** $0.25/day total income (from positions + funding)

---

## VIII. 30-DAY ROADMAP

### Week 1 (Days 1-7): VALIDATION PHASE
- **Goal:** 5-10 closed trades
- **Focus:** Prove edge exists (positive expectancy)
- **Action:** Execute, log, measure
- **No changes:** Let system run as-is

### Week 2 (Days 8-14): CALIBRATION PHASE
- **Goal:** 10-15 closed trades total
- **Focus:** Tier performance comparison
- **Action:** Analyze Tier 1 vs Tier 2 results
- **Minor adjustments:** Threshold tweaks if needed

### Week 3 (Days 15-21): SCALING PHASE
- **Goal:** 20+ closed trades (edge validated)
- **Focus:** Increase capital deployment
- **Action:** Scale position sizes if performance supports it
- **Risk:** Monitor drawdown closely

### Week 4 (Days 22-30): COMPOUND PHASE
- **Goal:** Maximize capital efficiency
- **Focus:** Deploy all proven strategies simultaneously
- **Action:** Multi-strategy execution (Tier 1 + Tier 2 + PM if triggered)
- **Target:** Hit $194 (or prove 30-day doubling is unrealistic)

---

## IX. DASHBOARD (Real-Time)

### Key Metrics (Update Daily)
```
Capital: $97.14 → $??? (Target: $194)
Deployed: 31% → ??? (Target: >70%)
Daily P&L: $0.00 → $??? (Target: $2.23/day)
Closed Trades: 0 → ??? (Target: 20+)
Win Rate: N/A → ??? (Target: >50%)
Expectancy: N/A → ??? (Target: >$0.50/trade)
```

### Today's Snapshot (2026-03-26)
- ✅ 2 positions entered (SUPER, PROVE)
- ✅ Tiered allocation active
- ✅ Trade logger ready
- ⏸️ Waiting for first closed trade
- ⏸️ Market scan continues every 30 min

---

## X. COMMANDS

### View Performance
```bash
python3 scripts/trade_logger.py
```

### Check Current Positions
```bash
python3 -c "from scripts.risk_guardian import check_positions; check_positions()"
```

### Force Manual Scan
```bash
cd /Users/yumo/Projects/autonomous-trading-system
ENTRY_MODE=live python3 scripts/hl_entry.py
```

### View Tiered Signals
```bash
python3 scripts/tiered_scanner.py
```

---

**Last Updated:** 2026-03-26 20:14 UTC
**Status:** OPERATIONAL
**Mode:** LIVE CAPITAL DEPLOYMENT
**Next Milestone:** First closed trade → validation begins
