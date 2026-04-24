# Q1 Retroactive Gate Analysis — D50 resume

**Date:** 2026-04-24
**Scope:** Apply the current 0.70 composite gate retroactively to the
instrumented D50 canonical backtest (trade log + companion signal log
keyed by `(asset, entry_time)`). Supersedes the uncommitted D31 STOP
report at `analysis/q1_canonical_gate/REPORT.md`.
**Verdict:** **Q1 = AMPLIFIES** (PF_gated = 1.683 ≥ 1.30 AND n_gated = 23 ≥ 10) — with a material caveat about zero composite-score variance on this sample (§5).

---

## 1. Pinned artifact pair

| | |
|---|---|
| Trade log | `artifacts/backtest_trades_d50.jsonl` |
| Trade sha256 | `2ee4f3725b5ec9cccae1bec499a969ecdc3b702f4de17f334c6548692afe31f4` |
| Signal log | `artifacts/backtest_signals_d50.jsonl` |
| Signal sha256 | `0259dfaa9581ccf6d3a732e5e1ca5e09a3647020035fa3de5d8775840c72ba49` |
| Keying | `(asset, entry_time_ms)` — 23 trades × 23 signals, 1:1 invariant verified |

**D46 invariance verified at strongest form.** The D50 trade log sha256
equals the D31 trade log sha256 byte-for-byte. Not merely PF reconciles
within rounding — every field of every trade is identical. The post-D46
config (TIER*_MIN_FUNDING = 8.00 × 24 × 365) selects the same 23
historical entries that the pre-D43 config (threshold 1.00 × 1095)
selected, as the algebraic proof predicted (`rate × 1095 ≥ 1.0 ⇔
rate × 8760 ≥ 8.0`).

## 2. Instrumentation summary (D50)

`scripts/backtest/strategies/funding_arb.py` now constructs a
`RegimeTransitionEvent` per filtered candidate and invokes
`CompositeSignalScorer.score()` via read-only import. The scorer is
wired with:

| Scorer dependency | D50 wiring | Synthesis? |
|---|---|---|
| `duration_predictor` | Real `DurationPredictor` against `data/regime_history.db` (1472 transitions, 358 HIGH_FUNDING, 6 assets); pooled HIGH_FUNDING fallback for assets absent from the DB (predictor's own fallback path at `duration_predictor.py:53-59`) | No |
| `liquidity_scorer` | Volume-only log-norm against per-bar max volume (OI absent historically) | **Yes** — flagged in every record's `synthesized_fields` |
| `adapters` | `{}` (single-venue backtest) | No — scorer's own `<2-adapter` path at `composite_scorer.py:163` returns `None` for cross_spread |
| `RegimeTransitionEvent.max_apy_annualized` | `funding_annual × 100` (fraction → percent, matching `ats_connector.py:164` convention) | No — derived from the same historical rate the filter uses |
| `RegimeTransitionEvent.new_regime` | `RegimeTier.HIGH_FUNDING` (derived from the TIER*_MIN_FUNDING threshold crossing — only HIGH_FUNDING candidates survive the filter) | No — derived from real threshold check |

**Synthesis count: 1/5** (liquidity_score only). Under the 2/5 tripwire
from the D50 decision entry.

Engine change: `scripts/backtest/engine.py` gains `--enable-scoring` and
`--emit-tag` CLI flags. When both are set, the engine writes
`artifacts/backtest_trades_{tag}.jsonl` (D31-schema-compatible) plus the
companion signal log. No changes to filter logic, sizing, fees, funding
accrual, SL/TP/TIMEOUT, or trade outcomes.

## 3. PF_raw ground truth (reconciliation)

| Metric | D50 value | D31 reference |
|---|---|---|
| n_raw | 23 | 23 |
| PF_raw | 1.683 | 1.683 |
| WR_raw | 82.6% (19W / 4L) | 82.6% |
| gross_win | $6.3143 | $6.3143 |
| gross_loss | $3.7510 | $3.7510 |
| net PnL | $2.56 | $2.56 |
| Sharpe | 5.64 | 5.64 |
| Worst trade | VVV STOP_LOSS −$1.5159 | VVV STOP_LOSS −$1.5159 |
| sha256 | same | same |

Reconciliation: **byte-identical**. D46 invariance proof confirmed.

## 4. Composite score distribution

| | |
|---|---|
| n | 23 |
| min | 84.79 |
| max | 84.79 |
| mean | 84.79 |
| unique values | **1** (all 23 records = 84.79) |

Every surviving candidate receives the **exact same composite score of
84.79**. This is a structural consequence of the scorer's behavior on
this sample, documented below in §5.

## 5. Why composite score has zero variance on this sample (critical caveat)

The scorer weights (from `config.yaml`) are:
`net_apy=0.35, duration_confidence=0.30, liquidity=0.20, cross_exchange_spread=0.15`.

For every surviving candidate:

| Component | Input | Normalized value | Weight × value |
|---|---|---|---|
| `net_apy` normalized to [0, 500]% | max_apy_annualized ≥ 800% (all candidates exceed the 800% APY entry bar) | clamped to 1.0 | 0.35 |
| `duration_survival_prob` | Pooled HIGH_FUNDING distribution from `regime_history.db` (no per-asset data for backtest-window assets) | 0.993 (constant) | 0.2979 |
| `liquidity` normalized [0,1] | Volume-only log-norm vs per-bar max (each bar has only one surviving candidate → self-normalization → 1.0) | 1.0 | 0.20 |
| `cross_exchange_spread` normalized [0, 200] | `None` (single-venue backtest) → 0.0 per scorer rule at `composite_scorer.py:80-82` | 0.0 | 0.0 |

`composite = (0.35 + 0.2979 + 0.20 + 0) × 100 = 84.79` — **for every candidate**.

**Implications:**
- The scorer has **no discriminating power** on this historical sample.
  At a gate of 0.70 (=70), all 23 pass. At a gate of 0.85, zero pass.
  The gate is a step function with a cliff at 84.79.
- This is **not a synthesis bug**. Each of the four inputs is computed
  as the scorer would compute it. The zero variance is a property of
  the scorer × this specific sample: the filter that pre-selected these
  candidates (800% APY) saturates the net_apy component, the per-bar
  self-normalization of the liquidity proxy always returns 1.0 when
  only one candidate survives per bar, the pooled-duration fallback is
  constant across candidates, and the missing cross_spread is uniformly
  0.
- In live operation the scorer DOES discriminate because (a) it sees
  many candidates per cycle across the HIGH_FUNDING/MODERATE boundary
  (not just the top of HIGH_FUNDING), (b) liquidity normalization is
  against a global max, not per-candidate, and (c) cross_spread carries
  real multi-exchange variance. On the D31/D50 sample, the entry-time
  filter has already absorbed all of the discrimination upstream.

This is a real finding, not a blocker: it says the current 0.70 gate is
**non-binding** on the D31/D50 canonical sample. It does not reject
the canonical edge (Q1 = AMPLIFIES in the mechanical three-outcome
sense) but it also does not *improve* PF on this sample.

## 6. PF_gated and gate-sensitivity

| Gate | n_gated | PF_gated | WR_gated | gross_win | gross_loss |
|---|---|---|---|---|---|
| 0.50 | 23 | 1.683 | 82.6% | $6.31 | $3.75 |
| 0.60 | 23 | 1.683 | 82.6% | $6.31 | $3.75 |
| **0.70** | **23** | **1.683** | **82.6%** | **$6.31** | **$3.75** |
| 0.80 | 23 | 1.683 | 82.6% | $6.31 | $3.75 |
| 0.849 | 0 | n/a | n/a | — | — |
| 0.85 | 0 | n/a | n/a | — | — |

At the pre-registered 0.70 gate: **n_gated = 23, PF_gated = 1.683**,
identical to PF_raw because all 23 records score 84.79 ≥ 70.

### Worst-trade sensitivity (deliverable 5)

Worst gated trade: VVV STOP_LOSS, net_pnl −$1.5159.
`PF_gated excl worst = 6.3143 / (3.7510 − 1.5159) = 2.825`.

## 7. Verdict (three-outcome block)

| Outcome | Trigger | Applies? |
|---|---|---|
| (a) PF_gated ≥ 1.30 AND n_gated ≥ 10 → Q1 = **AMPLIFIES** | 1.683 ≥ 1.30 ✓ AND 23 ≥ 10 ✓ | **YES** |
| (b) 1.00 ≤ PF_gated < 1.30 OR n_gated < 10 → Q1 = NEUTRAL | — | no |
| (c) PF_gated < 1.00 → Q1 = CONTRADICTS, D-entry required | — | no |

**Q1 = AMPLIFIES** (mechanical). The canonical edge survives the live
0.70 composite gate on this sample.

### Routing per the D50 decision entry

Per §"Expected outcomes and routing" of D50:
> Q1 = AMPLIFIES ... Investigation routes to Q3 (paper/execution
> gating divergence).

Q3 is the logical next question. But the §5 caveat modifies the
*interpretation*: the canonical edge survives because the gate is
non-binding on this sample, not because the gate independently
validates the edge. If Q3 investigation finds paper/execution gating
divergence, the gate's behavior on *live* candidates (where it WOULD
discriminate) is the right object of study, not its behavior on this
backtest sample.

No D-entry is triggered by this verdict (outcome (a) does not require
one). No threshold proposals, no scorer changes. The D44 Path A / Path
B capital decision remains deferred per the D50 scope.

## 8. Adversarial pass (silent-failure checks)

Three plausible ways this AMPLIFIES verdict could be spurious:

1. **Scorer is secretly bypassed.**
   - Evidence: `funding_arb.py:90-95` deferred import confirms the
     scorer is instantiated only when `enable_scoring=True`. At call
     time, `self._asyncio.run(self._scorer.score(event))` runs the
     real async scorer — same module, same weights, same formula as
     the live pipeline uses.
   - Conclusion: not bypassed. The 84.79 is the scorer's output.

2. **Synthesis is quietly used for inputs the task treats as real.**
   - Evidence: each record's `synthesized_fields` contains exactly one
     entry, covering only `liquidity_score`. `duration_survival_prob`
     appears as 0.993 (real pooled DB value, verified by manual query
     `python3 -c "... predictor.predict(...)"` on unknown assets
     returning used_fallback=True, survival=0.993). `max_apy_annualized`
     is `funding_annual × 100` (pure conversion). `cross_exchange_spread`
     is `None` per scorer's own <2-adapter path, not a synthesized 0.
   - Conclusion: synthesis is 1/5 as stated, not higher.

3. **1:1 companion invariant is secretly violated (trades without
   signals or signals without trades).**
   - Evidence: run.py checks `len(trades) == len(signals)` and that
     every `(asset, entry_time)` in trades is present in the signal
     index. Both pass.
   - Conclusion: no hidden mismatch.

**Residual acknowledged:** the zero-variance observation itself is
**the** key epistemic finding. It is not a failure of the instrumentation
or of the scorer; it is a property of applying the current scorer
retroactively to a sample where the entry-time filter has already
saturated the net_apy component and where per-bar self-normalization
flattens liquidity. This behavior is material to Q3 (which studies the
live-vs-paper gate divergence) and is raised above.

## 9. Backlog advancement

- **Q1:** advanced from "open — blocked on structural data gap" (prior
  BLOCKED-ON-DATA verdict in `REPORT.md`) to "resolved — AMPLIFIES
  mechanically; gate non-binding on this sample".
- **Q2 (sample-size projection):** not touched this session.
- **Q3 (paper/execution gating divergence):** elevated. The §5 finding
  (scorer has zero variance on canonical sample) narrows Q3's scope:
  any live/paper divergence attributable to the 0.70 gate must come
  from the subset of candidates *not* saturating the net_apy
  component (moderate-APY candidates) or with multi-venue data.
  Proposed Q3 object of study: live `signal_filter.db` records
  (which carry the full scorer inputs per live candidate including
  those rejected by filters the backtest sample pre-passed).

## 10. Artifacts produced this session

- `artifacts/backtest_trades_d50.jsonl` (23 trades; byte-identical to D31)
- `artifacts/backtest_signals_d50.jsonl` (23 companion records, keyed by `(asset, entry_time)`)
- `analysis/q1_canonical_gate/run.py` — parameterized to accept `--trade-log`, `--signal-log`, `--gate`. Legacy D31 STOP path preserved when `--signal-log` omitted.
- `analysis/q1_canonical_gate/REPORT_D50.md` — this file.
- `scripts/backtest/engine.py` — adds `--enable-scoring`, `--emit-tag`, `self.entry_signals`, `export_trades_jsonl`, `export_signals_jsonl`.
- `scripts/backtest/strategies/funding_arb.py` — adds `enable_scoring`, `_score_candidate`, `_HistoricalLiquidityScorer`.
- Governance: D50 entry at `/Users/yumo/Desktop/ats_files/decision_log.md` extended with "Pinned artifacts" subheading (per acceptance criterion 1).

## 11. Verification footer

Re-run the full pass from repo root:

```
python3 scripts/backtest/engine.py --strategy funding_arb \
  --start-date 2025-10-18 --end-date 2026-04-16 \
  --initial-capital 95 --enable-scoring --emit-tag d50

python3 analysis/q1_canonical_gate/run.py \
  --trade-log artifacts/backtest_trades_d50.jsonl \
  --signal-log artifacts/backtest_signals_d50.jsonl \
  --gate 0.70
```

Both commands are idempotent against the pinned artifact pair.
