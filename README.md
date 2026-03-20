# Autonomous Trading System

**Version:** 4.0  
**Status:** Production (Paper Trading)  
**Deployed:** 2026-03-20  

A production-grade autonomous trading system with 7 layers of validation, risk management, and adaptive intelligence.

---

## System Architecture

```
Layer 7: Human Oversight (final approval + emergency controls)
Layer 6: Live-Readiness Validator (deployment eligibility verification)
Layer 5: Execution Safety (9 pre-trade checks + circuit breakers)
Layer 4: Portfolio Allocator (risk-adjusted capital allocation)
Layer 3: Alpha Intelligence (adaptive learning + signal reweighting)
Layer 2: Governance Supervisor (3-stage validation + human approval)
Layer 1: Data Integrity (9 data quality checks + source health)
         ↓
Trading Agency (signal scanner + paper trader)
         ↓
Data Sources (Hyperliquid + Polymarket)
```

---

## Features

### 1. Data Integrity Layer
- Source health monitoring (API uptime, latency, failures)
- Schema validation (required fields per data type)
- Timestamp freshness (max 60s age)
- Price outlier detection (max 50% change)
- Volume validation (min $1K)
- Spread validation (max 5%)
- Funding stability checks
- Duplicate signal prevention (5 min window)
- **Signal decay logic (1h lifetime, linear)**

### 2. Alpha Intelligence Layer
- **Learns which sources/strategies/regimes produce best returns**
- Dynamic weight adjustment based on historical performance
- Multi-factor confirmation bonuses (2-3 sources = 20-50% bonus)
- Market regime detection (TREND/RANGE/HIGH_VOL/LOW_VOL)
- Automatic elimination of low-performing signal types
- Performance tracking by source, strategy, regime

### 3. Governance Supervisor (3-Stage)
- **VALIDATE:** Paper trading, collecting 30+ trades
- **QUARANTINE:** Performance warning buffer (3-strike rule)
- **PROMOTE:** Validated, awaiting human approval
- **LIVE:** Human-approved, live capital allowed
- 7 promotion criteria (Sharpe, WR, PF, MDD, expectancy)
- 4 quarantine triggers + 5 demotion triggers

### 4. Portfolio Allocator
- Risk-adjusted scoring (Sharpe 30%, PF 25%, expectancy 20%, WR 15%, MDD 10%)
- Correlation matrix (pairwise strategy correlation)
- Optimal weight calculation (correlation-adjusted)
- Capital allocation (max 50% exposure, 20% per strategy)
- Continuous rebalancing every 4 hours

### 5. Execution Safety Layer
- **9 pre-trade checks** (signal freshness, duplicates, position size, exchange health, etc.)
- **5 circuit breakers** (consecutive losses, daily/hourly loss limits, drawdown, frequency)
- Emergency kill switch (instant manual halt)
- System status (SAFE/CAUTION/HALT)
- Full audit trail (all checks logged)

### 6. Live-Readiness Validator
- **14 validation criteria** (100 trades, 14 days, Sharpe > 1.0, etc.)
- Cost modeling (0.15% total per trade: 0.10% slippage + 0.05% fees)
- Baseline comparisons (coin flip, random entry, buy-hold)
- Regime robustness testing (min 2 regimes)
- Operational robustness (recovery rate, incident tracking)
- **Deployment verdicts:** NOT_READY, LIMITED_LIVE_READY, LIVE_READY

### 7. Human Oversight
- Reviews all reports daily
- Approves PROMOTE → LIVE transitions
- Controls emergency kill switches
- Can override any decision

---

## Validation Criteria (Live Deployment)

**Critical (must pass):**
- 100+ closed paper trades
- 14+ days forward testing
- Sharpe ratio ≥ 1.0 (after costs)
- Profit factor ≥ 1.5
- Max drawdown ≤ 15%
- Expectancy ≥ $0.20 per trade
- Beat baseline strategies by 10%+

**Warnings (advisories):**
- Win rate ≥ 50%
- Max 10 consecutive losses
- Tested across 2+ market regimes
- Max 3 operational incidents
- 95%+ recovery success rate

---

## Execution Schedule

**Every 4 hours:**
```
XX:55 → Data Integrity (validate sources)
XX:00 → Trading Agency (scan + trade)
XX:15 → Governance Supervisor (evaluate + decide)
XX:20 → Alpha Intelligence (learn + adapt)
XX:25 → Safety Layer (pre-validation)
XX:30 → Portfolio Allocator (assign capital)
XX:35 → Safety Layer (post-validation)
```

**Daily (8 PM):**
```
20:00 → Live-Readiness Validator (deployment verdict)
```

---

## Current Status

**Deployment Verdict:** 🔴 NOT_READY

**Why:**
- 0 closed trades (need 100)
- 0 days tested (need 14)
- No performance data yet

**Expected Timeline:**
- Week 1-2: Accumulate 30+ trades
- Week 2-3: Hit 100 trades, 14 days
- Week 3-4: First validation (possibly LIMITED_LIVE_READY)
- Month 2: LIVE_READY verdict (if criteria met)

---

## Tech Stack

**Language:** Python 3.12  
**APIs:** Hyperliquid (229 assets), Polymarket (5+ markets)  
**Data:** Real-time funding rates, order book, market prices  
**Execution:** Paper trading (Hyperliquid testnet-equivalent)  
**Scheduling:** Cron (every 4 hours + daily validation)  
**Storage:** JSON logs, append-only audit trails  

---

## Components

### Scripts (9 files)
- `data-integrity-layer.py` (25.6 KB) — Data validation + source health
- `alpha-intelligence-layer.py` (25.2 KB) — Adaptive learning + signal reweighting
- `supervisor-governance.py` (23.0 KB) — 3-stage strategy validation
- `portfolio-allocator.py` (17.9 KB) — Risk-adjusted capital allocation
- `execution-safety-layer.py` (25.6 KB) — Pre-trade checks + circuit breakers
- `live-readiness-validator.py` (25.6 KB) — Deployment eligibility verification
- `trading-agency-phase1.py` — Agency orchestrator
- `phase1-signal-scanner.py` — Market data scanner
- `phase1-paper-trader.py` — Paper trading engine

### Logs (14 files)
- Data integrity state + metrics + rejected signals
- Alpha intelligence state + performance DB + weights
- Governance decisions + strategy registry + approval queue
- Portfolio allocation + history
- Execution safety state + blocked actions + incidents
- Live-readiness state + validation history
- Paper trades (all trades logged)
- Phase 1 signals + performance

### Documentation (5 files)
- `DATA_INTEGRITY_LAYER.md` (12.1 KB)
- `EXECUTION_SAFETY_LAYER.md` (11.0 KB)
- `CAPITAL_ALLOCATION.md` (8.6 KB)
- `THREE_STAGE_GOVERNANCE.md` (9.1 KB)
- `FINAL_SYSTEM_STATUS.md` (12.7 KB)

---

## Safety Guarantees

✅ **No stale data** (max 60s age)  
✅ **No incomplete data** (required fields validated)  
✅ **No price outliers** (max 50% change)  
✅ **No low volume** (min $1K)  
✅ **No wide spreads** (max 5%)  
✅ **No unstable funding** (volatility checks)  
✅ **No duplicate signals** (5 min dedup)  
✅ **No old signals** (1h decay)  
✅ **No unreliable sources** (health monitoring)  
✅ **No unvalidated strategies** (3-stage governance)  
✅ **No uncorrelated portfolios** (correlation matrix)  
✅ **No unsafe trades** (9 pre-trade checks)  
✅ **No unverified deployment** (live-readiness validation)  

---

## Risk Management

**7 layers of defense:**
1. Data integrity (validates inputs)
2. Alpha intelligence (learns what works)
3. Governance (validates strategies)
4. Portfolio allocation (optimizes capital)
5. Execution safety (validates trades)
6. Live-readiness (validates system)
7. Human oversight (final approval)

**Capital preservation:**
- Max 50% portfolio exposure
- Max 20% per strategy
- Max $5 per trade (Phase 3)
- Max $2 per trade (LIMITED_LIVE_READY)
- Circuit breakers (5 automatic halts)
- Kill switch (instant manual stop)

---

## Usage

**Monitor system:**
```bash
# Data health
cat ~/.openclaw/workspace/DATA_HEALTH_REPORT.md

# Execution safety
cat ~/.openclaw/workspace/EXECUTION_SAFETY_REPORT.md

# Governance status
cat ~/.openclaw/workspace/SUPERVISOR_GOVERNANCE_REPORT.md

# Portfolio allocation
cat ~/.openclaw/workspace/PORTFOLIO_ALLOCATION_REPORT.md

# Live-readiness verdict
cat ~/.openclaw/workspace/LIVE_READINESS_REPORT.md

# Alpha intelligence
cat ~/.openclaw/workspace/ALPHA_INTELLIGENCE_REPORT.md
```

**Check logs:**
```bash
tail -f ~/.openclaw/workspace/logs/phase1-paper-trades.jsonl
tail -f ~/.openclaw/workspace/logs/rejected-signals.jsonl
tail -f ~/.openclaw/workspace/logs/blocked-actions.jsonl
tail -f ~/.openclaw/workspace/logs/incident-log.jsonl
```

**Emergency stop:**
```bash
# Edit state file
nano ~/.openclaw/workspace/logs/execution-safety-state.json
# Set: "kill_switch_active": true
```

---

## License

MIT

---

## Contact

Built by Aiden (AI) + Yumo (Human)  
Montreal, Canada  
March 2026  

---

*Production-grade autonomous trading system. Zero tolerance for quality violations. Capital preservation is paramount.*
