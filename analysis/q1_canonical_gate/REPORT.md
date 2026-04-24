# Q1 Retroactive Gate Analysis — STOP (tripwire hit)

**Date:** 2026-04-24
**Scope:** Apply current 0.70 composite gate retroactively to the pinned
canonical D31 backtest trade log and report PF_raw vs PF_gated side-by-side.
**Verdict:** **STOP** — "Scorer requires inputs the trade log does not carry"
(tripwire #3 in task brief). PF_gated not computed.

---

## 1. Pinned artifact hash verification

| | |
|---|---|
| Path | `artifacts/backtest_trades_d31.jsonl` |
| Expected sha256 | `2ee4f3725b5ec9cccae1bec499a969ecdc3b702f4de17f334c6548692afe31f4` |
| Actual sha256 | `2ee4f3725b5ec9cccae1bec499a969ecdc3b702f4de17f334c6548692afe31f4` |
| Match | **TRUE** ✓ |

## 2. Composite scorer commit SHA + drift check

| | |
|---|---|
| Scorer path | `src/scoring/composite_scorer.py` |
| Most recent commit touching the scorer | `2b17958` dated `2026-04-15 17:07:46 -0400` |
| D31 artifact mtime (local) | `2026-04-16 23:46:49` |
| Drift between scorer at D31 and scorer at HEAD | **NONE** — scorer last touched 2026-04-15, one day before the D31 artifact was generated; no intervening commits |
| Retroactive-applicability caveat | **Not triggered.** The scorer you would apply retroactively is the same scorer that existed at D31. No "later gate applied to older selection" concern. |

Checked via `git log --follow --format="%h %ci" src/scoring/composite_scorer.py`; the three most recent commits are `2b17958` (2026-04-15), `cf0aa5b` (2026-04-14), `9ee6bc9` (2026-04-13) — all pre-dating the artifact mtime.

## 3. PF_raw ground-truth reproduction

Computed directly from the 23-trade log. Methodology: `net_pnl` field sums,
wins = `net_pnl > 0`, losses = `net_pnl <= 0`. No re-derivation of sizing,
fees, or funding accrual — re-uses the values the D31 engine wrote.

| Metric | Value |
|---|---|
| n_raw | 23 |
| gross_win | $6.3143 |
| gross_loss | $3.7510 |
| **PF_raw** | **1.683** |
| WR_raw | 82.6% (19W / 4L) |
| reproduces 1.68 ± rounding | **YES** |
| worst raw trade | VVV STOP_LOSS, net_pnl −$1.5159 (entry 2026 snap at `entry_time=1771142400000`) |

PF_raw tripwire (#2) did NOT fire — the raw profit factor reproduces canonically. The pinned pipeline is internally consistent.

## 4. Scorer input gap (root cause of the STOP)

### 4a. Trade log fields (12 unique, union across all 23 records)

`asset`, `direction`, `entry_price`, `entry_time`, `exit_price`,
`exit_reason`, `exit_time`, `fees`, `funding`, `gross_pnl`, `net_pnl`,
`size_usd`

All 12 are execution-layer outputs: prices, timestamps, P&L components,
position size. None are signal-layer inputs.

### 4b. Inputs required by `composite_scorer.py::score()`

Read from `src/scoring/composite_scorer.py:42-89`. All five required inputs
are **absent** from the trade log:

| Required input | Used at | Origin | In log? |
|---|---|---|---|
| `event.max_apy_annualized` | line 63 (net_apy computation) | `RegimeTransitionEvent` field — entry-time funding APY | **NO** |
| `event.new_regime` | line 96 (regime gate) | `RegimeTransitionEvent` field — HIGH_FUNDING tier label | **NO** |
| `duration_est.survival_probability` | line 86 (composite), line 102 (gate) | `DurationPredictor.predict()` output at entry timestamp | **NO** (stateful — requires replaying duration model against historical regime data) |
| `liq_score` | line 87 (composite), line 108 (gate) | `LiquidityScorer.score()` output — orderbook depth snapshot | **NO** (environmental — requires orderbook depth snapshot at entry time, not reconstructable post-hoc) |
| `cross_spread` | line 88 (composite) | `_compute_cross_exchange_spread()` — live cross-exchange funding | **NO** (environmental — requires live multi-exchange rates at entry time) |

### 4c. Why the inputs are not in the log (pipeline divergence)

`scripts/backtest/strategies/funding_arb.py:55-106` filters candidates on
`funding_annual * TIER*_MIN_FUNDING` and `volume_24h * TIER*_MIN_VOLUME`
only. It never constructs a `RegimeTransitionEvent`, never calls
`CompositeSignalScorer`, never records a composite score. The backtest and
live codepaths diverge at the signal layer: live emits `ScoredSignal`
(carries `composite_score` and its four inputs); backtest emits `{asset,
direction, size_usd, score=funding_annual, tier, ...}` — a pre-composite
object.

The trade log captures what the backtest engine subsequently did with the
candidate (entry, exit, P&L). The scorer's view of that candidate at entry
time was never persisted because it was never computed.

### 4d. Per-trade table (partial — gated column unfillable)

Full table below. `composite_score` and `gated` columns left as `—`
because they cannot be computed from the log; showing them as blanks would
misrepresent the STOP. `raw included` is universally `true` (all 23 are
in-sample).

| # | asset | entry_ts (ms) | exit_ts (ms) | net_pnl | raw included | composite_score | gated |
|---|---|---|---|---|---|---|---|
| 1 | VVV | 1768010400000 | 1768060800000 | +$0.0470 | true | — | — |
| 2 | VVV | 1768154400000 | 1768158000000 | +$1.2841 | true | — | — |
| 3 | MON | 1770746400000 | 1770753600000 | +$0.1542 | true | — | — |
| 4–23 | … (see `artifacts/backtest_trades_d31.jsonl`) | | | | true | — | — |

(A full 23-row dump is available from the script's stage-3 computation; omitted here because without the gated column it's execution tail padding — reader gains nothing beyond the summary stats in §3.)

### 4e. Worst-trade sensitivity (deliverable 5)

**Not computable.** The deliverable was "PF_gated excluding the single worst gated trade", which requires an existing PF_gated. PF_gated is blocked, so this downstream metric is also blocked. For reference only, worst raw trade is VVV STOP_LOSS at −$1.5159; `PF_raw_excl_worst = 6.3143 / (3.7510 − 1.5159) = 2.825`. This is a raw-sample statistic, not a gated one, and should not be used as a substitute.

## 5. Verdict (three-outcome block — none apply)

The three pre-registered outcomes (a) / (b) / (c) in the task brief all presuppose a computed `PF_gated` value. None apply here:

| Outcome | Trigger | Applies? |
|---|---|---|
| (a) `PF_gated ≥ 1.30 AND n_gated ≥ 10` → Q1 = AMPLIFIES | requires PF_gated | **NO — PF_gated blocked** |
| (b) `1.00 ≤ PF_gated < 1.30 OR n_gated < 10` → Q1 = NEUTRAL | requires PF_gated | **NO — PF_gated blocked** |
| (c) `PF_gated < 1.00` → Q1 = CONTRADICTS, D-entry required | requires PF_gated | **NO — PF_gated blocked** |

**Effective verdict: Q1 = BLOCKED-ON-DATA.** The canonical D31 artifact alone is insufficient to answer Q1 in either direction. No D-entry skeleton for parameter change is warranted (outcome (c) did not trigger) and none is proposed.

## 6. Adversarial pass on the STOP (in the spirit of WAIT-discipline)

Three plausible silent-failure modes that could make this STOP spurious, with evidence:

1. **Companion signal log might exist but be untracked.**
   - Evidence: `find . -name "backtest_*" -type f` returns only `scripts/backtest/*.py`, `artifacts/backtest_trades_d31.jsonl`, and unrelated analysis dirs. `ls artifacts/` shows no signal/score companion file. `grep -r "composite_score|duration_survival|liquidity_score" scripts/backtest/*.py` → no matches.
   - **Conclusion:** no hidden companion. Gap is real.

2. **Scorer might degrade gracefully with missing inputs.**
   - Evidence: `composite_scorer.py:84-89` unconditionally multiplies all four weighted components. `duration_predictor.predict()` and `liquidity_scorer.score()` are async calls requiring model state and a live adapter respectively. With inputs unavailable they cannot return; they would raise (tripwire #4, "any composite_score computation throws"). No fallback path inside the scorer.
   - **Conclusion:** cannot be partial-computed. Gap blocks the full score.

3. **The trade log schema might be richer than observed — maybe some records carry extra fields.**
   - Evidence: union of keys across all 23 records (script stage 4) = exactly 12 fields, all execution-layer. No record has any of the scorer inputs.
   - **Conclusion:** schema is uniform; no hidden enrichment.

**Residual risks (unverified this session):**
- Whether older commits of `scripts/backtest/engine.py` or its strategies once emitted a richer record that was later pruned. Not pursued because the task scope is "read-only analysis against the currently pinned artifact", not an archaeology of prior output formats.
- Whether `src/models.py::RegimeTransitionEvent` constructor could synthesize a minimal event from log fields + runtime calls. Not pursued because synthesizing a regime event from post-hoc execution data would be "inventing substitute values" (explicitly forbidden by task brief §FORBIDDEN, item 2).

## 7. Backlog advancement (checkpoint 3)

**Q1 advanced from "open — unknown tractability" to "open — blocked on structural data gap".** Specifically: the canonical backtest pipeline and the live scorer diverge at the signal layer; neither persists composite-score inputs against individual backtest trades. Resolving Q1 requires one of:

- **Option A:** instrument `scripts/backtest/engine.py` (or its strategy) to construct a `RegimeTransitionEvent` per candidate and invoke `CompositeSignalScorer`, emitting `composite_score` + its four inputs into a companion jsonl keyed by `(asset, entry_time)`. Then re-run the canonical 180-day backtest, re-pin artifacts, and apply the 0.70 gate to the companion.
- **Option B:** redefine Q1's evaluation sample to the live `execution_log.jsonl` (which does carry all four scorer inputs and the composite score per signal), making it a live/live-gated comparison rather than canonical-backtest/live-gated.

Both options are structural decisions that require operator review via a D-entry. **This report does not propose either** (threshold proposals and scorer-logic changes are forbidden by session scope); it documents the gap and the two paths so the operator can choose.

**Q2 and Q3 are not touched by this session.**

## 8. Artifacts produced

- `analysis/q1_canonical_gate/run.py` — read-only analysis script (hash-check + scorer-drift check + PF_raw reproduction + input-gap enumeration). Re-runnable.
- `analysis/q1_canonical_gate/REPORT.md` — this file.

## 9. No commit

Per task brief §DELIVERABLES: "Commit only if the analysis completes cleanly; if it ends in STOP-and-report, leave uncommitted for operator review." Files left uncommitted.

## 10. Verification footer

Script output reproduces all numeric claims in this report. Run from repo root:

```
python3 analysis/q1_canonical_gate/run.py
```

Session-open minimum-verification queries (quoted in response body, not
re-dumped here): `systemctl is-active` → `active`; deployed HEAD
`e066ae1`; `/paper/status` shows n=27 closed, PnL −$41.01 (informational,
not used in this analysis). Working directory verified
`/Users/yumo/Projects/autonomous-trading-system`, origin
`yumorepos/autonomous-trading-system`.
