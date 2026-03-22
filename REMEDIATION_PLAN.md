# Remediation Plan

Date: 2026-03-22 UTC

Goal:
- clean up stale truth surfaces
- remove ambiguity around Polymarket status
- finish canonicalization of multi-exchange paper state
- keep claims aligned with what code and tests actually prove

## Phase 0: truth cleanup

### Task 0.1 — fix stale architecture proof statements
- **Files to edit:** `docs/SYSTEM_ARCHITECTURE.md`, `docs/OPERATOR_QUICKSTART.md`, `docs/REPO_TRUTHFULNESS_AUDIT.md`
- **Why:** these files still understate or mismatch the current agency test coverage and Polymarket paper-path proof level.
- **Dependency/order:** first.
- **Risk:** low.
- **Done criteria:** docs state that CI proves the offline agency entrypoint for Hyperliquid, Polymarket, mixed-mode limitation, and negative-path behavior.

### Task 0.2 — fix stale data-integrity narrative
- **Files to edit:** `docs/DATA_INTEGRITY_LAYER.md`
- **Why:** the doc still describes Hyperliquid as a universal primary source that halts all signal generation; `polymarket_only` no longer behaves that way.
- **Dependency/order:** after 0.1.
- **Risk:** low.
- **Done criteria:** docs describe mode-aware gating exactly as implemented.

### Task 0.3 — quarantine live-readiness framing
- **Files to edit:** `scripts/live-readiness-validator.py`, `scripts/supervisor-governance.py`, `SYSTEM_STATUS.md`, `README.md`
- **Why:** even with caveats, active-tree live-readiness framing creates avoidable ambiguity in a paper-only repo.
- **Dependency/order:** parallel with 0.1/0.2.
- **Risk:** low.
- **Done criteria:** no active top-level text can be read as present-day live readiness.

## Phase 1: fix canonical architecture

### Task 1.1 — eliminate the second Polymarket state model
- **Files to edit:** `scripts/polymarket-executor.py`, `scripts/stability-monitor.py`, `scripts/live-readiness-validator.py`, any docs that mention `polymarket-state.json` or `polymarket-trades.jsonl`
- **Why:** the repo currently has both a canonical Polymarket paper path and a helper-specific Polymarket state model.
- **Dependency/order:** after Phase 0.
- **Risk:** medium.
- **Done criteria:** either archive the helper or make every active reader use canonical `phase1-paper-trades.jsonl` and `position-state.json` only.

### Task 1.2 — formalize one documented cross-exchange state contract
- **Files to edit:** `models/trade_schema.py`, `models/position_state.py`, `scripts/phase1-paper-trader.py`, `scripts/performance-dashboard.py`, `scripts/timeout-monitor.py`
- **Why:** the current contract works, but the authoritative schema should be explicitly documented as the only supported multi-exchange state model.
- **Dependency/order:** after 1.1.
- **Risk:** medium.
- **Done criteria:** one documented schema definition covers both trade history and open-position persistence, including Polymarket-specific identity fields.

### Task 1.3 — make mixed-mode semantics explicit in code and docs
- **Files to edit:** `scripts/phase1-paper-trader.py`, `scripts/trading-agency-phase1.py`, `README.md`, `docs/SYSTEM_ARCHITECTURE.md`
- **Why:** current behavior is single-entry-per-cycle; docs should either keep that limitation or architecture should be changed intentionally.
- **Dependency/order:** after 1.2.
- **Risk:** medium.
- **Done criteria:** mixed mode is either explicitly single-entry-per-cycle everywhere, or upgraded with matching tests.

## Phase 2: repair/add tests

### Task 2.1 — add a dedicated doc-truth regression check
- **Files to edit:** add a test or lint script under `tests/` or `scripts/`; wire it into `scripts/ci-safe-verification.sh`
- **Why:** stale docs are now one of the main truth risks.
- **Dependency/order:** after Phase 0.
- **Risk:** low.
- **Done criteria:** CI fails when known truth anchors drift from current claims.

### Task 2.2 — add direct tests for non-canonical file quarantine
- **Files to edit:** add tests covering `scripts/polymarket-executor.py`, `scripts/stability-monitor.py`, and any remaining helper readers
- **Why:** prevent reintroduction of alternate Polymarket state paths.
- **Dependency/order:** after 1.1.
- **Risk:** low.
- **Done criteria:** CI proves that active support scripts do not read/write deprecated Polymarket helper state.

### Task 2.3 — add live-connectivity checks only as non-blocking evidence jobs
- **Files to edit:** `.github/workflows/basic.yml` or a separate non-required workflow; `scripts/runtime-connectivity-check.py`
- **Why:** keep merge-blocking CI stable while preserving optional fresh evidence.
- **Dependency/order:** after canonical cleanup.
- **Risk:** medium.
- **Done criteria:** optional scheduled/manual job records read-only API reachability without affecting required CI.

## Phase 3: Polymarket integration completion

### Task 3.1 — choose one Polymarket runtime story
- **Files to edit:** `README.md`, `SYSTEM_STATUS.md`, `docs/POLYMARKET_TESTNET_RESEARCH.md`, `scripts/polymarket-executor.py`
- **Why:** the repo currently says Polymarket is experimental but keeps both canonical and helper-style paths.
- **Dependency/order:** after Phase 1.
- **Risk:** medium.
- **Done criteria:** repo clearly presents either (a) one canonical experimental paper path only, or (b) an archived helper outside the active runtime surface.

### Task 3.2 — harden Polymarket price identity and exit assumptions
- **Files to edit:** `scripts/phase1-signal-scanner.py`, `scripts/phase1-paper-trader.py`, `scripts/execution-safety-layer.py`, `scripts/timeout-monitor.py`, `models/trade_schema.py`
- **Why:** Polymarket entry/exit logic currently relies on read-only market snapshots and token/outcome matching heuristics.
- **Dependency/order:** after 3.1.
- **Risk:** medium.
- **Done criteria:** token identity, side, and market identity are explicit and consistently used across scan, safety, entry, exit, and monitoring.

### Task 3.3 — keep Polymarket scoped correctly unless live execution is actually built
- **Files to edit:** `README.md`, `SYSTEM_STATUS.md`, docs under `docs/`
- **Why:** offline paper-runtime proof is real, but it is not the same thing as execution-grade integration.
- **Dependency/order:** after 3.2.
- **Risk:** low.
- **Done criteria:** Polymarket remains labeled experimental until real authenticated execution, fills, and settlement handling exist and are tested.

## Phase 4: observability and docs cleanup

### Task 4.1 — label every script as canonical or non-canonical at the top of the file
- **Files to edit:** active scripts under `scripts/`
- **Why:** current repo still requires a reviewer to infer what is runtime-critical versus support-only.
- **Dependency/order:** after architecture cleanup.
- **Risk:** low.
- **Done criteria:** every active script self-identifies its status in the opening docstring.

### Task 4.2 — publish one machine-readable truth manifest
- **Files to edit:** add `TRUTH_MANIFEST.json` or `TRUTH_MANIFEST.md`; reference it from `README.md` and `SYSTEM_STATUS.md`
- **Why:** canonical vs support-only status is currently repeated across prose docs.
- **Dependency/order:** after 4.1.
- **Risk:** low.
- **Done criteria:** one file lists each script, whether it is canonical, what it reads/writes, and whether CI proves it.

### Task 4.3 — reduce report sprawl in operator docs
- **Files to edit:** `README.md`, `docs/OPERATOR_QUICKSTART.md`, `docs/RUNTIME_OBSERVABILITY.md`
- **Why:** there are many generated artifacts, but only a few are authoritative.
- **Dependency/order:** after 4.2.
- **Risk:** low.
- **Done criteria:** operator docs always list authoritative files first and monitoring/report files second.

## Priority order summary

1. Correct stale docs and remove ambiguity.
2. Eliminate the alternate Polymarket state model.
3. Formalize the single canonical cross-exchange state contract.
4. Lock mixed-mode semantics down explicitly.
5. Add CI checks that keep docs/support surfaces truthful.
6. Keep Polymarket experimental until execution-grade functionality actually exists.
