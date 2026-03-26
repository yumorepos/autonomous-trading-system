# Autonomous Trading System — Case Study

> A paper-trading research platform with autonomous execution, multi-layer safety, and truth-first architecture.

## Overview

I built an autonomous trading system that runs unattended — scanning markets, evaluating signals through safety gates, executing paper trades, and persisting all state to append-only logs. The system enforces correctness at every layer: schema contracts validate every trade record, circuit breakers halt execution on anomalies, and a canonical data layer prevents state drift.

**Stack:** Python 3.12 · Hyperliquid API · Polymarket CLOB · launchd scheduling · JSONL append-only logs · 25 test suites

**Status:** Paper trading. No real capital at risk.

---

## System Architecture

```
┌─────────────────────────────────────────────────┐
│                    SCHEDULER                     │
│            (launchd, 4-hour cycles)              │
└─────────────┬───────────────────────────────────┘
              ▼
┌─────────────────────────────────────────────────┐
│              SIGNAL SCANNER                      │
│   Funding rates · Volume · OI · EV scoring       │
└─────────────┬───────────────────────────────────┘
              ▼
┌─────────────────────────────────────────────────┐
│           DATA INTEGRITY LAYER                   │
│   Schema validation · State recovery · Dedup     │
└─────────────┬───────────────────────────────────┘
              ▼
┌─────────────────────────────────────────────────┐
│           EXECUTION SAFETY LAYER                 │
│   10 safety gates · Circuit breakers · Limits    │
└─────────────┬───────────────────────────────────┘
              ▼
┌─────────────────────────────────────────────────┐
│              PAPER TRADER                        │
│   Entry · Exit (TP/SL/timeout) · Position mgmt   │
└─────────────┬───────────────────────────────────┘
              ▼
┌─────────────────────────────────────────────────┐
│          CANONICAL PERSISTENCE                   │
│   JSONL trade log · Position state · Account     │
└─────────────┬───────────────────────────────────┘
              ▼
┌─────────────────────────────────────────────────┐
│         PERFORMANCE ANALYTICS                    │
│   Win rate · PnL · Equity curve · Reporting      │
└─────────────────────────────────────────────────┘
```

---

## Execution Pipeline

Every cycle follows a deterministic path:

1. **Scanner** queries Hyperliquid for funding rates, volume, and open interest across all perpetual markets
2. **Signal scoring** computes expected value (EV) from funding rate × volume × OI, with time-decay
3. **Data integrity layer** validates position state, recovers from crashes, prevents duplicate entries
4. **Safety layer** runs 10 independent checks:
   - Signal freshness (max 5 min age)
   - Position size limits ($1.96 per trade)
   - Concurrent position cap (max 5)
   - Circuit breaker (3 consecutive losses → halt)
   - Daily/hourly loss limits
   - Drawdown protection (20% max from peak)
   - Cooldown between trades
   - Duplicate entry prevention
   - Exchange connectivity verification
   - Capital adequacy check
5. **Paper trader** executes at current market prices, sets take-profit (2%) and stop-loss (-2%) levels
6. **Exit evaluator** checks TP/SL/timeout every cycle, closes positions that hit thresholds
7. **Persistence** writes every action to append-only JSONL — no mutations, no deletions

---

## Safety Design

The system assumes it will fail and is designed to survive failures:

### Circuit Breakers
- 3 consecutive losses → automatic halt
- $3/hour loss limit → pause 1 hour
- $10/day loss limit → pause 24 hours
- 20% drawdown from peak → full stop

### Schema Contracts
Every trade record is validated against a canonical schema before persistence:
- 14 required fields for closed trades (trade_id, exchange, symbol, side, entry_price, exit_price, position_size, position_size_usd, realized_pnl_usd, realized_pnl_pct, status, exit_reason, entry_timestamp, exit_timestamp)
- Normalization layer handles legacy formats automatically
- Invalid records are rejected with warnings, never silently accepted

### State Recovery
If `position-state.json` is corrupted or missing:
- System rebuilds authoritative state from append-only trade history
- Prevents duplicate entries after restart
- Handles malformed JSONL lines gracefully

---

## Real Results

**Paper trading period:** March 26, 2026 (single day)

| Metric | Value |
|---|---|
| Total trades | 7 |
| Win rate | 57.1% (4W / 3L) |
| Total PnL | +$0.97 |
| Expectancy | +$0.14/trade |
| Avg position | $1.96 |
| Avg duration | 82 min |
| Max drawdown | 0.03% |
| Starting balance | $97.80 |
| Ending balance | $98.77 |

### Exit Breakdown
- Take profit (2%): 2 trades
- Timeout (1.5h): 5 trades

### Equity Curve (cumulative balance)

| Trade | Symbol | PnL | Balance |
|---|---|---|---|
| 0 | — | — | $97.80 |
| 1 | PROVE | +$0.49 | $98.29 |
| 2 | SUPER | +$0.49 | $98.78 |
| 3 | PROVE | +$0.02 | $98.80 |
| 4 | SUPER | -$0.01 | $98.79 |
| 5 | REZ | -$0.01 | $98.78 |
| 6 | TRUMP | -$0.01 | $98.76 |
| 7 | STABLE | +$0.00 | $98.77 |

---

## Limitations (Explicit)

1. **Paper trading only** — no real capital deployed, no slippage, no market impact
2. **7 trades** — far below the ~30+ minimum needed for any statistical confidence
3. **Single strategy** — funding rate arbitrage only; no diversification
4. **Single day** — no regime changes, no volatility shifts, no black swan testing
5. **No transaction costs** — real trading includes exchange fees (0.02-0.05%), spread, and slippage
6. **Tiny position sizes** — $1.96 per trade; results may not scale to larger sizes
7. **No proven edge** — positive PnL does not imply a sustainable strategy

---

## What I'd Improve Next

1. **Run 100+ paper trades** across multiple market conditions before considering live capital
2. **Add backtesting framework** to validate signals against historical data
3. **Implement slippage modeling** to simulate realistic execution costs
4. **Multi-strategy support** — test mean reversion, momentum, and cross-exchange arbitrage
5. **Alerting system** — push notifications on circuit breaker triggers or anomalies
6. **Dashboard** — real-time web interface for monitoring positions and performance

---

## Technical Highlights (for engineers)

- **Append-only architecture**: All state changes logged to JSONL. Position state is derived, never authoritative.
- **Dynamic runtime resolution**: Config paths resolve at call time, not import time — enabling full test isolation without mocks.
- **25 test suites** covering schema contracts, state recovery, negative paths, and regression guards.
- **Offline-capable**: Full test suite runs without network access using fixture-based request patching.
- **Multi-exchange normalization**: Hyperliquid and Polymarket signals normalized to a single canonical schema.

---

*Source: [github.com/yumorepos/autonomous-trading-system](https://github.com/yumorepos/autonomous-trading-system)*
