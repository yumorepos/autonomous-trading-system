# Truth-First Repository Audit and Improvement Plan (2026-03-24)

## A) Executive Verdict

This repository is a **well-structured paper-trading research system** with a clearly defined canonical orchestrator and meaningful offline destructive tests, but it is **not live-trading capable** and **not production-ready**. The strongest evidence is offline, fixture-driven, and focused on deterministic behavior of canonical paper paths (especially Hyperliquid), with Polymarket explicitly canonical-for-paper yet experimental overall, and mixed mode intentionally limited/asymmetric.

## B) Canonical Architecture Map

### Canonical operator path (implemented)

1. **Entrypoint**: `scripts/trading-agency-phase1.py`
2. **Bootstrap check**: runs `scripts/bootstrap-runtime-check.py`
3. **Data integrity gate**: loads `scripts/data-integrity-layer.py` and runs `run_pre_scan_gate(...)`
4. **Signal scanner**: subprocess call to `scripts/phase1-signal-scanner.py`
5. **Safety validation**: loads `scripts/execution-safety-layer.py` and validates selected candidate
6. **Trader planning**: loads `scripts/phase1-paper-trader.py` and builds execution plan
7. **Authoritative persistence**: `phase1-paper-trades.jsonl`, `position-state.json`, `phase1-performance.json`
8. **Monitoring stage**: executes `scripts/timeout-monitor.py`; explicitly skips `scripts/exit-monitor.py` in canonical loop
9. **Cycle reporting**: writes `workspace/logs/agency-cycle-summary.json`, `workspace/AGENCY_CYCLE_SUMMARY.md`, `workspace/logs/agency-phase1-report.json`

### Canonical state files

- `workspace/logs/phase1-signals.jsonl`
- `workspace/logs/phase1-paper-trades.jsonl`
- `workspace/logs/position-state.json`
- `workspace/logs/phase1-performance.json`
- `workspace/logs/execution-safety-state.json`
- `workspace/logs/agency-cycle-summary.json`
- `workspace/logs/agency-phase1-report.json`

### Mode model (implemented)

- `hyperliquid_only`: strongest canonical proof path.
- `polymarket_only`: canonical paper path, experimental overall.
- `mixed`: limited deterministic mode with one new entry per cycle and Hyperliquid priority.

### Non-canonical/support surfaces (present but outside canonical execution)

- `scripts/live-readiness-validator.py`
- `scripts/exit-monitor.py`
- `scripts/support/stability-monitor.py`
- `scripts/support/supervisor-governance.py`
- `scripts/archive/`
- `docs/archive/`

## C) Repo Structure Audit Findings

### What is clean and coherent

- Canonical path naming is explicit across README + truth docs + orchestrator.
- Core architecture separation is understandable (`config/`, `models/`, `scripts/`, `utils/`, `tests/`, `workspace/`).
- Contract centralization exists in `models/paper_contracts.py`, reducing schema drift risk.
- CI runner (`.github/workflows/basic.yml`) consistently invokes one deterministic verification shell script.

### Duplication / truth-surface sprawl

The repository has many overlapping truth documents with similar claims and dates:

- `README.md`, `SYSTEM_STATUS.md`, `TRUTH_INDEX.md`, `PROOF_MATRIX.md`, `EXECUTION_TRUTH_MAP.md`, `docs/SYSTEM_ARCHITECTURE.md`, `docs/REPO_TRUTHFULNESS_AUDIT.md`, `REMEDIATION_PLAN.md`, `INTEGRATION_GAP_MATRIX.md`, `CODEX_AUDIT_REPORT.md`, plus archived historical truth snapshots.

This is mostly intentional, but creates **truth-maintenance overhead** and raises drift risk when one surface updates later than others.

### Potential dead/stale or confusing surfaces

- `workspace/README.md` and top-level docs can create dual ownership of runtime guidance.
- `docs/archive/root-history/README.md` plus numerous historical audits can be misread as current unless reviewers follow `TRUTH_INDEX.md` strictly.
- Script names like `live-readiness-validator.py` remain potentially misleading despite improved header disclaimers.

### Ownership clarity issues

- No single machine-checkable source of truth for all claim statements (the docs are human-aligned but not generated from one canonical manifest).
- CI validates wording in selected surfaces, but not all long-form docs with architecture/status language.

## D) Execution-Path Assessment (Truth-by-stage)

### 1) Bootstrap/runtime checks

**Implemented:** orchestrator hard-runs bootstrap script and aborts early on failure.

**Robustness:** good fail-fast behavior.

**Fragility:** bootstrap checks dependency presence only; does not prove full runtime environment parity beyond module availability.

### 2) Signal scanning

**Implemented:** mode-aware scanner collects Hyperliquid and/or Polymarket opportunities; applies integrity validation before persistence.

**Robustness:** scanner enforces canonical contract validation before appending accepted signals.

**Fragility:** scanner relies on network APIs in real runs; CI proofs use offline fixtures, so live payload drift is not merge-blocking.

### 3) Integrity validation

**Implemented:** pre-scan gate validates API availability/freshness/completeness and supports mixed-mode advisory semantics for secondary source.

**Robustness:** explicit critical-vs-warning severity model and incident logging.

**Fragility:** threshold tuning is static; behavior under prolonged intermittent partial outages is only partially covered in tests.

### 4) Execution safety

**Implemented:** safety stage snapshots runtime state, refreshes breaker accounting from canonical history, and records blocked actions.

**Robustness:** structured transition persistence (`BEFORE_VALIDATION`, `VALIDATION_PASSED`, `BLOCKED_TRADE`, etc.) is strong for auditability.

**Fragility:** risk semantics remain paper-only abstractions; no live fill/latency/reconciliation risk controls exist.

### 5) Paper trade planning + persistence

**Implemented:** trader builds close-first then optional single-entry plan; authoritative writes happen only after trader success.

**Robustness:** append-only trade history + rebuildable position state is a strong paper architecture.

**Fragility:** consumed-signal dedupe by timestamp is simple; may be collision-prone in edge cases with generated fixtures or batched scans.

### 6) State updates

**Implemented:** centralized persistence and `synchronize_position_state(...)` recovery logic.

**Robustness:** destructive tests exercise malformed/missing/drifted state recovery.

**Fragility:** schema evolution versioning is partially handled, but long-term migration tooling is still lightweight.

### 7) Monitoring/reporting

**Implemented:** timeout monitor runs in canonical loop; exit-monitor is explicitly skipped to avoid over-claiming authoritative closes.

**Robustness:** cycle summary JSON + markdown gives operator-visible per-cycle truth.

**Fragility:** observability remains file-based with no event stream backend, no dashboard service SLOs, and no alert routing.

## E) Proof and Testing Assessment

### What has strong proof

- Deterministic offline CI-safe suite (`scripts/ci-safe-verification.sh`).
- Destructive isolated orchestrator tests for Hyperliquid, Polymarket, mixed mode, negative paths, repeat-cycle behavior, and state recovery.
- Explicit proof docs mapping claims to scripts/tests.

### Proof taxonomy (current state)

- **Code existence:** strong across canonical components.
- **Unit/integration proof:** moderate-to-strong via script-style tests and destructive isolated flows.
- **Deterministic offline proof:** strong (fixtures + patched requests).
- **Live runtime proof:** weak/absent by design; not claimed.

### Important negative paths still under-covered

1. Partial external API shape drift in one exchange while other remains healthy across multiple cycles.
2. Corrupted or out-of-order runtime event logs impacting safety/accounting observability.
3. Disk-full / write-permission failures during authoritative persistence.
4. Clock skew/timezone anomalies affecting freshness/timeout/decay logic.
5. Very large JSONL history performance/latency regression in orchestrator path.
6. Concurrent process access to canonical state files (race conditions) not deeply stress-tested.

### CI pass vs real-path unproven risks

- CI can pass entirely offline while real-world API contracts may have changed.
- CI does not validate external network reachability or latency characteristics.
- CI does not prove any live order-placement or fill reconciliation path (none implemented).

## F) Truth-Surface Audit

### Verified alignment (good)

README/system-truth docs consistently state:

- canonical entrypoint = `scripts/trading-agency-phase1.py`
- Hyperliquid canonical paper path
- Polymarket canonical paper path, experimental overall
- mixed limited/asymmetric
- CI offline proof only
- no live trading / real money support

### Truth debt / mismatch risks

1. **Date drift debt**: multiple dated audit docs can age at different rates.
2. **Terminology drift risk**: “canonical paper path” vs “experimental overall” appears consistent now but must remain synchronized across many files.
3. **Status duplication debt**: remediation and architecture/status docs overlap heavily.
4. **Future-scope script naming debt**: some support scripts still sound production-adjacent by filename.
5. **Proof-index fragmentation**: proof map exists, but discoverability still depends on reviewers reading several top-level docs.

## G) Product and Monetization Readiness Reality Check

### Ready now (credible)

1. **Portfolio/demo positioning:** yes.
   - Clear canonical architecture.
   - Deterministic offline evidence.
   - Truthful scope boundaries.

2. **Research product (internal/research-client):** near-ready.
   - Can package as a reproducible paper-trading research framework with auditable outputs.

### Partially ready (with focused packaging)

3. **Sellable signal/intelligence product:** early-stage feasible, if framed as research intelligence (not execution).
   - Needs better operator-grade reporting exports, dataset snapshots, and changelogged signal quality metrics.

### Not ready

- Live execution product.
- Real-money auto-trading service.
- “Production bot” claims.

### Fastest credible monetization path

**Sell a “truthful signal research + audit evidence package”** (subscription/reporting/API for paper-signal intelligence), not execution.

Why this path is fastest:
- Leverages strongest existing assets: canonical paper signals, persistence, cycle summaries, offline deterministic proof.
- Avoids largest engineering/compliance burden: live brokerage/exchange execution, auth, reconciliation, risk/compliance ops.

## H) Gap Matrix

| Area | Current state | Proven? | Risk | Recommended action |
|---|---|---|---|---|
| Canonical entrypoint clarity | Strong and explicit | Yes (docs + tests) | Low | Keep; add one auto-generated architecture index |
| Mixed-mode semantics | Explicitly limited/asymmetric | Yes (offline) | Medium (misinterpretation) | Encode one-line mixed disclaimer in all operator outputs |
| Signal integrity before persistence | Implemented and tested | Yes (offline) | Medium | Add live-shape nonblocking checks + fixture drift tests |
| Position-state recovery | Implemented, destructive tested | Yes (offline) | Medium | Add high-volume replay benchmark tests |
| Safety layer transitions | Structured persisted snapshots | Yes (offline) | Medium | Add corruption and file-write failure negative tests |
| Monitoring stage truthfulness | exit-monitor skipped canonically; timeout monitor runs | Yes (offline) | Low | Keep explicit skip reason in cycle summary JSON schema |
| CI proof scope | Strong offline coverage | Yes (offline) | Medium | Add clearly labeled optional online contract check workflow |
| Live runtime evidence | Not implemented | No | High (if overstated) | Keep hard truth boundaries; avoid live-readiness language in badges |
| Docs truth coherence | Generally aligned | Partially (manual) | Medium | Consolidate duplicated truth docs via single source manifest |
| Monetization readiness | Demo/research-ready; execution-not-ready | Partially | Medium-High | Productize intelligence/reporting layer, not execution |

## I) Improvement Roadmap (Prioritized)

### P0 — truth/safety/clarity fixes

1. **Title:** Create single machine-checkable truth manifest
- **Problem:** many docs repeat scope claims manually.
- **Why it matters:** prevents truth drift and accidental overstatement.
- **Files likely involved:** `TRUTH_INDEX.md`, `README.md`, `SYSTEM_STATUS.md`, `PROOF_MATRIX.md`, `tests/repo-truth-guard-test.py`, new `truth/claims.yaml`.
- **Risk:** Low.
- **Difficulty:** Medium.
- **Expected impact:** High.
- **Proof of completion:** one manifest drives generated snippets/checks; CI fails on mismatch.

2. **Title:** Standardize “offline-only proof” banner in every operator-facing report
- **Problem:** generated reports can be copied without context.
- **Why it matters:** reduces misuse as live-proof artifacts.
- **Files likely involved:** `scripts/trading-agency-phase1.py`, `scripts/timeout-monitor.py`, report markdown emitters.
- **Risk:** Low.
- **Difficulty:** Low.
- **Expected impact:** High trust protection.
- **Proof of completion:** report files include consistent scope header and test assertions enforce it.

3. **Title:** Rename or namespace future-scope scripts for clearer non-canonical status
- **Problem:** filenames like `live-readiness-validator.py` can still imply near-live status.
- **Why it matters:** naming is a truth surface.
- **Files likely involved:** `scripts/live-readiness-validator.py`, README/docs references, truth guards.
- **Risk:** Low.
- **Difficulty:** Low.
- **Expected impact:** Medium.
- **Proof of completion:** script moved to `scripts/support/` or renamed with `research-` prefix; docs/tests updated.

### P1 — canonical execution reliability

4. **Title:** Harden persistence failure handling in canonical writes
- **Problem:** write-path failures (disk/permissions) are not deeply tested.
- **Why it matters:** authoritative state corruption risk.
- **Files likely involved:** `utils/json_utils.py`, `scripts/phase1-paper-trader.py`, `scripts/trading-agency-phase1.py`, destructive tests.
- **Risk:** Medium.
- **Difficulty:** Medium.
- **Expected impact:** High.
- **Proof of completion:** deterministic tests simulate write failures and assert safe abort + clear status.

5. **Title:** Add explicit lock strategy for canonical state files
- **Problem:** concurrent process writes are not strongly guarded.
- **Why it matters:** race conditions can invalidate position-state truth.
- **Files likely involved:** `utils/json_utils.py`, `models/position_state.py`, trader/orchestrator persistence paths.
- **Risk:** Medium.
- **Difficulty:** Medium-High.
- **Expected impact:** High for reliability.
- **Proof of completion:** concurrency stress test demonstrates no corruption under parallel writes.

6. **Title:** Make dedupe semantics stronger than timestamp-only consumption
- **Problem:** consumed signal detection currently keys heavily on timestamp.
- **Why it matters:** duplicate/ambiguous signal ingestion risk.
- **Files likely involved:** `scripts/phase1-paper-trader.py`, `scripts/phase1-signal-scanner.py`, tests.
- **Risk:** Medium.
- **Difficulty:** Medium.
- **Expected impact:** Medium-High.
- **Proof of completion:** deterministic test with timestamp collision still prevents duplicate entry.

### P2 — test/proof expansion

7. **Title:** Add nonblocking live-shape contract check script/workflow
- **Problem:** API payload drift can break real runs while CI remains green.
- **Why it matters:** closes offline-vs-online blind spot without making CI flaky.
- **Files likely involved:** new `scripts/verify-live-shapes.py`, optional GitHub workflow/manual job, docs.
- **Risk:** Medium.
- **Difficulty:** Medium.
- **Expected impact:** High.
- **Proof of completion:** documented command validates key fields from current Hyperliquid/Polymarket payloads and outputs pass/fail report.

8. **Title:** Expand destructive tests for filesystem and malformed-history edge cases
- **Problem:** some operational failure paths are unproven.
- **Why it matters:** improves confidence in canonical robustness claims.
- **Files likely involved:** `tests/destructive/*`, `tests/support/*`.
- **Risk:** Low-Medium.
- **Difficulty:** Medium.
- **Expected impact:** High.
- **Proof of completion:** new negative tests for write failure, partial JSONL corruption, large-history replay.

### P3 — operator UX/reporting/observability

9. **Title:** Add canonical cycle schema versioning and changelog
- **Problem:** report structures may evolve without explicit compatibility contract.
- **Why it matters:** downstream tooling stability.
- **Files likely involved:** `scripts/trading-agency-phase1.py`, `docs/RUNTIME_OBSERVABILITY.md`, tests.
- **Risk:** Low.
- **Difficulty:** Low-Medium.
- **Expected impact:** Medium.
- **Proof of completion:** cycle summary contains `schema_version`; tests assert version and required keys.

10. **Title:** Add compact operator “health + evidence” CLI
- **Problem:** evidence reading is spread across multiple files.
- **Why it matters:** faster truthful operator checks.
- **Files likely involved:** new `scripts/operator-evidence-summary.py`, docs quickstart, tests.
- **Risk:** Low.
- **Difficulty:** Medium.
- **Expected impact:** Medium.
- **Proof of completion:** one command prints mode, latest cycle verdict, proof scope disclaimers, and artifact locations.

### P4 — monetization-enabling productization

11. **Title:** Package paper signal intelligence export API (offline/nearline)
- **Problem:** outputs are file-based and not product-ready.
- **Why it matters:** simplest monetizable layer without false execution claims.
- **Files likely involved:** new `api/` or `scripts/export-signals.py`, schemas, docs.
- **Risk:** Medium.
- **Difficulty:** Medium.
- **Expected impact:** High monetization leverage.
- **Proof of completion:** stable JSON export endpoint/file contract with versioned schema and sample client.

12. **Title:** Build benchmarked signal-quality reports by mode/exchange
- **Problem:** difficult to package measurable value to customers.
- **Why it matters:** enables paid research narrative with evidence.
- **Files likely involved:** performance/report scripts, docs, tests, sample notebooks.
- **Risk:** Low-Medium.
- **Difficulty:** Medium.
- **Expected impact:** High for sales enablement.
- **Proof of completion:** reproducible report generation with baseline comparisons and date-bounded methodology.

## J) Top 10 Highest-Value Fixes (Impact per effort)

1. Single truth manifest + CI guard generation
2. Standard offline-proof banner in all reports
3. Nonblocking live-shape contract check command
4. Persistence failure-path tests (disk/permission)
5. Stronger signal dedupe key than timestamp-only
6. Canonical cycle schema versioning
7. Consolidated operator evidence CLI summary
8. Rename/relocate future-scope scripts under support namespace
9. Large-history replay performance test for state recovery
10. Product-grade signal export schema + sample consumer

## K) Truth-First Rewrite Recommendations (Exact files)

1. `README.md`
- Add explicit pointer to one machine-checkable truth manifest once introduced.

2. `TRUTH_INDEX.md`
- Keep as top entrypoint, but reduce duplicated prose and link to manifest-driven claims table.

3. `SYSTEM_STATUS.md`
- Replace manually duplicated status bullets with generated status block.

4. `PROOF_MATRIX.md`
- Add explicit column for proof type: `offline deterministic` vs `live runtime`.

5. `docs/OPERATOR_EVIDENCE_GUIDE.md`
- Add explicit “Do not interpret as live validation” banner at top.

6. `docs/SYSTEM_ARCHITECTURE.md`
- Add compact section: “Failure modes not yet proven.”

7. `scripts/trading-agency-phase1.py`
- Include scope banner in generated summary markdown/json fields.

8. `tests/repo-truth-guard-test.py`
- Expand checks to include all active truth surfaces, not just selected files.

9. `scripts/live-readiness-validator.py`
- Move/rename to support namespace to reduce execution ambiguity.

10. `REMEDIATION_PLAN.md`
- Convert to current + next milestones only; archive prior completed detail to reduce reviewer confusion.

## L) Single Best Next Implementation Task

**Task:** Implement a **single machine-checkable truth manifest** (e.g., `truth/claims.yaml`) and wire it into CI + doc generation checks.

**Why this should come first:**
It directly reduces the highest systemic risk in this repository right now: **truth drift across many duplicated status surfaces**. It is low-to-medium effort, immediately improves trust/safety, and creates a stable foundation for every other reliability, testing, and monetization step without overstating capability.
