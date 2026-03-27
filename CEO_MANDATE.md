# CEO MANDATE: FULL AUTONOMOUS EXECUTION

> **Effective:** 2026-03-26 20:26 UTC
> **Authority:** CEO (Yumo)
> **Scope:** All ATS operations

---

## MISSION

Run the ATS end-to-end as a capital allocator by:
1. Continuously scanning and executing ONLY valid high-edge trades
2. Maximizing capital efficiency WITHOUT forcing low-quality entries
3. Logging every trade with full lifecycle data
4. Prioritizing rapid completion of ≥20 closed trades to validate expectancy
5. Maintaining strict risk controls and system stability
6. Avoiding premature optimization or rebalancing
7. Automatically transitioning to performance-based scaling ONLY after sufficient real data proves a durable edge

---

## OPERATIONAL PARAMETERS

### Scanning & Execution
- **Frequency:** Every 30 minutes (launchd)
- **Mode:** LIVE capital deployment
- **Entry criteria:** Tier 1 or Tier 2 signals only (Tier 3 = reject)

### Capital Allocation
- **Tier 1:** $15 per position (≥150% funding, <-1% premium, ≥$1M volume)
- **Tier 2:** $8 per position (≥75% funding, <-0.5% premium, ≥$500k volume)
- **Max positions:** 3 Tier 1 + 2 Tier 2 = $61 max deployed (63% of capital)
- **Current utilization:** 31% ($30 deployed) — ACCEPTABLE given market conditions

### Risk Controls (Non-Negotiable)
- **Stop-loss:** -10% ROE (auto-exit)
- **Take-profit:** +15% ROE (auto-exit)
- **Trailing stop:** Activates +2%, trails 2% behind
- **Timeout:** 12 hours max hold
- **Thesis degradation:** Funding drops >40% from entry + ROE < 0 → exit

### Circuit Breakers
- **5 consecutive losses:** Halt 24 hours
- **$10 loss in 1 day:** Halt 24 hours
- **20% drawdown from peak:** Full stop, manual review required

### Trade Logging
- **Every entry:** Asset, price, size, tier, funding, premium, timestamp
- **Every exit:** Exit price, reason (SL/TP/trailing/timeout/thesis-decay), hold time, P&L
- **File:** `workspace/logs/trade-lifecycle.jsonl`
- **Analysis:** `python3 scripts/trade_logger.py`

---

## PROHIBITED ACTIONS (Until 20 Trades)

### ❌ NO Optimization
- NO threshold adjustments
- NO entry filter changes
- NO capital allocation rule changes

### ❌ NO Rebalancing
- NO forced exits to "rebalance" portfolio
- NO position resizing based on tier changes
- Natural exits only (via guardian triggers)

### ❌ NO Low-Quality Entries
- NO trades below Tier 2 minimum edge
- NO forcing capital deployment to hit utilization targets
- Market is dry → low utilization is CORRECT

---

## VALIDATION PHASE (First 20 Trades)

### Objective
Prove the edge exists before optimizing.

### Metrics to Track
1. **Win rate** (target: >50%)
2. **Expectancy** (target: >$0.50 per trade)
3. **Funding vs price P&L** (which dominates?)
4. **Tier 1 vs Tier 2 performance** (which is better?)
5. **Hold time distribution** (avg hours per trade)
6. **Exit reason breakdown** (SL/TP/trailing/timeout/thesis-decay)

### Timeline
- **Expected:** 2-4 weeks (at current 0.5 trades/day frequency)
- **Accelerated:** 10-14 days (if market heats up, 1-2 trades/day)

---

## TRANSITION TO SCALING (After 20 Trades)

### Condition 1: Edge Validated
**IF** expectancy > $0.50/trade AND win rate > 50%:
- Scale Tier 1: $15 → $18 (+20%)
- Scale Tier 2: $8 → $10 (+25%)
- Add 4th Tier 1 position (was max 3)
- Max deployed: $61 → $74

### Condition 2: Edge Weak
**IF** expectancy < $0 OR win rate < 45%:
- HALT all new entries
- Review thresholds (tighten filters)
- Reduce position sizes: Tier 1 $15 → $12, Tier 2 $8 → $6
- Resume cautiously

### Condition 3: Mixed Results
**IF** 0 < expectancy < $0.50 OR 45% < win rate < 50%:
- Continue at current sizing
- Analyze tier performance (Tier 1 vs Tier 2)
- Make minor threshold adjustments
- Accumulate 10 more trades before scaling

---

## CURRENT STATUS (2026-03-26 20:26 UTC)

### System State
- ✅ Scanner: Running (tiered_scanner.py)
- ✅ Entry module: LIVE mode
- ✅ Guardian: Monitoring every 30 min (launchd)
- ✅ Trade logger: Ready (0 closed trades)

### Capital
- **Total:** $97.14
- **Deployed:** $30 (31%)
- **Idle:** $67 (69%)
- **Target:** Deploy more when Tier 1/2 signals appear

### Positions
1. **SUPER LONG:** 126 coins @ $0.11927, ROE -4.07%, Tier 2
2. **PROVE LONG:** 55 coins @ $0.27336, ROE +1.36%, Tier 2

### Market
- **Tier 1 signals:** 0 (none pass ≥150% funding threshold)
- **Tier 2 signals:** 2 (SUPER, PROVE — already held)
- **Assessment:** Market is dry, 31% utilization is CORRECT

### Next Scan
- **Time:** ~20:30 UTC (every 30 min)
- **Action:** Enter new position IF valid signal appears
- **Otherwise:** Continue monitoring existing positions

---

## SUCCESS METRICS (30-Day Horizon)

### Week 1 (Days 1-7)
- **Goal:** 5-10 closed trades
- **Focus:** Prove edge exists (positive expectancy)
- **Action:** Execute, log, measure
- **No changes:** Let system run as-is

### Week 2 (Days 8-14)
- **Goal:** 10-15 closed trades total
- **Focus:** Tier performance comparison
- **Action:** Analyze Tier 1 vs Tier 2 results
- **Minor adjustments:** Threshold tweaks if needed

### Week 3 (Days 15-21)
- **Goal:** 20+ closed trades (edge validated)
- **Focus:** Scale capital deployment
- **Action:** Increase position sizes if performance supports it
- **Risk:** Monitor drawdown closely

### Week 4 (Days 22-30)
- **Goal:** Maximize capital efficiency
- **Focus:** Multi-strategy execution (Tier 1 + Tier 2 simultaneously)
- **Action:** Deploy all proven strategies
- **Target:** Validate 2.3% daily compound is achievable ($97 → $194)

---

## REPORTING

### Daily (Automated)
- Position health check (ROE, funding earned)
- New signals scanned
- Guardian status

### Weekly (Manual Review)
- Closed trades this week
- Win rate trend
- Expectancy trend
- Tier performance comparison

### After 20 Trades (Validation Report)
- Full statistical analysis
- Tier 1 vs Tier 2 comparison
- Optimization recommendations
- Scaling decision (yes/no/conditional)

---

## AUTHORITY & OVERRIDE

### Standing Authority (No Approval Needed)
- Enter any Tier 1 or Tier 2 signal
- Exit via guardian triggers (SL/TP/trailing/timeout/thesis-decay)
- Log all trades
- Continue 30-min scan cycle

### Requires CEO Approval
- Change tier thresholds before 20 trades
- Force rebalancing of existing positions
- Override circuit breakers
- Change risk parameters (SL/TP percentages)

### Emergency Manual Override
- CEO can manually exit any position at any time
- CEO can halt system immediately (`ENTRY_MODE=paper` or kill launchd)
- CEO can review logs anytime (`trade_logger.py`)

---

## FINAL DIRECTIVE

**Execute autonomously. Prove the edge. Scale when validated.**

No premature optimization.
No forced rebalancing.
No low-quality entries.

Let the system work.

---

**Issued:** 2026-03-26 20:26 UTC
**Authority:** CEO (Yumo)
**Status:** IN EFFECT
**Next Review:** After 20 closed trades
