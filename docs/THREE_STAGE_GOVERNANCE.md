# Three-Stage Governance Model
**Version:** 3.0 (Production)  
**Implemented:** 2026-03-20 18:57 EDT  
**Status:** ✅ ENFORCED

---

## Lifecycle Flow

```
┌──────────────┐
│   VALIDATE   │ Paper trading, collecting data (min 30 trades)
└──────┬───────┘
       │
       │ All validation criteria met?
       │
       ▼ YES
┌──────────────┐
│   PROMOTE    │ Validated, awaiting human approval
└──────┬───────┘
       │
       │ ┌──────────────────┐
       │ │  QUARANTINE      │ Performance warning, monitoring
       │ └────────┬─────────┘
       │          │
       │          │ Recovered?
       │          └────YES──────┘
       │
       │ Human approves?
       │
       ▼ YES
┌──────────────┐
│     LIVE     │ Live capital allowed (Phase 3)
└──────────────┘

       Any critical trigger?
              │
              ▼ YES
       ┌──────────────┐
       │    DEMOTE    │ Failed validation
       └──────────────┘
```

---

## Stage 1: VALIDATE

**Purpose:** Paper trading, data collection, initial validation

**Entry:** All new strategies start here

**Requirements for promotion:**
1. ✅ Minimum 30 trades (statistical significance)
2. ✅ Win rate ≥ 60%
3. ✅ Profit factor ≥ 1.5
4. ✅ Max drawdown ≤ 15%
5. ✅ Sharpe ratio ≥ 1.0
6. ✅ Expectancy ≥ $0.50 per trade
7. ✅ Total P&L > $0

**Exit:**
- → PROMOTE (all criteria met)
- → DEMOTE (if critical trigger fires before 30 trades)

---

## Stage 2: QUARANTINE

**Purpose:** Performance warning buffer before demotion

**Entry triggers** (any warning = quarantine):
- Win rate drops below 50%
- Profit factor drops below 1.2
- 3 consecutive losses
- 15%+ degradation from peak

**While in quarantine:**
- Continue paper trading
- Monitored closely each cycle
- Quarantine cycle counter increments
- Can recover and return to PROMOTE

**Exit:**
- → PROMOTE (performance recovers, no warnings)
- → DEMOTE (3+ quarantine cycles OR critical trigger)

---

## Stage 3: PROMOTE

**Purpose:** Validated, awaiting human approval for live capital

**Status:** Strategy meets all validation criteria, ready for Phase 3

**Requirements for LIVE:**
- ✅ All validation criteria met
- ✅ Performance stable (no warnings)
- ✅ **Human approval explicitly granted**

**Human approval queue:**
- Strategy added to `human-approval-queue.json`
- Supervisor generates approval request
- Human reviews metrics, approves/rejects
- Only after approval → LIVE stage

**Exit:**
- → LIVE (human approves)
- → QUARANTINE (performance warning)
- → DEMOTE (critical trigger)

---

## Stage 4: LIVE

**Purpose:** Human-approved, live capital eligible

**Status:** Strategy cleared for Phase 3 micro-execution

**Constraints:**
- Max position size: $5 (micro-execution)
- Continuous monitoring (same quarantine/demotion logic applies)
- Human can revoke approval at any time

**Exit:**
- → QUARANTINE (performance warning)
- → DEMOTE (critical trigger)

---

## Stage 5: DEMOTE

**Purpose:** Failed strategies, removed from consideration

**Entry triggers** (immediate demotion):
- Win rate drops below 45%
- Profit factor drops below 1.0
- 5 consecutive losses
- 25%+ degradation from peak
- 3+ cycles in quarantine without recovery

**Status:** Strategy removed from active tracking

**Possible recovery:**
- Can be re-evaluated after significant code changes
- Must restart from VALIDATE stage
- No shortcuts

---

## Governance Criteria Summary

| Stage | Criteria | Thresholds |
|-------|----------|------------|
| **VALIDATE** | Promotion to PROMOTE | 30 trades, 60% WR, 1.5 PF, 15% MDD, 1.0 Sharpe, $0.50 expectancy |
| **QUARANTINE** | Warning (enter quarantine) | WR < 50%, PF < 1.2, 3 loss streak, 15% degradation |
| **QUARANTINE** | Critical (demote) | WR < 45%, PF < 1.0, 5 loss streak, 25% degradation, 3 cycles |
| **PROMOTE** | Human approval | Manual review + explicit approval |
| **LIVE** | Monitoring | Same quarantine/demotion logic |

---

## Metrics Calculated

### Expectancy
```
E = Average P&L per trade
```
- Measures profit per trade
- E > 0 = profitable system
- E ≥ $0.50 = validation requirement

### Win Rate
```
WR = (Wins / Total Trades) × 100%
```
- Basic profitability measure
- WR ≥ 60% = strong edge

### Profit Factor
```
PF = Gross Profit / Gross Loss
```
- Risk-adjusted profitability
- PF ≥ 1.5 = high quality

### Max Drawdown
```
MDD = (Peak - Trough) / Peak × 100%
```
- Worst equity decline
- MDD ≤ 15% = acceptable risk

### Sharpe Ratio
```
SR = Average Return / Std Dev
```
- Consistency measure
- SR ≥ 1.0 = good consistency

### Degradation
```
D = (Peak WR - Current WR) / Peak WR
```
- Performance decline from peak
- D ≥ 15% = warning
- D ≥ 25% = critical

---

## Human Approval Process

**1. Strategy reaches PROMOTE stage**
- Supervisor adds to approval queue
- File: `logs/human-approval-queue.json`

**2. Supervisor generates approval request**
- Full metrics included
- Validation checks shown
- Risk assessment provided

**3. Human reviews**
- Check metrics against criteria
- Verify performance stability
- Assess risk tolerance

**4. Human decision**
- **Approve:** Strategy → LIVE, cleared for Phase 3
- **Reject:** Strategy → QUARANTINE or DEMOTE
- **Defer:** Request more data, keep in PROMOTE

**5. Approval logged**
- Timestamp recorded
- Approver identified
- Strategy transitions to LIVE

---

## Quarantine Logic

**Purpose:** Graceful degradation, avoid premature demotion

**Three-strike rule:**
- Strike 1: Warning triggers, enter quarantine
- Strike 2: Still in quarantine next cycle, counter = 2
- Strike 3: Third cycle in quarantine, demote

**Recovery:**
- Performance improves (no warnings)
- Exit quarantine, return to PROMOTE
- Counter resets to 0

**Benefits:**
- Avoids false positives (temporary dips)
- Gives strategies time to recover
- Clear escalation path

---

## Regime-Aware Performance (Planned)

**Future enhancement:** Track performance across market regimes

**Regimes to track:**
- High volatility (VIX > 25)
- Low volatility (VIX < 15)
- Trending markets
- Range-bound markets
- Crisis conditions

**Benefits:**
- Validate strategies per-regime
- Pause strategies in unfavorable regimes
- Promote only regime-robust strategies

**Status:** Not implemented (Phase 2 enhancement)

---

## Files & Data

**Strategy Registry:**
- File: `logs/strategy-registry.json`
- Tracks: stage, timestamps, peak performance, lifecycle events
- Updated: Every supervisor cycle (4 hours)

**Human Approval Queue:**
- File: `logs/human-approval-queue.json`
- Tracks: pending approvals, approved strategies, rejected strategies
- Updated: When strategy reaches PROMOTE

**Supervisor Decisions:**
- File: `logs/supervisor-decisions.jsonl`
- Logs: All transitions, reasons, metrics
- Append-only audit trail

**Governance Report:**
- File: `SUPERVISOR_GOVERNANCE_REPORT.md`
- Human-readable summary
- Generated every cycle

---

## Example Registry Entry

```json
{
  "strategies": {
    "funding_arbitrage": {
      "name": "funding_arbitrage",
      "stage": "PROMOTE",
      "created_at": "2026-03-20T18:00:00Z",
      "promoted_at": "2026-03-22T14:00:00Z",
      "quarantined_at": null,
      "live_approved_at": null,
      "live_approved_by": null,
      "peak_performance": {
        "trades": 32,
        "win_rate": 65.7,
        "profit_factor": 2.1,
        "max_drawdown": 8.3,
        "sharpe_ratio": 1.4,
        "expectancy": 0.85,
        "total_pnl": 12.45
      },
      "current_performance": {
        "trades": 35,
        "win_rate": 64.2,
        "profit_factor": 2.0,
        "max_drawdown": 9.1,
        "sharpe_ratio": 1.3,
        "expectancy": 0.78,
        "total_pnl": 13.20
      },
      "quarantine_cycles": 0,
      "lifecycle_events": [
        {
          "timestamp": "2026-03-22T14:00:00Z",
          "type": "VALIDATION_COMPLETE",
          "reason": "All validation criteria met"
        }
      ]
    }
  }
}
```

---

## Benefits of Three-Stage Model

**1. Graceful Degradation**
- QUARANTINE buffer prevents premature demotion
- Strategies get time to recover
- Reduces false positives

**2. Human Oversight**
- No strategy goes live without explicit approval
- Human reviews metrics before capital risk
- Clear approval audit trail

**3. Clear Lifecycle**
- Every strategy has a defined path
- No ambiguous states
- Easy to understand status

**4. Conservative Validation**
- Multiple criteria (not just win rate)
- Risk-adjusted metrics (PF, Sharpe, MDD)
- Expectancy requirement

**5. Continuous Monitoring**
- LIVE strategies still monitored
- Can be quarantined or demoted
- Performance degradation detected early

---

## Schedule

**Every 4 hours:**
```
22:00 → Trading Agency executes
22:15 → Governance Supervisor reviews
        ├─ Evaluate all strategies
        ├─ Apply promotion/quarantine/demotion logic
        ├─ Update strategy registry
        ├─ Add to approval queue if promoted
        └─ Generate governance report
```

---

**This governance model enforces conservative, risk-managed strategy validation with human oversight before any live capital deployment.**

*Model enforced automatically. Human approval required only for PROMOTE → LIVE transition.*
