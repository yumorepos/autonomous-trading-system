# CEO MEMO — Capital Strategy
**Date:** 2026-03-26  
**Bankroll:** $102.01  
**Status:** Early-stage execution system, no proven edge

---

## 1. CEO Reality Check

### What IS proven:
- Hyperliquid execution: 2 orders filled on mainnet ✅
- Polymarket execution: 1 order placed + cancelled ✅
- Guardian protection: running autonomously every 4h ✅
- Entry module: signal scan + 10 safety gates + live fill ✅
- Infrastructure: 77 tests, audit logs, circuit breaker ✅

### What is NOT proven:
- **The trading strategy has positive expected value.** Zero evidence of edge.
- Funding rate arbitrage thesis is not validated. PROVE is -8.8% ROE and we're paying funding, not earning it.
- Signal scoring has no backtest. Score 5.0 threshold was set arbitrarily.
- Win rate: 0 wins, 1 open loss. Sample size: 1.
- No risk-adjusted return data exists.

### Biggest risks right now:
1. **PROVE position is thesis-broken.** We entered on negative funding (expecting to earn). We're paying funding AND losing on price. Both legs of the thesis are wrong.
2. **$102 bankroll has zero margin for error.** One bad streak of 3 losses at $15 each = 44% drawdown.
3. **System optimized for execution, not for edge.** We built a great car but don't know where the road goes.
4. **Emotional pressure to "make it work"** after losing $38.65 to wrong address.

---

## 2. Capital Preservation Policy

| Rule | Value | Rationale |
|---|---|---|
| Max single position | **$12** | 12% of bankroll. Survivable loss. |
| Max concurrent positions | **2** | Across both exchanges combined |
| Max total deployed | **$25** (25%) | Keep 75% in cash always |
| Daily loss limit | **$5** | 5% of bankroll. Halt all trading for 24h if hit. |
| Weekly loss limit | **$10** | 10%. Halt for 72h and review. |
| Account kill switch | **$80 total value** | If bankroll drops below $80, STOP. Full review before any trade. |
| Circuit breaker | **3 consecutive losses** (tightened from 5) | At this capital size, 5 losses is catastrophic. |

**Immediate action required:** Tighten circuit breaker from 5 to 3 losses.

---

## 3. Strategy Decisions

### PROVE position: CLOSE IMMEDIATELY.

**Reasoning:**
- Entry thesis: negative funding = we earn funding by going long. **Reality: we're paying $0.016 in funding, not earning.**
- Price thesis: funding anomaly reversal. **Reality: price dropped 8.8%, no reversal signal.**
- Both legs of the thesis are broken. This is not a position to "hope" on.
- Current loss: $0.44. If we wait for -15% stop-loss: $0.73 loss. Difference: $0.29 more risk for a broken thesis.
- **CEO decision: cut it now. A broken thesis is not worth holding.**

### Hyperliquid: SOLE FOCUS.

**Reasoning:**
- $102 is too small to split across exchanges.
- Hyperliquid has deeper liquidity, more assets, better infrastructure built.
- Polymarket USDC balance is tiny and depositing more means splitting scarce capital.
- **Polymarket stays in verification-only mode. No capital deployed until HL proves the edge.**

### Polymarket: VERIFICATION ONLY.

- Execution is proven. Good.
- No capital deployed. No trades.
- Revisit only after 20+ HL trades prove positive edge.

---

## 4. Edge Discovery Framework

### What must be logged for every trade:
```
- entry_timestamp
- exit_timestamp
- asset
- direction
- signal_score
- signal_type
- entry_price
- exit_price
- position_size_usd
- realized_pnl_usd
- realized_pnl_pct
- hold_duration_hours
- funding_earned_usd
- exit_reason (SL / TP / timeout / manual / thesis_broken)
- thesis_correct (yes / no / partial)
```

### Minimum sample before scaling:
- **20 completed trades** minimum.
- **Positive expectancy** over those 20: avg_win × win_rate > avg_loss × loss_rate.
- **No scaling until this is proven.** Period.

### Success thresholds to justify increasing size:
- Win rate > 50% over 20+ trades
- Average winner > average loser (reward:risk > 1.0)
- Max drawdown < 15% of bankroll during the sample
- Sharpe proxy > 0.5 (avg daily return / std dev of daily returns)

### Patterns that invalidate the strategy:
- Win rate < 35% after 15 trades → **stop and redesign**
- 3 consecutive thesis-broken entries → **signal scoring is broken, halt and fix**
- Funding collected < funding paid across all trades → **funding arb thesis is dead**
- Average hold time > 48h with no edge → **timeout too loose, signals too weak**

---

## 5. Operating Plan

### Every 4h (automated):
- Guardian evaluates all positions
- Entry module scans for signals
- Logs written to JSONL
- **No human action needed**

### Daily (manual, 5 min):
- Check `RISK_GUARDIAN_REPORT.md` — any alerts?
- Check `workspace/logs/hl-entry.jsonl` — any new entries?
- Check total account value — above $80 kill switch?
- **Decision:** any thesis-broken positions to cut?

### After every closed trade (manual, 10 min):
- Log the full trade record (see metrics above)
- Was the thesis correct?
- Was the exit timely or late?
- What would I change?

### Weekly (Sunday, 20 min):
- Total P&L this week
- Win/loss count
- Average winner vs average loser
- Funding earned vs paid
- Signal score distribution of winners vs losers
- **Decision:** continue / adjust thresholds / pause?

---

## 6. Hard "Do Not Do" List

1. **Do not revenge trade.** After a loss, the next entry must pass the same 10 gates. No exceptions.
2. **Do not increase size before 20 trades.** $12 max. Even if you "feel confident."
3. **Do not deploy to Polymarket yet.** Capital concentration > diversification at $102.
4. **Do not hold a thesis-broken position.** If the reason you entered is wrong, exit. Don't wait for stop-loss.
5. **Do not override the circuit breaker.** If it halts, you stop. Review first.
6. **Do not chase volatile assets.** Low-liquidity tokens (like PROVE) have gap risk. Prefer top-20 assets.
7. **Do not trade during high-impact news.** Funding rates spike artificially. Let them settle.
8. **Do not add to losers.** No averaging down. Ever. At any size.
9. **Do not manual trade outside the system.** Every trade goes through the entry module with logged gates.
10. **Do not check P&L more than twice a day.** Emotional decisions destroy small accounts.

---

## 7. CEO Verdict

**The system is execution-ready but strategy-immature.** 

We built a F1 car and drove it once on a track we don't know. The car works — proven. But we have zero evidence the route is profitable. The single trade (PROVE) is thesis-broken and losing.

**Priority is survival + data collection, not profit.** 

At $102, the goal is to complete 20 small trades, collect data on whether funding rate anomalies produce positive expectancy, and only then decide whether to scale.

---

## Next 3 Actions

### 1. IMMEDIATE: Close PROVE position.
Thesis broken (paying funding + price declining). Don't wait for -15% SL. Take the ~$0.45 loss now.
```
python3 scripts/hl_executor.py close PROVE
```

### 2. TODAY: Tighten system parameters.
- Circuit breaker: 5 → 3 consecutive losses
- Max position: $15 → $12
- Add min volume filter: $500k daily (PROVE was $4M but still gapped)
- Prefer top-50 assets by open interest

### 3. THIS WEEK: Run 3-5 small trades, log everything.
- $10-12 each, funding anomaly signals only
- Full post-trade review after each
- After 5 trades: first edge assessment
- After 20 trades: scaling decision
