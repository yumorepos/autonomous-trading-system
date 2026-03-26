# CEO DOCTRINE — Permanent Capital Allocation Rules

> Last updated: 2026-03-26
> Enforced by: ATS guardian, entry module, and all future code

## Prime Directive
**Capital preservation first. Profit second. Always.**

$97 is the entire bankroll. Every dollar lost is 1% of everything. Act accordingly.

## A Signal Standard (Relaxed 2026-03-26 for Throughput)
Only enter trades that meet ALL of these criteria:
1. **Composite signal score ≥ 6.0** (multi-factor: funding + momentum + volume)
2. **Funding rate > 150% annualized** (was 200% — relaxed for trade frequency, still strong edge)
3. **Volume > $1M / 24h** (enough liquidity to exit cleanly)
4. **Premium < -1%** (perp price below oracle = bullish reversion pressure)
5. **No conflicting momentum** (last 3 hourly candles not all red)

**Rationale:** 200% funding yielded 0 trades/day. 150% captures markets like PROVE (181% funding) while maintaining quality. Expected signal rate: ~1-2%/scan → 0.5-1 trade/day → 2-5% daily return.

If ANY criterion fails → NO TRADE. Wait for the next cycle.

## Opportunity Cost Gate
Before every entry, calculate:
- **Funding income per 8h** on the candidate position
- **Compare to: capital sitting in spot earning 0%**
- **If funding income < $0.03/8h on a $15 position → skip.** The edge isn't worth the risk.

## Position Management
- **Size:** $15 per trade (15% of capital)
- **Max concurrent:** 2 positions
- **Max exposure:** $40 (41% of capital)
- **Entry cooldown:** 45 minutes between entries

## Exit Rules (Guardian-enforced)
- **Stop-loss:** -10% ROE → immediate market close
- **Take-profit:** +15% ROE → immediate market close
- **Trailing stop:** Activates at +2% ROE, trails 2% behind peak
- **Timeout:** 12 hours max hold
- **Thesis degradation exit:** If funding rate decays >40% from entry level AND ROE is negative → EXIT. Don't wait for SL.

## Thesis Degradation Rule (LEARNED 2026-03-26)
The SUPER trade taught us: **funding can decay while you hold.** Entry funding was -300% annual, but it dropped to -180% within hours. The edge was 40% weaker than expected. 

**Rule:** Every guardian cycle must check if current funding is still >60% of entry funding. If not, and ROE < 0%, exit immediately regardless of SL distance.

## Polymarket Rules
- **Standby until trigger fires:**
  - Fillable spread > $0.05 on mid-range market
  - Near-expiry convergence > 3% return in < 24h
  - Volume spike > 10x normal
  - Flash crash > 15% in < 1h
- **Never market-take on Polymarket.** Limit orders only.
- **$43 sits parked.** No opportunity cost — it's on a different chain.

## Circuit Breakers
- 5 consecutive losses → halt all trading 24h
- $10/day loss → halt 24h  
- $3/hour loss → halt 1h
- Total capital < $80 → FULL STOP. Re-evaluate everything.
- 20% drawdown from peak → FULL STOP.

## What We Will NOT Do
- Trade without A+ signal
- Hold a degrading position hoping for recovery
- Split capital across exchanges without proven edge on both
- Override circuit breakers
- Chase losses with larger positions
- Trade based on opinion, hype, or prediction

## Learning Log
| Date | Trade | Result | Lesson |
|---|---|---|---|
| 2026-03-26 | SUPER LONG | -$0.29 (-5.87% ROE) | Funding decayed 40% during hold. Exit on thesis degradation, don't wait for SL. |
