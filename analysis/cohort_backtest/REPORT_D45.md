# D45 — Cohort Backtest Rerun Under Corrected Volume Filter

**Session:** 2026-04-22 UTC
**Scope:** Promote the USD-notional volume semantic into
`scripts/backtest/engine.py::estimate_volumes` so the mainline backtest engine
matches the live pipeline’s HL `dayNtlVlm` filter at
`scripts/tiered_scanner.py:76`. Rerun the D44 cohort backtest under the
patched engine and emit a semantically-honest comparator for D44.
**Branch:** `d45-backtest-filter-fix` (local, unpushed).
**Provenance:** cohort ETL pinned at
`data/historical/memecoin_cohort/` (window 2025-10-24 → 2026-04-22, 55,101
funding rows, 14 assets). Paper ledger pin
`analysis/snapshots/20260422T202943Z/paper_trades.jsonl`
sha256 `5a85d82…` (59 lines, 21 clean closes + 3 still-open).

---

## 1. The fix

### 1a. Patch (engine.py:618–627)

```diff
 def estimate_volumes(market_data: dict[str, dict[int, dict]]) -> dict[str, float]:
-    """Estimate 24h volume per asset from candle data (sum last 24 1h candles)."""
+    """Estimate 24h USD-notional volume per asset (sum of coin × close over last 24 1h candles).
+
+    D45 fix: volume_24h is USD notional (coin × close) to match live filter
+    semantic at scripts/tiered_scanner.py:76 (HL ``dayNtlVlm``). See
+    analysis/volume_filter_audit/REPORT.md for the prior coin-count bug.
+    Threshold (TIER2_MIN_VOLUME = 500_000) is unchanged; units are now USD.
+    """
     volumes: dict[str, float] = {}
     for asset, candles in market_data.items():
         sorted_ts = sorted(candles.keys())
         # Use last 24 candles as proxy
         recent = sorted_ts[-24:] if len(sorted_ts) >= 24 else sorted_ts
-        vol = sum(candles[ts]["volume"] for ts in recent)
+        vol = sum(candles[ts]["volume"] * candles[ts]["close"] for ts in recent)
         volumes[asset] = vol
     return volumes
```

### 1b. Blast radius

`estimate_volumes` is imported by six drivers besides `run_cohort_backtest.py`:
`scripts/backtest/sizing_sweep.py`, `scripts/backtest/report.py`,
`scripts/backtest/sweep.py`, `scripts/backtest/diagnose_funding_arb.py`,
`scripts/backtest/validate_edge.py`,
`analysis/path_decision/run_path_backtests.py`. All six previously
consumed coin-count sums. They now consume USD-notional sums — this
closes the long-standing mismatch that was quietly rejecting
low-priced-but-high-turnover memecoins and admitting low-turnover ones
that the live scanner would reject. The D44 cohort driver has its own
`usd_volume_estimator` at `run_cohort_backtest.py:72-87` that already
computed USD notional and passed it via `engine.run(volume_data=…)` —
so the cohort **results themselves do not change**, only the engine
default is brought into alignment. The driver’s helper is now
functionally redundant but kept in place per D45 task scope ("preserve
the 8× pre-scale trick").

### 1c. Tests

`tests/test_backtest_volume_semantic.py` — 9 cases covering: unit coin
at unit price; 1000 coins × $1 → $1000; 100M coins × $0.01 → $1M (clears
threshold); 1M coins × $0.0001 → $100 (fails threshold, was PASS under
coin-count); a 24-bar hand-computed series; only last-24 bars are used;
fewer-than-24-bars fallback; empty-candles edge case; multi-asset
independence.

Full pytest: **354 passed in 45.0s** (= 345 baseline + 9 new). No regressions.

---

## 2. Four-config results (under patched engine)

| Config | n | WR | **PF** | Net | Expectancy | Max DD | Sharpe | Avg hold |
|:-|-:|-:|-:|-:|-:|-:|-:|-:|
| Path A (800% TRUE APY) — vol-ON $500K | 36 | 75.0% | **1.4665** | +$3.16 | +$0.0877 | 0.04% | 4.38 | 7.58 h |
| Path B (100% TRUE APY) — vol-ON $500K | 195 | 69.2% | **1.1370** | +$3.89 | +$0.0199 | 0.12% | 1.36 | 9.33 h |
| Path A — vol-OFF (sensitivity) | 183 | 69.4% | 0.8234 | −$7.01 | −$0.0383 | 0.09% | −2.20 | 10.89 h |
| Path B — vol-OFF (sensitivity) | 711 | 62.5% | 0.8359 | −$19.33 | −$0.0272 | 0.24% | −1.92 | 12.69 h |

Numbers match the prior D44 REPORT within rounding (PF 1.47/1.14/0.82/0.84),
confirming the D45 audit’s claim that the cohort driver was already
USD-semantic. The D45 fix promotes that semantic into the engine default.

### 2a. Per-asset (vol-ON)

Path A: BIO n=9 PF 5.03 +$1.98 · BLUR n=25 PF 1.54 +$2.56 · MET n=2 PF 0.09 −$1.38.
Path B: BLUR n=70 PF 1.70 +$6.17 · BIO n=94 PF 0.95 −$0.67 · CHIP n=6 PF 5.83 +$1.19 · DOT n=14 PF 0.36 −$1.36 · MET n=11 PF 0.44 −$1.45.

Only 3 of 14 cohort assets fire in Path A; 5 of 14 in Path B. Neither path
exercises ALT, BLAST, MOVE, SAGA, STABLE, SUPER, UMA, YZY, ZETA under
the honest (USD-notional) filter — the live memecoin universe is not
meaningfully observable in the 180-day cohort window.

---

## 3. Asset eligibility delta (coin-count vs USD-notional)

Static, computed over the last 24 1h candles of each cohort CSV.

| Asset | coin count 24h | USD 24h | coin-count ≥ 500K | USD ≥ 500K | Transition |
|:-|-:|-:|:-:|:-:|:-|
| ALT | 27,702,858 | $211,841 | PASS | FAIL | **dropped** |
| BIO | 153,885,808 | $4,548,234 | PASS | PASS | retained |
| BLAST | 228,388,101 | $117,355 | PASS | FAIL | **dropped** |
| BLUR | 34,131,728 | $1,096,610 | PASS | PASS | retained |
| CHIP | 1,077,578,038 | $102,990,689 | PASS | PASS | retained |
| DOT | 1,010,477 | $1,301,523 | PASS | PASS | retained |
| MET | 77,813,049 | $14,684,409 | PASS | PASS | retained |
| MOVE | 7,800,610 | $144,157 | PASS | FAIL | **dropped** |
| SAGA | 22,526,685 | $414,995 | PASS | FAIL | **dropped** |
| STABLE | 12,366,142 | $323,606 | PASS | FAIL | **dropped** |
| SUPER | 1,337,017 | $172,946 | PASS | FAIL | **dropped** |
| UMA | 274,331 | $131,309 | FAIL | FAIL | excluded (both) |
| YZY | 95,768 | $28,683 | FAIL | FAIL | excluded (both) |
| ZETA | 3,329,155 | $180,001 | PASS | FAIL | **dropped** |

**Eligibility counts:**
- Coin-count vol-ON: **12 of 14** (UMA, YZY fail)
- USD-notional vol-ON: **5 of 14** (BIO, BLUR, CHIP, DOT, MET)
- **Δ: 7 newly dropped** (ALT, BLAST, MOVE, SAGA, STABLE, SUPER, ZETA), **0 newly added**.

Per paper ledger §6 of the D45 audit: all 7 newly-dropped assets do have
live paper opens (SUPER 2 clean + 1 open; MOVE 1; SAGA 1; STABLE 1;
ALT 1; BLAST 1; ZETA 2). Under the honest static-USD filter they would
not have been eligible in backtest. Paper catches them because live
`dayNtlVlm` is time-varying — memecoin ignition windows briefly spike
above $500K even when the 24h static proxy does not.

---

## 4. Paper transfer check

Paper ledger at pin: **n=21 clean closes, PF = 1.063** (source:
`analysis/snapshots/20260422T202943Z/paper_trades.jsonl`, recomputed this
session, exit_reason filter excludes `admin_*`).

| Config | Backtest PF | Paper PF | Δ | Within ±0.2 ? |
|:-|-:|-:|-:|:-:|
| Path A vol-ON (corrected) | 1.4665 | 1.063 | 0.404 | **NO** |
| Path B vol-ON (corrected) | 1.1370 | 1.063 | 0.074 | **YES** |
| Path A vol-OFF (sensitivity) | 0.8234 | 1.063 | 0.240 | NO (borderline) |
| Path B vol-OFF (sensitivity) | 0.8359 | 1.063 | 0.227 | NO (borderline) |

Only **Path B vol-ON** transfers within ±0.2 — as in the D44 REPORT, and
the transfer story is unchanged by the D45 engine patch (the cohort
driver was already USD-semantic).

**Concurrency caveat (from the parallel D45 concurrency audit):**
paper PF 1.063 at n=21 is a measurement of a *multi-position* strategy
(23 clean×clean overlap pairs detected; 3 concurrently open right now).
Under first-in-wins `MAX_CONCURRENT=1` enforcement the surviving-cohort
paper PF jumps to 1.445 at n=7 — this shifts the Δ table. Any verdict
citing the paper PF 1.063 figure as ground truth needs to state which
policy it measures.

---

## 5. Verdict class under D43 pre-registered rule (on corrected numbers)

Pre-registered thresholds (§6 of D43 path-decision spec):

| PF_A (vol-ON) | PF_B (vol-ON) | Class |
|:-:|:-:|:-|
| ≥ 1.30 | ≥ 1.30 | Path B wins (broader cohort) |
| **≥ 1.30** | **< 1.30** | **Path A defensible** |
| < 1.30 | ≥ 1.30 | Path B wins |
| < 1.30 | < 1.30 | pause/pivot, not A-vs-B |
| 1.0–1.30 (both) | 1.0–1.30 (both) | genuine tradeoff, operator calls |

**Corrected cohort reads:** PF_A = **1.4665** (≥ 1.30 ✅), PF_B = **1.1370**
(< 1.30 ❌) → **PATH A DEFENSIBLE** per the pre-registered rule.

**Caveats that do not change the rule output but limit its weight:**
1. Only 3 cohort assets fire under Path A (BIO, BLUR, MET). Path A's 1.47 is
   effectively a BLUR-and-BIO edge claim.
2. Paper PF 1.063 does not transfer within ±0.2 to Path A's 1.47 — the 0.41
   gap is plausibly driven by (a) MET −$224.07 cadence-overrun (exit-engineering
   issue, not funding-threshold issue) and (b) paper catching ignition-window
   volume that the static 24h backtest proxy misses.
3. Under enforced `MAX_CONCURRENT=1`, paper cohort is n=7 with PF 1.445 —
   n below any credible primary gate; the single-position paper signal is
   too thin to prefer either path over the other yet.
4. D43’s HL 8× under-annualization is the other open correctness bug;
   the cohort driver’s pre-scale-by-8 trick neutralizes it here, but the
   live pipeline still has the bug. Any Path A authorization based on this
   report MUST be paired with the D43 fix-the-three-sites work.

---

## 6. Three D44 draft variants (operator selects — **do NOT append here**)

### 6a. Path A selected (follows pre-registered rule mechanically)

> ## D44 — Path A selected: preserve 800% TRUE APY effective entry bar
> **Date:** 2026-04-22 UTC.
> **Status:** PATH A SELECTED. Cohort backtest PF 1.47 ≥ 1.30 primary gate (n=36, WR 75%, max DD 0.04%) under the corrected USD-notional volume filter (D45). Path B PF 1.14 fails the gate. Pre-registered rule yields "Path A defensible".
> **Caveats accepted:** (1) paper transfer is Δ=0.404 (outside ±0.2); (2) corresponding paper cohort under enforced MAX_CONCURRENT=1 is n=7 (below any credible primary gate floor); (3) MET −$224 cadence-overrun is an unresolved exit-engineering artifact unrelated to the funding threshold; (4) D43 HL 8× under-annualization must still be fixed at the three live sites — this decision authorizes the rate×8 retune coupled with that fix.
> **Next actions:** fix D43 three sites AND 8× TIER1/TIER2_MIN_FUNDING so effective bar stays ~800% TRUE APY. Retire contaminated D41 secondary / D42 Phase A UNKNOWN verdicts under corrected math. Fix the `MAX_CONCURRENT=1` enforcement gap per the D45 concurrency audit before any real-money arm.

### 6b. Path B selected (flag — unsupported by pre-registered rule)

> ## D44 — Path B selected: restore 100% TRUE APY entry bar
> **Date:** 2026-04-22 UTC.
> **Status:** PATH B SELECTED — **WARNING: unsupported by the pre-registered rule**. Cohort PF is 1.14 (vol-ON) / 0.84 (vol-OFF), both below the 1.30 primary gate. Operator must attach rationale (e.g. paper-transfer quality, breadth preference).

### 6c. Pause / pivot

> ## D44 — Edge too thin to decide; pause and re-scope
> **Date:** 2026-04-22 UTC.
> **Status:** NEITHER PATH CLEARS THE BAR AT USABLE N. Path A clears PF 1.30 at n=36 on 3 cohort assets; paper under enforced MAX_CONCURRENT=1 is n=7 PF 1.445; vol-OFF cohort PFs are 0.82/0.84 (both < 1.0).
> **What is decided:** No fix to D43’s three sites yet. Paper trader continues DRY_RUN unchanged. Real-money switch remains blocked.
> **Required pre-D45 analyses:** (a) MAX_CONCURRENT=1 enforcement fix (per D45 concurrency audit); (b) exit-cadence engineering (MET-class SL overruns); (c) grid search (min_apy × min_volume_usd) on cohort 180d for any configuration that clears 1.30 with n ≥ 30.

---

## 7. End-of-session deltas vs D44 REPORT

| Change | Before (D44) | After (D45) |
|:-|:-|:-|
| `engine.estimate_volumes` units | base-asset coin count | USD notional |
| Cohort driver `usd_volume_estimator` semantic | USD notional (helper) | USD notional (helper, now redundant with engine default) |
| Cohort PF_A vol-ON | 1.47 | **1.4665** (same, at more decimal places) |
| Cohort PF_B vol-ON | 1.14 | **1.1370** (same) |
| Cohort PF_A vol-OFF | 0.82 | **0.8234** (same) |
| Cohort PF_B vol-OFF | 0.84 | **0.8359** (same) |
| Tests | 345 passed | **354 passed** (+9 new) |
| Verdict class | "Path A defensible" (modulo vol-filter dispute) | **"Path A defensible" — no vol-filter dispute remains** |

---

## 8. Artifacts

- Patch: `scripts/backtest/engine.py:618-633` (11 lines changed)
- Tests: `tests/test_backtest_volume_semantic.py` (9 cases)
- Rerun results: `analysis/cohort_backtest/results.json` (4 configs)
- Driver (unchanged): `analysis/cohort_backtest/run_cohort_backtest.py`
- Fresh paper snapshot: `analysis/snapshots/20260422T202943Z/paper_trades.jsonl`
  sha256 `5a85d82…`
- Concurrency audit (parallel D45 session): `analysis/concurrency_audit/REPORT.md`

---

## One-sentence D44 recommendation

**Select Path A** per the pre-registered rule on the semantically-honest
numbers (PF_A = 1.47 ≥ 1.30, PF_B = 1.14 < 1.30), **conditional on** a
paired fix of D43’s three under-annualization sites and the `MAX_CONCURRENT=1`
enforcement gap from the D45 concurrency audit — both of which materially
affect the live pipeline’s actual behavior at production scale.
