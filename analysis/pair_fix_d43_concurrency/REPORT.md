# Pair-Fix Session — D43 Annualization + Concurrency + 8× Retune

**Author:** Claude Code (pair-fix session)
**Date:** 2026-04-22
**Branch:** `fix/d43-concurrency-path-a` off `main` (8d3cf0b)
**Scope:** One deployable paper-trading policy state aligning three coupled fixes.

---

## 1. Problem statement

Three issues surfaced by prior audits were locked to the same deploy boundary because shipping any one without the others would have changed the live filter's effective bar silently:

1. **MAX_CONCURRENT=1 not enforced.** `config/risk_params.py:30` declared 1, but `config/config.yaml:78` had `simulator.max_open_positions: 5` and `PaperTrader` read from the yaml with a 5-default constructor fallback. VPS had 3 concurrent opens (SUPER / MET / CHIP) earlier in this day's session, directly contradicting the declared discipline. D41 PF 1.063 was contaminated by same-window overlaps (first-in-wins reconstruction gave PF 1.4448 at n=7, Δ +0.3822).
2. **D43 HL under-annualization.** Hyperliquid `ctx['funding']` is per-hour, not per-8h. Four live code paths used `* 3 * 365` (intended for 8h), understating APY by 8×. Effective live entry bar was ~800% true APY, not the nominal 100%.
3. **Threshold retune required.** Fixing (2) without scaling `TIER1/TIER2_MIN_FUNDING` and `HIGH_FUNDING_MIN_MAX_APY` would have 8×'d the effective entry rate — silently widening the live filter and inviting a fresh batch of sub-marginal trades.

Shipping these independently would let the live filter drift mid-flight. They land together.

---

## 2. Phase 0 ground truth (before patch)

**Grep sweep vs. assumed truths (three contradictions surfaced):**

| Category | Assumed | Found |
|:-|:-|:-|
| Canonical D43 sites | 3 (brief listed regime_detector:165, trading_engine:804, funding_arb:60) | **4 live sites** — added `scripts/tiered_scanner.py:78`. Brief missed this; `system_state.md` listed tiered_scanner but missed regime_detector. Both enumerations were incomplete. |
| MAX_CONCURRENT drift | Paper trader only | **+2 additional drifts off-path:** `scripts/hl_entry.py:66` (local = 2) and `scripts/daily-review.py:43` (local `MAX_CONCURRENT_POSITIONS = 5`). Verified off the live paper path via grep for imports reachable from `run_paper_trading.py` and `live_orchestrator.py`. |
| VPS open-position count | 3 (SUPER / MET / CHIP) | **0** — all three closed between Session 1 and this session. Phase 4 downgraded to synthetic regression test. |

All three resolved before code edits (scope clarified with operator).

---

## 3. What landed

### 3.1 Concurrency (Commit 1)

- `src/simulator/paper_trader.py:16-22`: now imports `MAX_CONCURRENT` from `config/risk_params.py`.
- `src/simulator/paper_trader.py:37-52`: constructor signature changed from `max_open_positions: int = 5` to `max_open_positions: int | None = None`; when `None`, defaults to `MAX_CONCURRENT`. Test ergonomics preserved (explicit overrides still work), but production path has no yaml fallback.
- `config/config.yaml:78`: `max_open_positions: 5` removed; breadcrumb comment retained pointing to the new source of truth.
- `scripts/run_paper_trading.py:70-78`: `max_open_positions=sim_cfg.get(...)` argument removed from the `PaperTrader(...)` call.

**Invariant preserved:** duplicate-asset-on-same-exchange protection unchanged (`paper_trader.py:317-323`).

**Reload exemption:** `_reload_open_positions_from_log()` appends `SimulatedPosition` directly to `self.positions` — it does NOT call `open_position()` and therefore never hits the MAX_CONCURRENT gate. This is the correct semantic (reload must not silently drop legacy opens when the limit tightens) and was already the case; no code change needed, only a regression test.

### 3.2 Annualization (Commit 2)

`* 3 * 365` → `* 24 * 365` at **four canonical sites**:

- `scripts/regime_detector.py:165`
- `scripts/trading_engine.py:804`
- `scripts/backtest/strategies/funding_arb.py:60` (+ docstring line 5)
- `scripts/tiered_scanner.py:78`

Each carries a one-line D43 comment so a future reader can't silently revert. `funding_arb.py`'s file docstring was also updated to reflect the per-hour semantic (legacy variable name `rate_8h` preserved for diff hygiene; flagged in docstring).

### 3.3 Threshold retune (Commit 3)

`config/risk_params.py`:
- `TIER1_MIN_FUNDING`: 1.00 → 8.00
- `TIER2_MIN_FUNDING`: 1.00 → 8.00

`config/regime_thresholds.py`:
- `HIGH_FUNDING_MIN_MAX_APY`: 1.00 → 8.00

**Invariant:** `(|r| * 3 * 365) >= 1.00` ≡ `(|r| * 24 * 365) >= 8.00` (both equal `|r| >= 1/1095 = 0.0009132…`). This is proven by `test_path_a_invariant_on_sampled_rates` (100 sampled rates in [0, 0.05]) and `test_path_a_invariant_on_boundary_rates`. Every rate that passed the pre-D43 nominal-100% gate passes the post-D43 true-800% gate, and vice versa. The 8× retune is not a change in selection criteria — it preserves the effective bar while the APY unit is corrected.

Also updated in Commit 3 (same logical boundary): four pre-existing tests that hardcoded the old 1.00 threshold (`test_funding_arb_classify_matches_live`, `test_high_funding_regime`, `test_boundary_high_funding_exact_threshold`, `test_default_thresholds`) plus two passing-but-semantically-stale tests (`test_sub_threshold_no_signal`, `test_below_threshold_no_signal` — they were computing APY with the old `* 3 * 365` for the assertion math even though they still produced the expected no-signal outcome). Updating them in the same commit keeps every commit green on `pytest tests/` for clean bisection.

### 3.4 New tests (Commit 4)

- `tests/test_paper_trader.py::TestMaxConcurrentSourceOfTruth` — 4 tests:
  - `test_max_concurrent_rejects_second_open`
  - `test_max_concurrent_reads_from_risk_params_not_yaml`
  - `test_existing_open_positions_persist_across_reload`
  - `test_reload_from_jsonl_preserves_existing_opens_past_limit` (3-open scenario mirroring real VPS state earlier in the day)
- `tests/test_d43_annualization.py` — 4 tests (behavioral for regime_detector + funding_arb; source-inspection for trading_engine + tiered_scanner, since unit-testing scanner loops requires mocking urllib + HL client + regime state file and that mock surface area isn't worth the fragility).
- `tests/test_path_a_preservation.py` — 6 tests pinning the 8×-scale invariant (constant equality, 100-sample property, exact boundary, tier-1 boundary independently).

**14 new tests** on top of the 312-test baseline on main → 326 collected, 326 passing.

### 3.5 Migration handling

VPS was empty at session start (0 open positions). No live migration was required. The reload-exemption is guarded synthetically by `test_reload_from_jsonl_preserves_existing_opens_past_limit` (constructs 3 opens with a loose PaperTrader, reloads with MAX_CONCURRENT=1, asserts all 3 persist and a 4th open is rejected). If a future restart hits non-empty state past the limit, the regression test documents the expected behavior.

---

## 4. Out of scope (this session)

These were surfaced during Phase 0 or analysis but deferred per the operator's Phase 0 direction:

**Known drift — not on live paper path (file as future housekeeping, D46-era):**
- `scripts/hl_entry.py:66`: local `MAX_CONCURRENT = 2` (not importing from risk_params). Invoked only by `scripts/ats-cycle.py`, a separate cron orchestrator. Not reachable from `scripts/run_paper_trading.py` or `src/pipeline/live_orchestrator.py`.
- `scripts/daily-review.py:43`: local `MAX_CONCURRENT_POSITIONS = 5`. Standalone cron script, not imported by the paper path.

**Known follow-up — non-decision-path `* 3 * 365` sites:**
- `scripts/signal_engine.py:63`
- `scripts/phase1-signal-scanner.py:86`
- `scripts/daily-review.py:276`
- `scripts/backtest/engine_regime_exit.py:206`
- `scripts/backtest/diagnose_funding_arb.py:167` (display)
- `src/collectors/exchange_adapters/base.py:56` (docstring example)

All produce logged/displayed APY values that will silently under-report by 8× if left alone, but none are on the live entry-decision path. The stale displays will confuse an operator reading logs — worth fixing, but not to block deploy.

**Additional stale-semantics follow-ups (flagged, not fixed):**
- `config/regime_thresholds.py:35-40`: `REGIME_EXIT_THRESHOLDS` hysteresis bands (`HIGH_FUNDING: 0.80`, `MODERATE: 0.60`) are on the same `max_funding_apy` scale as `HIGH_FUNDING_MIN_MAX_APY`. After the 8× retune, the ENTRY threshold is 8.00 but EXIT stays at 0.80/0.60, opening a much wider hysteresis dead-zone than the pre-fix 100%→80% band. This is subtle — probably wants a deliberate discussion on band width rather than a mechanical 8×.
- `scripts/regime_detector.py:72`: `above_100 = sum(1 for a in asset_funding if a["funding_apy"] >= 1.00)` — the "above 100" counter hardcodes `1.00`, which post-D43 corresponds to ~12.5% of the old 100% scale. EXTREME regime (>=10% of assets above that counter) will trigger much more easily. `test_extreme_regime_many_assets` in `tests/test_regime_detector.py:250-261` still passes because it uses funding=-0.001 values that cross the new scale too — but the test's comment ("~109% APY") is now stale (really ~876% APY).
- `config/regime_thresholds.py:24`: `MODERATE_MIN_MAX_APY = 0.75` — same semantic issue, not 8×'d.

**Governance doc corrections — DEFERRED to next governance consolidation:**
- Desktop `system_state.md` and `decision_log.md` list three D43 sites. Real count is four (add `scripts/tiered_scanner.py:78`). Per operator direction, do NOT edit Desktop files this session.

---

## 5. Verification

- Full suite: **326 passed in 46.46s** (0 failures, 0 skips). 14 new tests, 4 existing tests updated to match the retuned thresholds.
- No VPS changes this session (operator handles deploy separately).
- No pushes, no merges, no ledger mutation.

---

## 6. Commit sequence

1. `fix(paper): enforce MAX_CONCURRENT=1 by reading from risk_params, remove config.yaml drift`
2. `fix(annualization): correct HL funding annualization to × 24 × 365 at four D43 sites`
3. `config: retune TIER1/TIER2_MIN_FUNDING and HIGH_FUNDING_MIN_MAX_APY 1.00 → 8.00 to preserve Path A effective bar post-D43`
4. `test: concurrency enforcement, annualization correctness, Path A preservation invariants`
5. `analysis: pair-fix session report (D43 + concurrency + 8× retune)`

All commits are local-only on `fix/d43-concurrency-path-a`. No push.

---

## 7. Deploy readiness

The three fixes now share one branch-head SHA. Operator can deploy all three atomically:

```
systemctl stop ats-paper-trader
cd /opt/trading && git fetch && git checkout <commit5-SHA>
systemctl start ats-paper-trader
```

A half-landed state (any subset of commits 1–3 deployed without the others) is the exact failure mode this session was structured to prevent.

**Before-deploy operator check:** the paper-trades ledger is currently empty (0 opens as of session start). If new opens accrued between session close and deploy, the reload-exemption test guarantees they survive the MAX_CONCURRENT=1 tightening — but new opens after deploy are gated to 1.
