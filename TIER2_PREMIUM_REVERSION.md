# TIER 2 SIGNAL: Premium Reversion

> Secondary signal to complement funding arbitrage (Tier 1)
> Target: 1-2 trades/day, 3-5% daily return

## The Edge

**Premium = (Perp Price - Oracle Price) / Oracle Price**

When premium is **significantly negative** (perp trading below oracle):
- Arbitrageurs can buy perp, short spot → profit from convergence
- Market makers rebalance → upward pressure on perp
- Funding rate often turns negative → longs get paid
- Mean reversion pressure is strong

**Expected behavior:** Perp price converges toward oracle within 1-8 hours.

## Entry Conditions (ALL must be true)

1. **Premium < -2.5%** (perp significantly below oracle)
2. **Volume > $500k / 24h** (enough liquidity, lower than Tier 1)
3. **Funding rate < 0** (shorts paying longs — supportive but not required to be strong)
4. **No conflicting momentum** (not in a strong downtrend — last 3 hourly candles not all red)
5. **Position size: $10** (smaller than Tier 1 due to lower confidence)

## Exit Logic

**Take Profit:** +5% ROE (premium reverts halfway)  
**Stop Loss:** -8% ROE (premium continues to widen — exit before -10%)  
**Trailing Stop:** Activates at +3% ROE, trails 2% behind peak  
**Timeout:** 12 hours max hold  
**Premium convergence exit:** If premium reverts to > -0.5%, exit at market (edge is gone)

## Expected Performance

| Metric | Value |
|---|---|
| Win rate | 55-65% (lower than Tier 1) |
| Avg win | +5% |
| Avg loss | -8% |
| Expectancy | ~1.5% per trade |
| Hold time | 2-8 hours |
| Trigger rate | 3-5% of scans |
| Trades/day | 1-2 |

## Risk Parameters

- **Max concurrent Tier 2 positions:** 1
- **Max Tier 2 capital deployed:** $10 (10% of total)
- **Cooldown between Tier 2 entries:** 2 hours
- **Circuit breaker:** 3 consecutive Tier 2 losses → pause Tier 2 for 24h

## Quality Gates (Prevent Bad Trades)

- Premium must be verified from BOTH perp orderbook AND oracle feed
- Asset must have active market making (check bid-ask spread < 2%)
- No entry within 1 hour of major news/events (if detectable)
- Skip if asset has <3 days of price history

## Example Trade

**Entry:**
- Asset: DOGE
- Premium: -3.2% (perp $0.145, oracle $0.150)
- Funding: -0.08% per 8h (-87% annual)
- Volume: $2.1M / 24h
- Action: BUY 68.9 DOGE @ $0.145 = $10 notional (3x leverage)

**Exit (TP scenario):**
- Premium reverts to -1.0% (perp $0.148)
- ROE: +6.2%
- PnL: +$0.62
- Hold time: 4.2 hours

**Exit (SL scenario):**
- Premium widens to -4.5% (perp $0.143)
- ROE: -8.3%
- PnL: -$0.83
- Hold time: 2.1 hours

## Integration with Tier 1 (Funding)

**Independent signals:** Can run in parallel  
**No conflict:** Premium reversion is short-term (hours), funding is 8h+ holds  
**Capital separation:** Tier 1 uses $15, Tier 2 uses $10, never overlap on same asset  
**Total max exposure:** $40 (2x Tier 1 @ $15 each + 1x Tier 2 @ $10)

## Implementation Priority

1. Add premium calculation to scanner
2. Add Tier 2 entry gate to `hl_entry.py`
3. Add premium convergence exit to guardian
4. Test on 1 trade, then enable autonomous mode
