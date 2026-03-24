# Truth-First Improvement Plan

**Audit date:** 2026-03-23 UTC  
**Scope:** local checkout plus direct runtime verification in this environment  
**Standard:** truth-first repo audit grounded in code, tests, CI, and runtime checks only

## A. Executive verdict

This repository is a **well-documented paper-trading research system with a real canonical operator loop and strong offline proof coverage**, but it is **not live-trading capable, not real-money capable, and not production-ready**. The strongest proven path is the Hyperliquid paper loop. Polymarket is implemented in the same canonical paper architecture, but it remains experimental overall and public-data-only. Mixed mode is real but intentionally constrained to a single new entry per cycle with deterministic Hyperliquid priority. CI proves offline behavior, not current exchange compatibility.

## Current implementation status after executing P0/P1 work

- Active truth terminology is now standardized across the main non-archived truth docs.
- Default CI compile validation now excludes archived scripts.
- Canonical position-state recovery is now proven offline for malformed, missing, and drifted state through append-only trade-history replay.
- Live runtime compatibility remains unproven in this environment because read-only connectivity checks still fail with proxy tunnel `403` errors.

## B. Canonical architecture map

### Canonical operator path

1. `scripts/trading-agency-phase1.py`  
   Canonical entrypoint and stage orchestrator.
2. `scripts/bootstrap-runtime-check.py`  
   Dependency/bootstrap gate only.
3. `scripts/data-integrity-layer.py`  
   Pre-scan source health and per-signal integrity validation.
4. `scripts/phase1-signal-scanner.py`  
   Hyperliquid / Polymarket paper signal generation.
5. `scripts/execution-safety-layer.py`  
   Single-candidate safety validation and breaker accounting.
6. `scripts/phase1-paper-trader.py`  
   Entry/exit planning, candidate selection, persistence hooks.
7. `models/trade_schema.py` + `models/position_state.py`  
   Canonical normalization and authoritative open-position state.
8. `scripts/timeout-monitor.py`  
   Canonical monitor stage only; monitoring, not authoritative close persistence.

### Canonical state and generated runtime artifacts

- `workspace/logs/phase1-signals.jsonl`
- `workspace/logs/phase1-paper-trades.jsonl`
- `workspace/logs/position-state.json`
- `workspace/logs/phase1-performance.json`
- `workspace/logs/execution-safety-state.json`
- `workspace/logs/agency-phase1-report.json`
- `workspace/logs/agency-cycle-summary.json`
- `workspace/AGENCY_CYCLE_SUMMARY.md`
- `workspace/TIMEOUT_MONITOR_REPORT.md`

### Non-canonical or support-only surfaces that still matter

- `scripts/exit-monitor.py` — explicitly skipped by the canonical loop.
- `scripts/live-readiness-validator.py` — future-scope/support-only.
- `scripts/stability-monitor.py`, `scripts/supervisor-governance.py`, `scripts/performance-dashboard.py`, `scripts/position-exit-tracker.py`, `scripts/enhanced-exit-capture.py`, `scripts/exit-safeguards.py`, `scripts/alpha-intelligence-layer.py`, `scripts/portfolio-allocator.py` — support / research surfaces, not canonical execution.
- `scripts/archive/` and `docs/archive/` — historical only.

### Ownership / surface-shape reality

The repository is unusually heavy on truth, audit, and remediation docs. That improves honesty, but it also means reviewers must distinguish between:
- active truth docs,
- historical audit docs,
- support-only scripts,
- canonical runtime code.

That distinction is mostly documented, but not fully encoded in layout or CI boundaries.

## C. Gap matrix

| Area | Current state | Proven? | Risk | Recommended action |
|---|---|---|---|---|
| Canonical entrypoint | `scripts/trading-agency-phase1.py` orchestrates the full paper loop. | Yes, offline | Medium | Keep this as the only operator entrypoint and remove ambiguity from side scripts. |
| Bootstrap/runtime checks | Dependency-only bootstrap; does not prove exchange reachability. | Yes, offline | Medium | Keep truth wording sharp; do not let bootstrap be interpreted as runtime readiness. |
| Data-integrity gate | Mode-aware pre-scan source checks and signal validation are implemented. Mixed mode treats Polymarket health as advisory when Hyperliquid is enabled. | Yes, offline | Medium | Add optional live-shape drift checks outside blocking CI. |
| Signal generation | Hyperliquid and Polymarket scanners produce canonical paper signals and persist only integrity-approved signals. | Yes, offline | Medium | Add optional non-blocking live-shape contract checks; keep scanner acceptance aligned with trader contracts. |
| Safety validation | Strong offline blocker coverage for stale signals, duplicates, breaker conditions, and capacity. | Yes, offline | Medium-High | Expand negative-path coverage for monitor failures, corrupt state, and restart edge cases. |
| Trade planning / persistence | Canonical paper-trader writes append-only trades and authoritative open state through normalized schemas, and canonical readers can now recover open positions from append-only trade history after malformed/missing/drifted state. | Yes, offline | Medium | Extend recovery proof to additional restart edge cases and monitor-stage failures. |
| Monitoring | `timeout-monitor.py` runs in canonical loop; `exit-monitor.py` is skipped as non-canonical. | Timeout monitor: yes, offline. Exit persistence: no, by design | Medium | Make canonical/non-canonical monitor boundaries even more obvious in docs and script layout. |
| Hyperliquid path | Best-supported canonical paper path. | Yes, offline and repeat-cycle | Low-Medium | Use this as the primary portfolio/demo proof path. |
| Polymarket path | Canonical paper path, experimental overall, public-data-only, no authenticated execution. | Yes, paper only | High | Do not overstate integration; either keep paper-only or define a real execution roadmap. |
| Mixed mode | Limited deterministic evaluation path; one new entry per cycle; Hyperliquid priority. | Yes, limited offline proof | High | Either keep explicitly limited, or redesign with explicit peer-symmetric semantics and new proofs. |
| CI | Full offline proof suite runs and passes; default compile validation now targets active runtime/support code rather than archived scripts. | Yes, offline only | Low-Medium | Keep active-vs-archive CI scope explicit as the repo evolves. |
| Live runtime proof | Optional connectivity script exists, but current environment check failed for both exchanges with proxy 403 tunneling errors. | No | High | Preserve “offline proof only” wording; add optional manual live-shape verification with archived results clearly labeled. |
| Truth surfaces | Active truth docs now use the same paper-only wording for live trading, real-money execution, and Polymarket scope. | Yes | Low | Preserve this with guard coverage as docs evolve. |
| Monetization readiness | Demo/research narrative is credible; sellable live-trading claims are not. | Partially | High | Monetize research outputs first, not execution claims. |

## D. Improvement roadmap

### P0 — truth / safety / clarity fixes

#### 1. Standardize active truth terminology across all non-archived docs — **completed**
- **Problem:** Active docs previously mixed precise wording (`not live-integrated`, `paper only`, `not implemented`) with looser wording (`not live-ready`, `non-live-ready`).
- **Why it matters:** The repo has invested heavily in truthfulness; terminology drift recreates truth debt even when the direction is honest.
- **Exact files likely involved:** `docs/OPERATOR_QUICKSTART.md`, `docs/REPO_TRUTHFULNESS_AUDIT.md`, `docs/OPERATOR_EVIDENCE_GUIDE.md`, `docs/POLYMARKET_EXECUTION_SCOPE.md`, possibly `docs/SYSTEM_ARCHITECTURE.md`.
- **Risk level:** Low.
- **Estimated difficulty:** Low.
- **Expected impact:** High truth-surface consistency.
- **Proof of completion:** A guard test asserts the exact canonical wording across all active truth docs, not only README/system-status surfaces.

#### 2. Split canonical runtime code from support-only scripts at the directory level
- **Problem:** Many support-only scripts live beside canonical runtime files under `scripts/`, which blurs review boundaries.
- **Why it matters:** Reviewers can still infer importance from filenames and proximity, even when docs warn otherwise.
- **Exact files likely involved:** move or re-home `scripts/stability-monitor.py`, `scripts/supervisor-governance.py`, `scripts/performance-dashboard.py`, `scripts/position-exit-tracker.py`, `scripts/enhanced-exit-capture.py`, `scripts/exit-safeguards.py`, `scripts/alpha-intelligence-layer.py`, `scripts/portfolio-allocator.py`; update `README.md`, `TRUTH_INDEX.md`, `docs/SYSTEM_ARCHITECTURE.md`, tests that reference paths.
- **Risk level:** Medium.
- **Estimated difficulty:** Medium.
- **Expected impact:** High review clarity; lower truth debt.
- **Proof of completion:** Canonical path remains unchanged, support scripts live in a separate namespace, and truth docs reflect the new layout.

#### 3. Stop compiling archived scripts in the default CI verification path — **completed**
- **Problem:** `compileall` previously traversed `scripts/`, which included `scripts/archive/` even though archive material is historical only.
- **Why it matters:** Historical code can still fail CI or give the impression it remains part of the active quality bar.
- **Exact files likely involved:** `scripts/ci-safe-verification.sh`, `.github/workflows/basic.yml`.
- **Risk level:** Low.
- **Estimated difficulty:** Low.
- **Expected impact:** Medium; sharper canonical CI scope.
- **Proof of completion:** CI compiles only active runtime/support code explicitly, with archive coverage moved to optional/manual checks if desired.

#### 4. Add a truth-guard for non-canonical monitor wording
- **Problem:** `exit-monitor.py` is correctly skipped, but monitor truth depends on docs and inline strings rather than explicit guard coverage.
- **Why it matters:** Monitoring/proof scripts are easy places for future overstatement.
- **Exact files likely involved:** `tests/repo-truth-guard-test.py`, `scripts/trading-agency-phase1.py`, `scripts/exit-monitor.py`, `docs/RUNTIME_OBSERVABILITY.md`.
- **Risk level:** Low.
- **Estimated difficulty:** Low.
- **Expected impact:** Medium.
- **Proof of completion:** Test fails if `exit-monitor.py` is presented as canonical persistence or if orchestrator stops explicitly skipping it.

### P1 — canonical execution reliability

#### 5. Add restart/recovery tests around partially written or corrupted canonical state — **completed for malformed/missing/drifted state replay**
- **Problem:** Proof was strong for happy-path and selected negative-path runs, but not for corrupt JSON/JSONL, partial writes, or interrupted cycles.
- **Why it matters:** Operator trust depends on state recovery, not only clean isolated runs.
- **Exact files likely involved:** `models/position_state.py`, `models/trade_schema.py`, `utils/json_utils.py`, new destructive tests under `tests/destructive/`.
- **Risk level:** Medium.
- **Estimated difficulty:** Medium.
- **Expected impact:** High operational confidence.
- **Proof of completion:** Destructive tests simulate malformed trade history, malformed position state, truncated JSONL, and interrupted-cycle replay without silent corruption.

#### 6. Add multi-cycle mixed-mode orchestrator tests with restart semantics
- **Problem:** Mixed mode is proven for current limitation and cross-exchange state integrity, but not for restart/recovery over multiple orchestrated cycles.
- **Why it matters:** Mixed mode is the most semantically fragile path in the repo.
- **Exact files likely involved:** `tests/destructive/trading-agency-mixed-test.py`, new mixed-mode multi-cycle test, `scripts/trading-agency-phase1.py`, `scripts/phase1-paper-trader.py`.
- **Risk level:** Medium.
- **Estimated difficulty:** Medium.
- **Expected impact:** High for the repo’s most ambiguous path.
- **Proof of completion:** Test proves deterministic winner selection, no duplicate leakage, and intact shared canonical state across several restarts/cycles.

#### 7. Add canonical tests for monitor-stage failure handling
- **Problem:** The orchestrator truthfully runs monitor stage last, but there is little explicit proof for timeout-monitor failures/timeouts beyond code paths.
- **Why it matters:** A broken monitor should not retroactively cast doubt on persisted trade/state truth.
- **Exact files likely involved:** `scripts/trading-agency-phase1.py`, `scripts/timeout-monitor.py`, new destructive test(s).
- **Risk level:** Medium.
- **Estimated difficulty:** Medium.
- **Expected impact:** Medium-High.
- **Proof of completion:** Test forces timeout-monitor non-zero exit and timeout conditions, then asserts report/cycle summary remain truthful about persistence vs monitoring failure.

#### 8. Replace hard-coded balance assumptions with explicit paper-account state
- **Problem:** The trader and safety layer still rely on static paper balance / peak-balance defaults rather than an explicit evolving paper account model.
- **Why it matters:** Current performance/safety semantics are coherent enough for paper proof, but capital/risk accounting is still partly synthetic.
- **Exact files likely involved:** `scripts/phase1-paper-trader.py`, `scripts/execution-safety-layer.py`, `models/` or new `workspace/logs/paper-account.json`, tests.
- **Risk level:** Medium.
- **Estimated difficulty:** Medium.
- **Expected impact:** High on execution realism without crossing into live-trading claims.
- **Proof of completion:** Paper account state becomes explicit, updated from canonical closed trades, and used by safety/trader sizing logic under test.

### P2 — test / proof expansion

#### 9. Add optional non-blocking live-shape contract checks for public APIs
- **Problem:** The repo currently has offline proof and an optional connectivity check, but no structured non-blocking contract check for current payload shapes.
- **Why it matters:** CI can stay offline-safe while still providing a truthful manual proof path for “public endpoint shape still matches expectations.”
- **Exact files likely involved:** new `tests/nonblocking/` or `scripts/manual-live-shape-check.py`, `utils/api_connectivity.py`, `docs/OPERATOR_EVIDENCE_GUIDE.md`, `PROOF_MATRIX.md`.
- **Risk level:** Medium.
- **Estimated difficulty:** Medium.
- **Expected impact:** High truth value; medium engineering value.
- **Proof of completion:** Manual command records pass/fail against current public response shape for Hyperliquid and Polymarket without being treated as live-trading proof.

#### 10. Extend proof matrix to distinguish code existence vs deterministic offline proof vs manual live-shape proof
- **Problem:** The repo already tries to do this, but several docs still compress proof categories together.
- **Why it matters:** Reviewers need a one-glance proof taxonomy.
- **Exact files likely involved:** `PROOF_MATRIX.md`, `TRUTH_INDEX.md`, `docs/OPERATOR_EVIDENCE_GUIDE.md`, `README.md`.
- **Risk level:** Low.
- **Estimated difficulty:** Low.
- **Expected impact:** Medium-High.
- **Proof of completion:** Every major claim is tagged with proof type and explicit “not proven” boundaries.

#### 11. Add negative-path tests for invalid operator controls and health overrides in the agency loop
- **Problem:** `SystemHealthManager` has meaningful operator-control logic, but the canonical agency-loop proof emphasis is still mostly trading-path-centric.
- **Why it matters:** Operator override handling is part of the real execution boundary.
- **Exact files likely involved:** `utils/system_health.py`, `scripts/trading-agency-phase1.py`, new destructive tests.
- **Risk level:** Medium.
- **Estimated difficulty:** Medium.
- **Expected impact:** Medium.
- **Proof of completion:** Tests cover invalid operator control values, halt-new-trades override, and degraded/critical hold semantics at the agency entrypoint.

### P3 — operator UX / reporting / observability

#### 12. Add a single canonical operator evidence dashboard artifact
- **Problem:** Evidence is spread across JSON, JSONL, Markdown summaries, runtime events, safety state, and system status.
- **Why it matters:** The repo is strongest when reviewed as an evidence-backed research system, but the evidence is distributed.
- **Exact files likely involved:** `scripts/trading-agency-phase1.py`, new support renderer, `docs/RUNTIME_OBSERVABILITY.md`.
- **Risk level:** Low-Medium.
- **Estimated difficulty:** Medium.
- **Expected impact:** High for demos and operator comprehension.
- **Proof of completion:** One generated artifact links current cycle result, persistence state, safety summary, monitor summary, and truth disclaimers.

#### 13. Make cycle summaries explicitly identify what was proven this run vs historically proven
- **Problem:** Current cycle summary is good operationally, but it does not clearly separate “this run did X” from “the repo has historical proof of Y.”
- **Why it matters:** That distinction is core to truth-first presentation.
- **Exact files likely involved:** `scripts/trading-agency-phase1.py`, `workspace/AGENCY_CYCLE_SUMMARY.md` format docs.
- **Risk level:** Low.
- **Estimated difficulty:** Low-Medium.
- **Expected impact:** Medium.
- **Proof of completion:** Summary template includes sections for current-cycle actions, current-cycle failures, and out-of-scope/unproven capabilities.

#### 14. Fix timezone labeling and operator-facing message precision
- **Problem:** Some runtime output uses `EDT` formatting while the audit environment and several artifacts are UTC-based.
- **Why it matters:** Time ambiguity weakens operator trust and complicates audits.
- **Exact files likely involved:** `scripts/trading-agency-phase1.py`, `scripts/execution-safety-layer.py`, any report generators with `EDT` labels.
- **Risk level:** Low.
- **Estimated difficulty:** Low.
- **Expected impact:** Medium.
- **Proof of completion:** Generated timestamps use an explicit consistent timezone label and are covered by simple tests/string guards where practical.

### P4 — monetization-enabling productization

#### 15. Package the Hyperliquid paper runtime + proof suite as a research/demo product
- **Problem:** The repo’s strongest asset is evidence-backed paper execution, but the packaging still looks like an internal engineering repo.
- **Why it matters:** This is the fastest credible path to monetizable value.
- **Exact files likely involved:** `README.md`, `docs/OPERATOR_QUICKSTART.md`, `docs/OPERATOR_EVIDENCE_GUIDE.md`, new demo bundle docs/artifacts.
- **Risk level:** Low-Medium.
- **Estimated difficulty:** Medium.
- **Expected impact:** High for portfolio/demo sales.
- **Proof of completion:** A buyer/reviewer can run the offline proof suite, inspect artifacts, and understand exact limitations without reading the entire repo.

#### 16. Build a sellable signal/intelligence layer before any execution-commercialization attempt
- **Problem:** There is no truthful basis yet for selling this as live execution software.
- **Why it matters:** The current codebase is much closer to “signal research and evidence packaging” than to “automated broker/exchange execution.”
- **Exact files likely involved:** `scripts/alpha-intelligence-layer.py`, `scripts/performance-dashboard.py`, new export/reporting surfaces, docs.
- **Risk level:** Medium.
- **Estimated difficulty:** Medium-High.
- **Expected impact:** High if productized carefully.
- **Proof of completion:** Signals, rankings, and paper outcomes can be exported as a clear research/intelligence deliverable with explicit paper-only disclaimers.

#### 17. Do not pursue live execution commercialization until an explicit execution state model exists
- **Problem:** There is no order lifecycle, fill reconciliation, wallet/signing, or settlement model.
- **Why it matters:** Anything sold as live execution before that would be misleading.
- **Exact files likely involved:** future-scope only; would require new canonical modules, state models, tests, and secrets/config handling.
- **Risk level:** High.
- **Estimated difficulty:** High.
- **Expected impact:** Potentially high, but only after major build-out.
- **Proof of completion:** Order placement, acknowledgements, fills, cancellations, settlement, and exchange-reconciled state all exist and are tested in a controlled non-paper environment.

## E. Top 10 highest-value fixes

**Completed in this revision:** items 1, 2, and 3 below.

1. **Standardize active truth terminology across all non-archived docs.**  
   Highest impact per effort because the repo’s brand is truthfulness.
2. **Stop compiling archived scripts in default CI.**  
   Cheap clarity win; reduces confusion about what is active.
3. **Add restart/corrupt-state destructive tests.**  
   Biggest operational-proof gap on the canonical path.
4. **Add multi-cycle mixed-mode restart proof.**  
   Best way to contain the repo’s most fragile semantics.
5. **Replace static paper balance assumptions with explicit paper-account state.**  
   Improves safety realism without overstating scope.
6. **Add monitor-stage failure tests.**  
   Preserves truthful reporting under partial failure.
7. **Add optional non-blocking live-shape contract checks.**  
   Best way to improve evidence without pretending CI is live validation.
8. **Split support-only scripts into a separate namespace.**  
   Large clarity payoff for reviewers and future maintainers.
9. **Add operator-control negative-path tests.**  
   Important because health overrides are part of the real control surface.
10. **Create a single operator evidence dashboard artifact.**  
   Highest demo/portfolio payoff once truth is tightened.

## F. Monetization reality check

### Credibly monetizable now

#### Portfolio / demo positioning
Yes.
- Best positioning: **truthful paper-trading research system with deterministic offline proof and a canonical operator loop**.
- Strongest asset: Hyperliquid paper path with good documentation and repeat-cycle offline validation.
- Best audience: hiring managers, technical reviewers, quantitative research audiences, consultants evaluating engineering rigor.

#### Research product
Yes, with modest packaging work.
- Best positioning: **signal generation + paper execution + evidence-backed monitoring for research workflows**.
- Sellable angle: research tooling, auditability, reproducible paper workflows, exchange-comparison experimentation.

#### Signal / intelligence product
Potentially yes, sooner than execution monetization.
- Best positioning: curated signals, exchange observations, ranked opportunities, paper outcome reporting.
- Requirement: stronger reporting/export packaging and very explicit paper-only disclaimers.

### Not credibly monetizable now

#### Live trading system
No.
- No live order placement.
- No auth/signing.
- No fill reconciliation.
- No settlement.
- No live integration proof.

#### Real-money autonomous execution
No.
- Unsupported by code, tests, docs, and runtime evidence.

#### Production SaaS for automated exchange execution
No.
- Missing execution state model, operations model, secrets handling, recovery model, live validation, and deployment truth.

### Fastest credible monetization path

**Sell the system as a paper-trading research and signal-intelligence product, not as execution software.**

Most credible near-term packaging:
1. Hyperliquid-first evidence-backed demo.
2. Optional Polymarket paper-research comparison mode.
3. Exportable intelligence/report artifacts.
4. Proof bundle showing deterministic offline verification.

## G. Truth-first rewrite recommendations

### Update first
1. `docs/OPERATOR_QUICKSTART.md`
   - Replace “not live-ready” with sharper wording: live trading not implemented; real-money execution not supported; Polymarket not live-integrated.
2. `docs/REPO_TRUTHFULNESS_AUDIT.md`
   - Replace “non-live-ready” with the same exact canonical wording used in README/status surfaces.
3. `PROOF_MATRIX.md`
   - Add an explicit proof-type column: code existence / offline deterministic proof / manual live-shape proof / unproven.
4. `TRUTH_INDEX.md`
   - Add a short “review this, ignore that” table with canonical/support/archive buckets.
5. `README.md`
   - Add one short section clarifying that support scripts remain in `scripts/` for convenience but are not canonical execution.
6. `docs/SYSTEM_ARCHITECTURE.md`
   - Add a short “failure/recovery proof gaps” subsection so architecture truth includes what is still not proven.
7. `docs/RUNTIME_OBSERVABILITY.md`
   - Clarify that runtime summaries are operator evidence artifacts, not proof of live exchange compatibility.
8. `scripts/ci-safe-verification.sh`
   - If CI scope is narrowed, update the wording so the command lists only active canonical/support proof surfaces.

## Remaining mismatches and truth debt

1. **Support-only script placement remains a review hazard.**  
   The repo tells the truth about non-canonical tools, but the directory layout still makes them look peer-level with the canonical path.
2. **Live-shape compatibility remains unproven.**  
   The optional runtime connectivity check failed in this environment for both exchanges, and CI intentionally does not prove runtime reachability.
3. **Mixed mode remains the largest semantics debt.**  
   It is documented honestly, but still easy for outsiders to overread as “both exchanges run together.”

## Single best next implementation task

**Replace static paper-balance assumptions with explicit paper-account state.**

### Why this should come first

Because the repository now has stronger truth surfaces, sharper CI scope, and explicit offline proof for canonical state recovery, the highest-value remaining P1 gap is **risk and capital accounting that still depends on static paper-balance assumptions instead of an explicit evolving paper account**. Fixing that improves execution realism, safety accounting, and operator trust without making any unproven live-trading claim.
