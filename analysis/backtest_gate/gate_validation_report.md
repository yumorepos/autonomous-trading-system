# D41 Backtest Gate Validation — Report

Generated: 2026-04-22T05:26:46Z
Trade log: `/Users/yumo/Projects/autonomous-trading-system/artifacts/backtest_trades_d31.jsonl`

**Verdict: UNKNOWN**

## D41 Classification Thresholds

- AMPLIFIES: PF_gated / PF_raw ≥ **1.3**
- HARMS:    PF_gated / PF_raw < **0.85**
- NEUTRAL:  between the two, with n_gated ≥ 5
- UNKNOWN:  n_gated < 5 OR PF_raw undefined

## Canonical Sanity Check

- Canonical PF (D31 headline): **1.68**, tolerance ±0.1
- Reconstructed PF_raw: **1.6834** — PASS

## Partition Stats (threshold score_normalized ≥ 0.70)

| Cohort   | n  | Win rate | Profit factor | Net PnL ($) | Expectancy ($) |
|----------|----|----------|---------------|-------------|----------------|
| RAW      | 23 | 82.61% | 1.6834 | 2.5633 | 0.1114 |
| GATED    | 1 | 100.00% | n/a | 0.3180 | 0.3180 |
| SUB_GATE | 22 | 81.82% | 1.5986 | 2.2453 | 0.1021 |

- PF_gated / PF_raw ratio: **None**
- Classification reason: n_gated=1 < 5 required for classification

## Score Distribution

| Range              | Count |
|--------------------|-------|
| [0.00, 0.50) | 1 |
| [0.50, 0.60) | 19 |
| [0.60, 0.65) | 2 |
| [0.65, 0.70) | 0 |
| [0.70, 0.75) | 0 |
| [0.75, 0.80) | 1 |
| [0.80, 1.01) | 0 |

## Warnings
- (none)

## Known Biases (Proxy → Live)

All three proxies bias composite_score DOWNWARD relative to live:

- **Cross-exchange spread** forced to `None` → contributes 0 (up to −15 pts).
- **Liquidity** uses volume-only log-normalization; live blends 40% OI. Assets
  with high OI-to-volume ratio score lower than live would (up to −8 pts).
- **Duration survival** uses the pooled HIGH_FUNDING distribution when the
  specific asset is unknown. This is the same fallback the live predictor
  takes, so no extra bias beyond the live runtime.

**Interpretive rule:** if the gated cohort shows AMPLIFIES under these
proxies, live would be at least as strong. If HARMS, the result could be a
proxy artifact and should be treated as at most NEUTRAL until proxies
improve.