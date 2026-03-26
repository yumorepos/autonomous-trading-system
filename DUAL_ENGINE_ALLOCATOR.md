# DUAL-ENGINE AUTONOMOUS CAPITAL ALLOCATOR

> Established: 2026-03-26
> Objective: Double $140 → $280 in 30 days with strict risk controls

## Capital Allocation

| Engine | Current | Max | Status | Edge Type |
|---|---|---|---|---|
| **Hyperliquid** | $97.14 | $97 | ✅ ACTIVE | Funding arbitrage (negative funding = longs earn) |
| **Polymarket** | $43.17 | $43 | ⏸️ STANDBY | Convergence + spread capture |
| **Total** | **$140.31** | **$140** | | |

## Allocation Rules

1. **Hyperliquid is primary.** It has proven funding arb edge. Capital flows here first.
2. **Polymarket is opportunistic.** Only deploy when edge > HL opportunity cost.
3. **Never split capital without strict EV comparison.** If PM opportunity yields <0.5%/day and HL has A+ signal, reject PM.

## Autonomous Operation Schedule

| Task | Frequency | Tool |
|---|---|---|
| Scan HL for A+ signals | Every 30 min | launchd → `ats-cycle.sh` |
| Evaluate open positions | Every 30 min | `risk-guardian.py` |
| Check PM for triggers | Every 4 hours | Manual until automated |
| Rebalance capital | Daily 00:00 UTC | Not yet implemented |
| System audit | Daily 06:00 UTC | Not yet implemented |

## A+ Signal Standard (Hyperliquid)

ALL must be true:
- Signal score ≥ 6.0
- Funding rate ≥ 200% annualized (for longs: funding must be negative)
- Volume ≥ $1M / 24h
- Premium < -1% (perp below oracle = bullish)
- No conflicting momentum (last 3 hourly candles not all red)

## Polymarket Triggers (Standby → Active)

ANY triggers deployment:
- Fillable spread > $0.05 on mid-range market ($0.30-$0.70)
- Near-expiry convergence: YES >$0.95, <24h to expiry, buy <$0.97 (3%+ return)
- Volume spike: 10x normal on a single market
- Flash crash: >15% drop in <1h with no fundamental news

## Position Management (HL)

- **Size per trade:** $15 (15% of capital)
- **Max concurrent:** 2 positions
- **Max exposure:** $40 (41% of capital)
- **Entry cooldown:** 45 min between entries

## Exit Rules (Guardian-Enforced)

- **Stop-loss:** -10% ROE → market close
- **Take-profit:** +15% ROE → market close
- **Trailing stop:** Activates at +2% ROE, trails 2% behind peak
- **Timeout:** 12h max hold
- **Thesis degradation:** If funding decays >40% from entry AND ROE < 0 → exit immediately

## Circuit Breakers

| Trigger | Action | Duration |
|---|---|---|
| 5 consecutive losses | HALT ALL TRADING | 24h |
| $10 loss in one day | HALT ALL TRADING | 24h |
| $3 loss in one hour | HALT ALL TRADING | 1h |
| Total capital < $80 | **FULL STOP** | Manual review required |
| 20% drawdown from peak | **FULL STOP** | Manual review required |

## Compounding Target

- **Start:** $140.31 (2026-03-26)
- **Target:** $280 (double in 30 days)
- **Required daily return:** 2.34% compounded
- **Strategy:** A+ signals only + strict risk management
- **Realistic?** Aggressive. Require 18-20 winning trades at +15% each with <5 losses at -10%.

## Capital Rebalancing Protocol (Not Yet Implemented)

Daily at 00:00 UTC:
1. Calculate HL 7-day EV (avg funding income × probability of A+ signals)
2. Calculate PM 7-day EV (recent trigger frequency × avg profit)
3. If PM EV > HL EV by >20% → reallocate $20 from HL to PM
4. If HL has A+ signal waiting → keep all capital on HL
5. Never rebalance if either engine has open positions

## System Self-Audit (Not Yet Implemented)

Daily at 06:00 UTC:
1. Verify launchd is running (no missed scans)
2. Check for stale state files (position-state.json, entry-thesis.json)
3. Validate log integrity (no gaps in hl-entry.jsonl, risk-guardian.jsonl)
4. Measure execution quality (fill price vs mid, slippage)
5. Check for drift (are A+ thresholds still appropriate?)
6. Append findings to `workspace/logs/system-audit.jsonl`

## Autonomous Execution Checklist

- [x] CEO Doctrine established (capital preservation first)
- [x] A+ signal standard enforced in entry module
- [x] Thesis degradation exit in guardian
- [x] Launchd scheduling active (30 min cycles)
- [x] Polymarket standby mode configured
- [ ] PM trigger scanner (need to automate)
- [ ] Capital rebalancing cron
- [ ] Daily system audit cron
- [ ] Slack/Telegram alerts on circuit breaker hits
- [ ] Weekly performance report generator

## Learning Log

| Date | Event | Lesson | Action Taken |
|---|---|---|---|
| 2026-03-26 | SUPER LONG -5.87% | Funding can decay during hold. Exit on thesis degradation. | Added guardian check: if funding decays >40% + ROE<0 → exit |
| 2026-03-26 | Polymarket scan | Orderbook spreads are 90%+, but /price endpoint shows tight fills (0.1-2%). Always check real fill prices. | Standby until triggers fire |
