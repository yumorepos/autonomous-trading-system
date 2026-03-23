# Remediation Plan

Audit date: 2026-03-23 UTC
Goal: repair the repository to match a strict, evidence-based description of what is actually implemented.

## Phase 0 — truth cleanup — completed

### Task 0.1 — archive or relabel stale generated docs — completed
- **Files to edit:**
  - `docs/TIMEOUT_MONITOR_REPORT.md`
  - `docs/POSITION_TRACKING_REPORT.md`
  - `docs/EXIT_TRACKER_REPORT.md`
- **Why:** active docs root contains stale/generated report content that looks current and can contradict code.
- **Dependency/order:** first.
- **Risk:** low.
- **Done criteria:** met — each file now starts with a clear non-canonical historical/example banner.

### Task 0.2 — standardize repo truth wording — completed
- **Files to edit:**
  - `README.md`
  - `SYSTEM_STATUS.md`
  - `TRUTH_INDEX.md`
  - `docs/SYSTEM_ARCHITECTURE.md`
  - `docs/OPERATOR_EVIDENCE_GUIDE.md`
  - `docs/POLYMARKET_EXECUTION_SCOPE.md`
- **Why:** these are the main review surfaces and should use identical language.
- **Dependency/order:** after Task 0.1.
- **Risk:** low.
- **Done criteria:** met — one consistent vocabulary is used across the active truth surfaces: `canonical paper path`, `experimental overall`, `mixed limited`, `support-only`, `historical`, `offline proof only`.

### Task 0.3 — sharpen support/future-scope labeling — completed
- **Files to edit:**
  - `scripts/live-readiness-validator.py`
  - `scripts/supervisor-governance.py`
  - docs that mention them
- **Why:** names and descriptions still suggest broader operational scope than exists.
- **Dependency/order:** parallel.
- **Risk:** low-medium.
- **Done criteria:** met — their top-level descriptions now mark them as support-only and outside the canonical runtime.

## Phase 1 — fix canonical architecture

### Task 1.1 — enforce exchange-specific signal validation before persistence — completed
- **Files to edit:**
  - `scripts/data-integrity-layer.py`
  - `utils/paper_exchange_adapters.py`
  - `scripts/phase1-signal-scanner.py`
- **Why:** scanner acceptance now matches trader executability by applying exchange-specific canonical contract checks before append-only persistence.
- **Dependency/order:** completed foundational fix; retain regression coverage and build follow-on cleanup/tests on top of it.
- **Risk:** medium.
- **Done criteria:** met — exchange-invalid Hyperliquid and Polymarket signals are rejected before writing to `phase1-signals.jsonl`.

### Task 1.2 — centralize canonical trade/state contract — completed
- **Files to edit:**
  - `models/paper_contracts.py`
  - `models/trade_schema.py`
  - `models/position_state.py`
  - `scripts/phase1-paper-trader.py`
  - `scripts/performance-dashboard.py`
  - `scripts/timeout-monitor.py`
  - `scripts/execution-safety-layer.py`
  - `scripts/data-integrity-layer.py`
  - `utils/paper_exchange_adapters.py`
- **Why:** remove distributed paper-contract assumptions across validation, persistence, and readers.
- **Dependency/order:** completed after Task 1.1.
- **Risk:** medium.
- **Done criteria:** met — canonical signal requirements plus open/closed paper-trade requirements now come from shared helpers in `models/paper_contracts.py`.

### Task 1.3 — make mixed-mode semantics explicit in code and docs
- **Files to edit:**
  - `models/exchange_metadata.py`
  - `scripts/phase1-paper-trader.py`
  - `scripts/trading-agency-phase1.py`
  - `README.md`
  - `docs/SYSTEM_ARCHITECTURE.md`
- **Why:** mixed mode is limited by design; that should stay explicit and testable.
- **Dependency/order:** after Task 1.2.
- **Risk:** low-medium.
- **Done criteria:** code and docs agree on exactly one of these futures: keep mixed asymmetric, or upgrade to peer-symmetric behavior.

## Phase 2 — repair/add tests

### Task 2.1 — add Polymarket negative-path tests — completed
- **Files to edit/add:**
  - `tests/destructive/trading-agency-polymarket-negative-path-test.py`
  - `scripts/ci-safe-verification.sh`
- **Why:** Hyperliquid had stronger negative-path proof coverage than Polymarket.
- **Dependency/order:** completed after Task 1.1.
- **Risk:** low-medium.
- **Done criteria:** met — tests now cover stale Polymarket signals, duplicate entries, missing token metadata, and invalid market payloads.

### Task 2.2 — add optional live-shape contract checks
- **Files to edit/add:**
  - add nonblocking tests/scripts for current API payload shape
  - update docs with manual command path
- **Why:** offline fixtures prove repo logic only.
- **Dependency/order:** after Task 1.1.
- **Risk:** medium due network variability.
- **Done criteria:** maintainers can run a documented nonblocking command that validates current Hyperliquid and Polymarket public payload shape.

### Task 2.3 — add multi-cycle mixed-mode orchestrator proof
- **Files to edit/add:**
  - add destructive mixed multi-cycle test
- **Why:** current mixed proofs show constraint semantics, but not restart/recovery across several cycles with both exchanges represented in shared state over time.
- **Dependency/order:** after Task 1.3.
- **Risk:** medium.
- **Done criteria:** test proves deterministic mixed behavior across repeated isolated cycles without state drift.

## Phase 3 — Polymarket integration completion

### Task 3.1 — make an explicit product decision on Polymarket scope
- **Files to edit:**
  - `README.md`
  - `SYSTEM_STATUS.md`
  - `docs/POLYMARKET_EXECUTION_SCOPE.md`
  - roadmap/truth docs
- **Why:** current repo is in a paper-only middle state.
- **Dependency/order:** before any live execution work.
- **Risk:** organizational.
- **Done criteria:** the repo unambiguously states either “paper-only research integration” or “live execution roadmap”.

### Task 3.2 — if live execution is desired, add authenticated Polymarket order path
- **Files to edit/add:**
  - new canonical execution modules
  - canonical config/secrets surface
  - canonical persistence path for real orders/fills
- **Why:** current Polymarket path is public-data paper simulation only.
- **Dependency/order:** after Task 3.1.
- **Risk:** high.
- **Done criteria:** canonical runtime can place, track, and reconcile Polymarket orders without synthetic paper fills.

### Task 3.3 — add fill and settlement reconciliation
- **Files to edit/add:**
  - canonical execution and persistence modules
  - state model updates
  - integration tests
- **Why:** “fully integrated” is not truthful without exchange-confirmed state transitions.
- **Dependency/order:** after Task 3.2.
- **Risk:** high.
- **Done criteria:** canonical open/close state reflects actual exchange fills and settlement events.

### Task 3.4 — only then revisit mixed-mode parity
- **Files to edit:**
  - `models/exchange_metadata.py`
  - `scripts/phase1-paper-trader.py`
  - orchestrator/tests/docs
- **Why:** peer-symmetric mixed mode should not be attempted before single-exchange semantics are real and stable.
- **Dependency/order:** last in this phase.
- **Risk:** high.
- **Done criteria:** mixed mode semantics are explicit, implemented, and proven for whichever design is chosen.

## Phase 4 — observability and docs cleanup

### Task 4.1 — separate canonical truth docs from generated/report docs
- **Files to edit:** docs structure and indexes.
- **Why:** today they are mixed together.
- **Dependency/order:** after Phase 0 or in parallel.
- **Risk:** low.
- **Done criteria:** generated/runtime reports are clearly segregated from normative documentation.

### Task 4.2 — add one canonical “current proof surface” index
- **Files to edit:**
  - `TRUTH_INDEX.md`
  - `PROOF_MATRIX.md`
  - `README.md`
- **Why:** there are multiple summaries and audit files; drift risk is high.
- **Dependency/order:** after truth wording is standardized.
- **Risk:** low.
- **Done criteria:** one short index points to the only active truth surfaces and marks everything else as support/history.

### Task 4.3 — document the meaning of connectivity checks vs offline proofs
- **Files to edit:**
  - `README.md`
  - `docs/OPERATOR_QUICKSTART.md`
  - `docs/OPERATOR_EVIDENCE_GUIDE.md`
  - `scripts/runtime-connectivity-check.py` header/comments if needed
- **Why:** users need a clean distinction between repo correctness and current network reachability.
- **Dependency/order:** low.
- **Risk:** low.
- **Done criteria:** docs explicitly separate “offline proof”, “current read-only connectivity”, and “live execution proof”.
