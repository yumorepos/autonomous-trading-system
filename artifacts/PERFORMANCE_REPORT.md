# Paper Trading Performance Report

> Generated: 2026-03-26T21:23:51 UTC
> Data source: `phase1-paper-trades.jsonl`
> **⚠️ Paper trading only. Sample size too small for statistical significance.**

## Summary

| Metric | Value |
|---|---|
| Total trades | 7 |
| Wins / Losses | 4 / 3 |
| Win rate | 57.1% |
| Total PnL | $+0.9664 |
| Avg PnL per trade | $+0.1381 |
| Avg win | $+0.2502 |
| Avg loss | $-0.0114 |
| Profit factor | 29.28 |
| Max drawdown | 0.0346% |
| Starting balance | $97.80 |
| Ending balance | $98.77 |

## Duration

| Metric | Value |
|---|---|
| Avg duration | 72.2 min |
| Shortest | 3.7 min |
| Longest | 105.6 min |

## Exit Reasons

| Reason | Count |
|---|---|
| take_profit | 2 |
| timeout | 5 |

## Trade Log

| # | Symbol | Side | Size | PnL | PnL% | Exit | Duration |
|---|---|---|---|---|---|---|---|
| 1 | PROVE | LONG | $1.96 | $+0.4900 | +25.00% | take_profit | 9.2m |
| 2 | SUPER | LONG | $1.96 | $+0.4900 | +25.00% | take_profit | 3.7m |
| 3 | PROVE | LONG | $1.96 | $+0.0171 | +0.87% | timeout | 105.6m |
| 4 | SUPER | LONG | $1.96 | $-0.0109 | -0.56% | timeout | 103.2m |
| 5 | REZ | LONG | $1.96 | $-0.0112 | -0.57% | timeout | 101.5m |
| 6 | TRUMP | LONG | $1.96 | $-0.0120 | -0.61% | timeout | 91.2m |
| 7 | STABLE | LONG | $1.96 | $+0.0035 | +0.18% | timeout | 90.7m |

## Equity Curve

| Trade | Symbol | PnL | Balance |
|---|---|---|---|
| 0 | — | — | $97.80 |
| 1 | PROVE | $+0.4900 | $98.2900 |
| 2 | SUPER | $+0.4900 | $98.7800 |
| 3 | PROVE | $+0.0171 | $98.7971 |
| 4 | SUPER | $-0.0109 | $98.7862 |
| 5 | REZ | $-0.0112 | $98.7750 |
| 6 | TRUMP | $-0.0120 | $98.7629 |
| 7 | STABLE | $+0.0035 | $98.7664 |

## Limitations

- **Paper trading only** — no real capital at risk, no slippage, no market impact
- **Sample size: 7 trades** — far too small for statistical significance
- **Single strategy** — funding arbitrage only, no diversification tested
- **Single day of data** — no regime change or volatility shift testing
- **No transaction costs** — real trading would include fees, spread, and slippage

## What This Proves

- End-to-end execution pipeline works: signal → safety gates → entry → exit → logging
- Schema contracts enforced: all trades have required fields, pass validation
- Safety systems active: circuit breakers, position limits, timeout enforcement
- Canonical data persistence: all trades logged to append-only JSONL
