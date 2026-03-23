# Remediation Plan

Date: 2026-03-23 UTC

## Phase 0 — truth cleanup

### Task 0.1
- **Task:** Tighten active support docs to match actual canonical execution.
- **Files to edit:** `docs/DATA_INTEGRITY_LAYER.md`, `docs/EXECUTION_SAFETY_LAYER.md`, `docs/SYSTEM_ARCHITECTURE.md`, `docs/OPERATOR_QUICKSTART.md`
- **Why:** active docs still describe stronger behavior than the canonical flow executes.
- **Dependency/order:** first.
- **Risk:** low.
- **Done criteria:** active docs mention only runtime-enforced behavior or clearly label future/support-only concepts.

### Task 0.2
- **Task:** Consolidate canonical vs non-canonical labeling.
- **Files to edit:** `README.md`, `SYSTEM_STATUS.md`, `TRUTH_INDEX.md`
- **Why:** duplicated status language is manageable now but will drift.
- **Dependency/order:** after 0.1.
- **Risk:** low.
- **Done criteria:** one consistent vocabulary is used everywhere: `canonical paper path`, `experimental overall`, `mixed limited`, `support-only`, `historical`.

## Phase 1 — fix canonical architecture

### Task 1.1
- **Task:** Call `DataIntegrityLayer.validate_signal()` from the canonical scanner before persisting signals.
- **Files to edit:** `scripts/phase1-signal-scanner.py`, `scripts/data-integrity-layer.py`
- **Why:** duplicate detection, signal decay, and rejected-signal logging are currently dead from the canonical path.
- **Dependency/order:** after Phase 0.
- **Risk:** medium.
- **Done criteria:** scanner accepts/rejects signals through the integrity layer and writes accepted/rejected counts.

### Task 1.2
- **Task:** Either retire `scripts/exit-monitor.py` from the active tree or rewrite it as a pure canonical-state reader.
- **Files to edit:** `scripts/exit-monitor.py`, `docs/RUNTIME_OBSERVABILITY.md`, `docs/SYSTEM_ARCHITECTURE.md`
- **Why:** it is intentionally skipped today because it can confuse proof/reporting with authoritative persistence.
- **Dependency/order:** after 1.1.
- **Risk:** medium.
- **Done criteria:** no active monitor script looks authoritative while being non-authoritative.

### Task 1.3
- **Task:** Emit machine-readable mixed-mode policy in cycle/report artifacts.
- **Files to edit:** `scripts/trading-agency-phase1.py`, `scripts/phase1-paper-trader.py`, `models/exchange_metadata.py`
- **Why:** reviewers should not have to infer selection asymmetry from code.
- **Dependency/order:** after 1.1.
- **Risk:** low.
- **Done criteria:** agency report includes `primary_exchange`, `max_new_entries_per_cycle`, `secondary_health_is_advisory`, and rejected candidate metadata.

## Phase 2 — repair/add tests

### Task 2.1
- **Task:** Add a scanner-path regression test that fails if invalid/stale/duplicate signals are persisted.
- **Files to edit:** add new test under `tests/`; possibly update `scripts/ci-safe-verification.sh`
- **Why:** current tests do not prove that signal-level integrity logic runs in the canonical path.
- **Dependency/order:** after 1.1.
- **Risk:** low.
- **Done criteria:** CI fails if scanner bypasses integrity enforcement.

### Task 2.2
- **Task:** Add orchestrator-level multi-cycle mixed-mode proof that accumulates both exchanges over time without breaking the one-entry-per-cycle rule.
- **Files to edit:** add new destructive test under `tests/destructive/`; update `scripts/ci-safe-verification.sh`
- **Why:** current mixed-mode proof is correct but still narrow.
- **Dependency/order:** after 1.3.
- **Risk:** medium.
- **Done criteria:** one destructive test proves both shared-state accumulation and selection asymmetry at orchestrator level.

### Task 2.3
- **Task:** Add negative-path Polymarket tests for malformed market payloads.
- **Files to edit:** add new test files under `tests/`
- **Why:** current Polymarket proof is mostly happy-path.
- **Dependency/order:** parallel with 2.2.
- **Risk:** low.
- **Done criteria:** malformed prices/tokens/market IDs are rejected and covered.

## Phase 3 — Polymarket integration completion

### Task 3.1
- **Task:** Make a product decision: paper-only Polymarket forever, or real execution target.
- **Files to edit:** `README.md`, `docs/POLYMARKET_EXECUTION_SCOPE.md`, `SYSTEM_STATUS.md`
- **Why:** current wording is mostly honest but still leaves room for readers to project more than the code supports.
- **Dependency/order:** before any real execution work.
- **Risk:** medium.
- **Done criteria:** docs explicitly state whether live Polymarket execution is in or out of scope.

### Task 3.2
- **Task:** If live Polymarket execution is in scope, split paper adapters from live adapters and implement a real client.
- **Files to edit:** `utils/paper_exchange_adapters.py` (split), new live client modules, orchestrator wiring, tests, docs
- **Why:** paper adapter code is not a live execution implementation.
- **Dependency/order:** after 3.1.
- **Risk:** high.
- **Done criteria:** authenticated order placement, signing/wallet flow, fills, settlement, and live integration tests exist.

### Task 3.3
- **Task:** If live Polymarket execution is out of scope, rename surfaces to reduce ambiguity.
- **Files to edit:** docs, adapter names, maybe metadata naming
- **Why:** current `canonical` wording can be misread as broader than `canonical paper path`.
- **Dependency/order:** after 3.1 if live work is out of scope.
- **Risk:** low.
- **Done criteria:** every reference says `paper path` or `paper adapter` where appropriate.

## Phase 4 — observability and docs cleanup

### Task 4.1
- **Task:** Add a per-cycle runtime manifest.
- **Files to edit:** `scripts/trading-agency-phase1.py`
- **Why:** it should be trivial to see what ran, what was skipped, and which files were written.
- **Dependency/order:** after Phase 1.
- **Risk:** low.
- **Done criteria:** one JSON artifact lists executed stages, skipped scripts, touched files, and active policy flags.

### Task 4.2
- **Task:** Move broad support docs out of the active-doc set or relabel them.
- **Files to edit:** `docs/CAPITAL_ALLOCATION.md`, `docs/THREE_STAGE_GOVERNANCE.md`, `docs/EXIT_TRACKER_REPORT.md`, `docs/POSITION_TRACKING_REPORT.md`, `docs/STABILITY_REPORT.md`
- **Why:** these docs increase active truth surface without being part of the canonical loop.
- **Dependency/order:** after Phase 0.
- **Risk:** low.
- **Done criteria:** active docs directory is biased toward current runtime truth, not retained subsystem ambition.

### Task 4.3
- **Task:** Expand docs truth guards in CI.
- **Files to edit:** `tests/repo-truth-guard-test.py`, possibly add new guard test; update `scripts/ci-safe-verification.sh`
- **Why:** current truth guard does not cover all active docs.
- **Dependency/order:** after 4.2.
- **Risk:** low.
- **Done criteria:** CI fails on unsupported live-ready claims, unsupported mixed-mode claims, and unsupported data-integrity claims in active docs.
