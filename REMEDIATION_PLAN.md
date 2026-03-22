# Remediation Plan

Date: 2026-03-22
Goal: make the repo’s claims, architecture, metadata, and tests line up cleanly with what the code actually does.

---

## Phase 0: truth cleanup

### Task 0.1 — remove stale active contradictions
- **Files to edit:** `docs/SYSTEM_ARCHITECTURE.md`, `SYSTEM_STATUS.md`, `PROOF_MATRIX.md`, `docs/REPO_TRUTHFULNESS_AUDIT.md`
- **Why:** active docs should agree on what CI now proves and on the exact paper-only scope.
- **Dependency/order:** first.
- **Risk:** low.
- **Done criteria:** no active doc says the agency orchestrator is untested end-to-end in CI if offline agency tests remain in CI.

### Task 0.2 — standardize the Polymarket truth label
- **Files to edit:** `README.md`, `SYSTEM_STATUS.md`, `docs/OPERATOR_QUICKSTART.md`, `docs/OPERATOR_EVIDENCE_GUIDE.md`, `docs/POLYMARKET_TESTNET_RESEARCH.md`
- **Why:** repo messaging should consistently say “canonical paper path, experimental overall, not live-ready.”
- **Dependency/order:** after 0.1.
- **Risk:** low.
- **Done criteria:** active docs use one consistent phrase set for Polymarket and mixed mode.

### Task 0.3 — quarantine future-scope/support scripts in docs
- **Files to edit:** `README.md`, `SYSTEM_STATUS.md`, `docs/SYSTEM_ARCHITECTURE.md`
- **Why:** support scripts are easy to mistake for runtime proof surfaces.
- **Dependency/order:** after 0.1.
- **Risk:** low.
- **Done criteria:** every support-only script is clearly labeled non-canonical where it is mentioned.

---

## Phase 1: fix canonical architecture truth and metadata

### Task 1.1 — unify experimental/canonical metadata semantics
- **Files to edit:** `models/exchange_metadata.py`, `scripts/phase1-signal-scanner.py`, `utils/paper_exchange_adapters.py`, `utils/runtime_logging.py`, `models/trade_schema.py`
- **Why:** current code disagrees on whether Polymarket is experimental.
- **Dependency/order:** after Phase 0 doc cleanup.
- **Risk:** medium.
- **Done criteria:** Polymarket experimental status is represented consistently in signals, trades, runtime events, and exchange metadata.

### Task 1.2 — make mixed-mode limitation explicit in code metadata
- **Files to edit:** `scripts/phase1-paper-trader.py`, `scripts/trading-agency-phase1.py`, `models/exchange_metadata.py`
- **Why:** mixed mode currently behaves as deterministic one-entry evaluation, but the metadata surface is sparse.
- **Dependency/order:** after 1.1.
- **Risk:** low.
- **Done criteria:** runtime artifacts clearly indicate why one signal won and that mixed mode is not a dual-entry runtime.

### Task 1.3 — separate authoritative state from advisory state more clearly
- **Files to edit:** `scripts/trading-agency-phase1.py`, `docs/RUNTIME_OBSERVABILITY.md`, `docs/SYSTEM_ARCHITECTURE.md`
- **Why:** reports and safety artifacts are helpful but should not be mistaken for canonical execution truth.
- **Dependency/order:** after 1.2.
- **Risk:** low.
- **Done criteria:** docs and report fields clearly distinguish authoritative state from derived summaries.

---

## Phase 2: repair/add tests

### Task 2.1 — add regression tests for metadata consistency
- **Files to edit:** add `tests/polymarket-metadata-truth-test.py` (new), update `scripts/ci-safe-verification.sh`
- **Why:** current docs/code disagreement about Polymarket experimental status can regress silently.
- **Dependency/order:** after Phase 1 metadata fix.
- **Risk:** low.
- **Done criteria:** CI fails if runtime events, signals, and trades disagree on Polymarket experimental labeling.

### Task 2.2 — add explicit canonical-file contract test for agency outputs
- **Files to edit:** add `tests/agency-canonical-output-contract-test.py` (new), update `scripts/ci-safe-verification.sh`
- **Why:** canonical vs non-authoritative output classification should be enforced by test.
- **Dependency/order:** after 1.3.
- **Risk:** low.
- **Done criteria:** CI verifies that canonical trade/state outputs are the ones claimed in docs.

### Task 2.3 — add doc-truth guard for active docs
- **Files to edit:** `tests/repo-truth-guard-test.py`
- **Why:** active docs currently drift more easily than code.
- **Dependency/order:** after Phase 0 cleanup.
- **Risk:** low.
- **Done criteria:** CI fails on stale phrases like “orchestrator path not tested end-to-end” if no longer true.

### Task 2.4 — add live-connectivity test policy guard, not live-connectivity test itself
- **Files to edit:** add `tests/connectivity-scope-guard-test.py` (new), maybe `README.md`
- **Why:** ensure CI remains honest about what is offline proof versus live proof.
- **Dependency/order:** after 2.3.
- **Risk:** low.
- **Done criteria:** CI/documentation surface explicitly preserves “offline proof only” truth where applicable.

---

## Phase 3: Polymarket integration completion

### Task 3.1 — decide whether Polymarket is staying paper-only or moving toward real execution
- **Files to edit:** `README.md`, `SYSTEM_STATUS.md`, `docs/POLYMARKET_TESTNET_RESEARCH.md`, possibly new design doc under `docs/`
- **Why:** the repo currently mixes “canonical paper path” and “not fully integrated” language. Completion requires a declared target.
- **Dependency/order:** before any real execution work.
- **Risk:** medium.
- **Done criteria:** repo has one explicit Polymarket scope decision.

### Task 3.2 — if moving beyond paper, add authenticated execution module and state contracts
- **Files to edit:** likely new files under `utils/` and `scripts/`, plus `models/trade_schema.py`, `models/position_state.py`
- **Why:** real end-to-end integration requires authenticated order placement and execution-state persistence.
- **Dependency/order:** after 3.1.
- **Risk:** high.
- **Done criteria:** system can represent order intent, exchange order ID, fill status, partial fills, cancellation, and final settlement.

### Task 3.3 — add exchange-specific Polymarket lifecycle support
- **Files to edit:** new execution module(s), `scripts/phase1-paper-trader.py` or successor runtime, `scripts/timeout-monitor.py`, `models/trade_schema.py`
- **Why:** Polymarket requires market resolution/settlement semantics that paper marks do not cover.
- **Dependency/order:** after 3.2.
- **Risk:** high.
- **Done criteria:** code can track open order, fill, open position, resolution, settlement, and final realized outcome distinctly.

### Task 3.4 — add real integration tests outside default CI
- **Files to edit:** add a non-default suite under `tests/integration_live/` or similar, plus docs describing operator-run prerequisites
- **Why:** completion cannot be claimed from fixture-based tests.
- **Dependency/order:** after 3.2 and 3.3.
- **Risk:** high.
- **Done criteria:** authenticated sandbox/testnet or controlled live-read test proves request/response/order lifecycle for Polymarket.

---

## Phase 4: observability and docs cleanup

### Task 4.1 — align observability outputs with canonical truth map
- **Files to edit:** `docs/RUNTIME_OBSERVABILITY.md`, `scripts/trading-agency-phase1.py`, `scripts/timeout-monitor.py`
- **Why:** operator-facing artifacts should make canonical versus advisory outputs obvious.
- **Dependency/order:** after Phase 1 and Phase 2.
- **Risk:** low.
- **Done criteria:** every generated report says whether it is authoritative, advisory, or proof-only.

### Task 4.2 — add a single maintained current-state document
- **Files to edit:** `SYSTEM_STATUS.md`, `README.md`, possibly replace overlapping audit docs with links
- **Why:** too many overlapping truth surfaces cause drift.
- **Dependency/order:** after Phase 0.
- **Risk:** medium.
- **Done criteria:** one current-state doc becomes the source of truth; other docs point to it instead of rephrasing status.

### Task 4.3 — de-duplicate active root audit artifacts
- **Files to edit:** active root audit/plan markdown files
- **Why:** multiple audit files at repo root previously drifted and referenced removed artifacts.
- **Dependency/order:** after all earlier phases.
- **Risk:** low.
- **Done criteria:** root-level audit docs agree with each other and with active code/docs.

---

## Priority order summary

1. Fix active truth/doc contradictions.
2. Fix metadata inconsistency around Polymarket experimental status.
3. Add tests that lock those truths in place.
4. Decide whether Polymarket remains paper-only or gets real execution work.
5. Only then pursue production-grade exchange integration claims.

---

## What completion looks like

You can truthfully say **both exchanges are fully integrated** only if all of the following become true:
- authenticated execution exists
- order IDs/fills are persisted and reconciled
- settlement lifecycle exists where required
- non-fixture integration tests exist
- mixed-mode semantics are explicitly implemented and proven if you want to claim combined runtime support
- docs, runtime metadata, and reports all agree

Until then, the truthful posture remains:
- Hyperliquid integrated for the canonical paper path
- Polymarket integrated for the canonical paper path but still experimental/partial overall
- paper trading only
