# Dynamic Capital Allocation System
**Version:** 1.0  
**Document scope:** research-stage portfolio allocation notes  
**Status:** ✅ active support documentation for paper-trading research allocation

---

## Overview

Models paper-trading capital allocation across validated research strategies based on risk-adjusted performance, correlation, and portfolio-level constraints.

**Goal:** Maximize risk-adjusted returns while preserving capital through diversification and strict risk limits.

---

## Allocation Flow

```
Every 4 hours:
XX:00 → Trading Agency executes
XX:15 → Governance Supervisor reviews
XX:30 → Portfolio Allocator assigns capital
```

**Process:**
1. Load eligible research strategies from registry
2. Calculate risk-adjusted metrics for each
3. Compute correlation matrix
4. Calculate optimal weights (risk-score weighted, correlation-adjusted)
5. Apply portfolio constraints
6. Allocate capital proportionally
7. Generate allocation report

---

## Risk-Adjusted Scoring

Each strategy receives a **Risk Score** (0-100) based on:

| Metric | Weight | Range | Interpretation |
|--------|--------|-------|----------------|
| **Sharpe Ratio** | 30% | 0-3 → 0-1 | Risk-adjusted returns |
| **Profit Factor** | 25% | 0-3 → 0-1 | Gross profit / loss ratio |
| **Expectancy** | 20% | $0-1 → 0-1 | Average P&L per trade |
| **Win Rate** | 15% | 0-100% → 0-1 | % of winning trades |
| **Max Drawdown** | 10% | 0-20% → 1-0 | Inverted (lower is better) |

**Formula:**
```
Risk Score = (
    Sharpe * 0.30 +
    PF * 0.25 +
    Expectancy * 0.20 +
    WR * 0.15 +
    (1 - MDD/20) * 0.10
) * 100
```

**Example:**
- Sharpe 2.0 → 0.67 → 20.0 points
- PF 2.5 → 0.83 → 20.8 points
- Expectancy $0.80 → 0.80 → 16.0 points
- WR 65% → 0.65 → 9.8 points
- MDD 8% → 0.60 → 6.0 points
- **Total: 72.6/100**

---

## Portfolio Constraints

### Hard Limits

| Constraint | Threshold | Rationale |
|------------|-----------|-----------|
| **Max Total Exposure** | 50% | Preserve 50% cash reserve |
| **Max Strategy Weight** | 20% | Prevent single-strategy concentration |
| **Min Strategy Weight** | 2% | Exclude insignificant allocations |
| **Max Correlation** | 0.70 | Reduce weight for correlated strategies |
| **Max Portfolio Drawdown** | 15% | Circuit breaker |
| **Rebalance Threshold** | 10% | Trigger reallocation if drift > 10% |

### Soft Adjustments

**Correlation Penalty:**
- If corr(A, B) > 0.70, reduce allocation to lower-scoring strategy
- Penalty = (correlation - 0.70)
- Example: 0.85 correlation → 15% weight reduction

**Insufficient Data:**
- Strategies with < 10 trades excluded
- Promotes after meeting validation criteria

---

## Optimal Weight Calculation

**Step 1: Initial Weights** (risk-score proportional)
```
Weight_i = RiskScore_i / Σ(RiskScore)
```

**Step 2: Correlation Adjustment**
```
For each pair (A, B) where corr > 0.70:
  Penalize lower-scoring strategy
  Adjusted_Weight = Weight * (1 - penalty)
```

**Step 3: Normalize**
```
Weight_i = Adjusted_Weight_i / Σ(Adjusted_Weight)
```

**Step 4: Apply Constraints**
```
If Weight < min_weight: exclude
If Weight > max_weight: cap at max_weight
Renormalize after constraints
```

**Example:**

| Strategy | Risk Score | Initial Weight | Correlation Penalty | Final Weight | Capital ($97.80, 50% max) |
|----------|------------|----------------|---------------------|--------------|---------------------------|
| A | 85 | 42.5% | None | 45% | $22.00 |
| B | 75 | 37.5% | None | 40% | $19.56 |
| C | 40 | 20.0% | Corr with A (0.80) | 15% | $7.33 |

**Total Allocated:** $48.89 (50%)  
**Cash Reserve:** $48.91 (50%)

---

## Correlation Matrix

**How It's Calculated:**
- Pearson correlation on P&L time series
- Minimum 10 trades required per strategy
- Pairwise correlation for all eligible strategies

**Interpretation:**
- `corr > 0.70`: Highly correlated (penalty applied)
- `corr 0.30-0.70`: Moderate correlation
- `corr < 0.30`: Low correlation (good diversification)

**Use:**
- Reduces allocation to correlated strategies
- Promotes diversification
- Prevents redundant exposure

---

## Capital Allocation

**Total Capital:** $97.80 (current account balance)

**Max Exposure:** $48.90 (50% of capital)

**Per-Strategy Allocation:**
```
Capital_i = Max_Exposure * Weight_i
```

**Example:**
- Strategy A (45% weight): $48.90 * 0.45 = $22.00
- Strategy B (40% weight): $48.90 * 0.40 = $19.56
- Strategy C (15% weight): $48.90 * 0.15 = $7.34

**Cash Reserve:** $48.90 (50%)

---

## Portfolio Metrics

**Portfolio Sharpe Ratio:**
```
Portfolio_Sharpe = Σ(Sharpe_i * Weight_i)
```
Weighted average of individual Sharpe ratios

**Portfolio Expectancy:**
```
Portfolio_Expectancy = Σ(Expectancy_i * Weight_i)
```
Expected P&L per trade across portfolio

**Diversification Ratio:**
```
Diversification = 1 / max(Weight_i)
```
- Higher = better diversification
- 5.0 = perfectly equal weights (5 strategies @ 20% each)
- 1.0 = single strategy (100%)

---

## Rebalancing

**Trigger:** Portfolio weights drift > 10% from target

**Causes of drift:**
- Strategy performance changes
- New trades alter risk metrics
- Correlation changes
- Promotion/demotion events

**Action:**
- Recalculate optimal weights
- Adjust position sizes
- Log rebalancing event

**Frequency:** Every 4 hours (or when triggered)

---

## Risk Management

**Portfolio-Level Circuit Breakers:**

1. **Max Drawdown Exceeded**
   - If portfolio DD > 15%, halt all trading
   - Supervisor flags for human review
   - Requires manual restart

2. **Correlation Spike**
   - If multiple strategies become correlated (avg corr > 0.70)
   - Reduce exposure to correlated strategies
   - Increase cash reserve

3. **Single Strategy Dominance**
   - If one strategy > 20% of portfolio
   - Cap at 20%, reallocate excess

4. **Insufficient Diversification**
   - If num_strategies < 3, reduce total exposure to 30%
   - Promote diversification

---

## Files & Logs

**Configuration:**
- `logs/portfolio-allocation.json` — Current allocation state
- Updated every 4 hours

**History:**
- `logs/allocation-history.jsonl` — Append-only history
- Every allocation logged with timestamp

**Report:**
- `PORTFOLIO_ALLOCATION_REPORT.md` — Human-readable summary
- Strategy allocations, portfolio metrics, risk limits

**Script:**
- `scripts/portfolio-allocator.py` — Allocation engine

---

## Integration with Governance

**Lifecycle Interaction:**

| Strategy Stage | Capital Allocation |
|----------------|-------------------|
| VALIDATE | None (paper trading only) |
| QUARANTINE | None (monitoring) |
| PROMOTE | Eligible (awaiting human approval) |
| FUTURE_ONLY | Theoretical only; not an implemented execution stage |
| DEMOTE | None (failed) |

**Note:** allocation outputs are research metadata for paper trading; they do not unlock live execution in this repository.

---

## Example Allocation Report

```markdown
# PORTFOLIO ALLOCATION REPORT

## Portfolio Summary
- Total Capital: $97.80
- Allocated Capital: $48.90 (50%)
- Cash Reserve: $48.90 (50%)
- Portfolio Sharpe: 1.85
- Portfolio Expectancy: $0.72 per trade
- Active Strategies: 3
- Diversification Ratio: 2.22

## Strategy Allocations

### funding_arbitrage
**Stage:** FUTURE_ONLY (theoretical, not implemented)
**Allocation:** $22.00 (45%)
**Risk Score:** 85.2/100

**Performance Metrics:**
- Trades: 38
- Win Rate: 68.4%
- Profit Factor: 2.4
- Sharpe Ratio: 2.1
- Expectancy: $0.85
- Max Drawdown: 7.2%
- Total P&L: $32.30

### momentum_breakout
**Stage:** PROMOTE
**Allocation:** $19.56 (40%)
**Risk Score:** 78.5/100

**Performance Metrics:**
- Trades: 32
- Win Rate: 62.5%
- Profit Factor: 2.0
- Sharpe Ratio: 1.8
- Expectancy: $0.65
- Max Drawdown: 9.8%
- Total P&L: $20.80

### mean_reversion
**Stage:** FUTURE_ONLY (theoretical, not implemented)
**Allocation:** $7.34 (15%)
**Risk Score:** 65.3/100

**Performance Metrics:**
- Trades: 28
- Win Rate: 60.7%
- Profit Factor: 1.7
- Sharpe Ratio: 1.5
- Expectancy: $0.55
- Max Drawdown: 11.2%
- Total P&L: $15.40
```

---

## Schedule

**Every 4 hours:**
```
XX:00 → Trading Agency (scan + trade)
XX:15 → Governance Supervisor (evaluate + decide)
XX:30 → Portfolio Allocator (assign capital)
```

**Next Allocation:** 22:30 EDT

---

## Benefits

1. **Risk-Adjusted Returns**
   - Capital flows to highest-quality strategies
   - Multi-metric scoring (not just P&L)

2. **Diversification**
   - Correlation-adjusted weights
   - Reduced redundant exposure

3. **Capital Preservation**
   - 50% cash reserve
   - Max 20% per strategy
   - Circuit breakers

4. **Dynamic Rebalancing**
   - Adapts to performance changes
   - Continuous optimization

5. **Transparent**
   - Full audit trail
   - Clear allocation logic
   - Human-readable reports

---

*Allocation system operational. Integrated with three-stage governance model.*
