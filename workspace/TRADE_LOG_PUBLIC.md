# Trade Log — Public (Redacted)

This is the public-facing trade log. Private evidence is stored in `workspace/logs/`.

---

## Trade #1 — PROVE (Long) 2026-03-25
- **Entry:** 0.29217
- **Exit:** 0.28271
- **Result:** LOSS -$0.48 (-9.7% ROE)
- **Exit reason:** Thesis invalidated early
- **Signals:** 1/3 confirmed (funding only)
- **Protocol compliant:** Yes
- **Scaling eligible:** Yes
- **Diagnosis:** Funding direction misread + price move against entry → both legs wrong. **Fixed:** Gate #11 prevents paying funding on funding arbitrage trades.

---

## Trade #2 — PENDING

**System is currently scanning. Next potential trade must:**

1. Pass multi-factor composite score ≥ 6.0
2. Have ≥ 2/3 confirmations
3. Satisfy all 11 safety gates
4. Generate pre-trade decision packet
5. Respect canary limits ($12 max position, 1 concurrent, 2/day max, $3 daily loss cap)

**Trade 2–20 are canary trades.** No scaling until all gates pass.

---

## Canary Protocol Status

| Metric | Value |
|---|---|
| Trades completed | 1/20 |
| Expectancy needed | > 0.5% per $1 risked |
| Current expectancy | -3.3% |
| Profit factor needed | > 1.2 |
| Current profit factor | 0.0 |
| Max drawdown allowed | 15% of capital |
| Current drawdown | $0.48 (0.5%) ✅ |
| Consecutive losses | 1/3 |
| Daily loss cap | $3 |
| System mode | SCANNING (every 4h) |

---

## System Updates

**2026-03-25: Multi-factor signal engine deployed**
- Funding + momentum + volume composite scoring
- Minimum 2/3 confirmation required
- Funding direction gate prevents paying funding (Gate #11)

**2026-03-25: Canary trading protocol established**
- 20-trade discovery phase with strict limits
- Pre-trade decision packets required
- Scaling gates (20 trades, +expectancy, profit factor >1.2, zero violations)

**2026-03-25: Full security audit completed**
- Wallet addresses removed from entire git history
- Execution logs removed from tracking
- .gitignore prevents future leaks
- utils/redact.py for safe public logging

---

## Signal Flow Analysis (Last Scan)

| Step | Pass | Filtered |
|---|---|---|
| Total assets scanned | 229 | — |
| Funding > 30% ann. | 3 | 226 |
| Momentum aligned | 2 | 1 |
| Volume > $300k | 2 | 0 |
| 2/3 confirmations | 2 | 0 |
| Composite score ≥ 6.0 | **1** | 1 |

**Near-miss candidates:**
- **SUPER:** Score 6.0 (funding -285% ann., momentum +17.5%)
- **PROVE:** Score 5.3 (funding -145% ann., momentum +15.8%)
- **GAS:** Score 1.0 (only funding active, momentum -5.9%)

---

## Next Signal Scan

Scheduled every 4 hours by launchd agent. System is **execution ready** but selective: only 1 in 229 assets passed all gates in the last scan.
