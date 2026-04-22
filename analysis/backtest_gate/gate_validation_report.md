# D41 Backtest Gate Validation — Report

Generated: 2026-04-22T07:04:37Z
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
| GATED    | 2 | 100.00% | n/a | 0.4722 | 0.2361 |
| SUB_GATE | 21 | 80.95% | 1.5575 | 2.0911 | 0.0996 |

- PF_gated / PF_raw ratio: **None**
- Classification reason: n_gated=2 < 5 required for classification

## Score Distribution

| Range              | Count |
|--------------------|-------|
| [0.00, 0.50) | 0 |
| [0.50, 0.60) | 19 |
| [0.60, 0.65) | 2 |
| [0.65, 0.70) | 0 |
| [0.70, 0.75) | 1 |
| [0.75, 0.80) | 1 |
| [0.80, 1.01) | 0 |

## Warnings
- (none)

## Phase A delta vs 90eff68

Baseline: pre-Phase-A commit `90eff68` (cross_spread_norm forced to 0.0). Phase A wires Kraken historical funding into the cross-exchange spread component using a ±4h lookup window per trade; uncovered trades still fall back to 0.0.

| Metric            | Before (90eff68) | After (this run) |
|-------------------|------------------|------------------|
| n_gated           | 1 | 2 |
| Pass rate (n_gated/n_raw) | 4.35% | 8.70% |
| PF_gated          | n/a | n/a |
| WR_gated          | 100.00% | 100.00% |
| Net PnL (gated)   | $0.3180 | $0.4722 |
| Verdict           | UNKNOWN | UNKNOWN |

### Gate Crossings (Phase A)

| Asset | Entry (ms) | Direction | Score old→new | Outcome | PnL ($) |
|-------|-----------|-----------|---------------|---------|---------|
| MON | 1770746400000 | →GATED | 0.5812→0.7312 | W | +0.15 |

### Kraken Coverage Diagnostics

- Lookup window: ±4h around each trade's entry_time.
- Trades with Kraken row within window: **3 / 23**

| Asset | Covered / Total |
|-------|-----------------|
| MON | 1 / 1 |
| TAO | 1 / 1 |
| TRUMP | 1 / 1 |
| VVV | 0 / 20 |

## Known Biases (Proxy → Live)

After Phase A, two proxies remain biasing composite_score DOWNWARD vs live:

- **Cross-exchange spread** — Phase A wires Kraken funding when available
  within ±4h; uncovered trades still contribute 0. This removes one of the
  three documented proxies for the covered subset; the uncovered subset
  (e.g. VVV outside 2025-11-21) is unchanged from the 90eff68 behavior.
- **Liquidity** uses volume-only log-normalization; live blends 40% OI. Assets
  with high OI-to-volume ratio score lower than live would (up to −8 pts).
- **Duration survival** uses the pooled HIGH_FUNDING distribution when the
  specific asset is unknown. This is the same fallback the live predictor
  takes, so no extra bias beyond the live runtime.

**Interpretive rule:** if the gated cohort shows AMPLIFIES under these
proxies, live would be at least as strong. If HARMS, the result could be a
proxy artifact and should be treated as at most NEUTRAL until proxies
improve.