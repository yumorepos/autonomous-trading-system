> **Status: ACCURATE** — verified against current codebase.

# Edge Validation Report

Generated: 2026-04-10 21:25 UTC
Period: 180 days | Initial capital: $95

## Strategy Parameters (from config/risk_params.py)

| Parameter | Value |
|-----------|-------|
| Stop Loss | -15% ROE |
| Take Profit | 13% ROE |
| Timeout | 24h |
| Trailing Activate | 2% ROE |
| Trailing Distance | 2% |
| Tier 1 Min Funding | 100% APY |
| Tier 1 Min Volume | $1,000,000 |
| Tier 2 Min Funding | 100% APY |
| Tier 2 Min Volume | $500,000 |
| Risk Per Trade | 5% |
| Max Per Trade | $20 |
| Max Concurrent | 5 |
| Leverage | 3x |

## Transaction Cost Model

| Component | Rate |
|-----------|------|
| Taker Fee | 0.0350% per side |
| Slippage | 0.0500% per side |
| Round-Trip Cost | 0.1700% |

## Full Period Results (180 days)

| Window | Trades | W/L | Win Rate | Net PnL | Expectancy | PF | Max DD | Sharpe | Avg Hold |
|--------|--------|-----|----------|---------|------------|-----|--------|--------|----------|
| Full 180d | 23 | 19/4 | 82.6% | $2.44 | $0.1059 | 1.68 | 1.59% | 5.64 | 4.1h |

## 30-Day Window Results

| Window | Trades | W/L | Win Rate | Net PnL | Expectancy | PF | Max DD | Sharpe | Avg Hold |
|--------|--------|-----|----------|---------|------------|-----|--------|--------|----------|
| Window 1 (60d) | 0 | 0/0 | 0.0% | $0.00 | $0.0000 | 0.00 | 0.00% | 0.00 | 0.0h |
| Window 2 (60d) | 0 | 0/0 | 0.0% | $0.00 | $0.0000 | 0.00 | 0.00% | 0.00 | 0.0h |
| Window 3 (60d) | 21 | 17/4 | 81.0% | $1.17 | $0.0557 | 1.33 | 1.61% | 3.08 | 3.8h |

## Monthly Breakdown (Full Period)

| Month | Trades | Wins | Net PnL | Win Rate |
|-------|--------|------|---------|----------|
| 2026-01 | 2 | 2 | $1.26 | 100.0% |
| 2026-02 | 18 | 15 | $1.62 | 83.3% |
| 2026-03 | 3 | 2 | $-0.45 | 66.7% |

## Verdict: **CONDITIONAL-GO**

### GO/NO-GO Criteria

| Criterion | Required | Actual | Pass? |
|-----------|----------|--------|-------|
| Net expectancy > $0.00/trade | > $0.00 | $0.1059 | PASS |
| Profit factor > 1.2 | > 1.2 | 1.68 | PASS |
| Positive in >= 2/3 active windows | >= 2 | 1/1 active (2 idle) | FAIL |

### Reasoning

- Net expectancy $0.1059/trade is positive (PASS)
- Profit factor 1.68 exceeds 1.2 threshold (PASS)
- 2/3 windows had zero trades (neutral — strategy sat out)
- Only 1/3 windows had trades — insufficient data to assess consistency (FAIL)
- Expectancy and profit factor pass, but only 1/3 windows had trades. Strategy is regime-dependent — deploys conservatively, active only during extreme funding rates.

## Exit Reason Distribution

| Reason | Count | Avg Net PnL |
|--------|-------|-------------|
| STOP_LOSS | 2 | $-1.4396 |
| TAKE_PROFIT | 2 | $1.2201 |
| TIMEOUT | 1 | $-0.6727 |
| TRAILING_STOP | 18 | $0.1971 |
