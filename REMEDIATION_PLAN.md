# Remediation Plan

Date: 2026-03-21 UTC
Goal: make the repo’s claims match what is actually implemented and proven, then close the highest-value integration gaps in priority order.

## Phase 0: truth cleanup

### Task 0.1 — tighten the top-line claim language
- **Files to edit:** `README.md`, `SYSTEM_STATUS.md`, `docs/SYSTEM_ARCHITECTURE.md`, `docs/REPO_TRUTHFULNESS_AUDIT.md`, `docs/OPERATOR_QUICKSTART.md`
- **Why:** current wording still overstates CI-backed proof and mixed-mode strength.
- **Dependency/order:** first.
- **Risk:** low.
- **Done criteria:** docs say “paper-trading path,” not “integrated” or “orchestrated” without clarifying proof limits; mixed mode is described as experimental and single-entry-per-cycle unless architecture changes.

### Task 0.2 — quarantine active-tree live/future readiness language
- **Files to edit:** `scripts/live-readiness-validator.py`, `scripts/supervisor-governance.py`, `SYSTEM_STATUS.md`
- **Why:** future/live concepts in active files weaken truthfulness.
- **Dependency/order:** after 0.1.
- **Risk:** low.
- **Done criteria:** active-tree wording cannot be read as present-day live readiness; future-scope files are clearly marked non-canonical research.

### Task 0.3 — fix misleading optional-component reporting
- **Files to edit:** `scripts/trading-agency-phase1.py`
- **Why:** `polymarket_execution` is reported as enabled based on helper file presence even though it is not in the canonical flow.
- **Dependency/order:** parallel with 0.1/0.2.
- **Risk:** low.
- **Done criteria:** orchestrator reports canonical Polymarket paper path status separately from non-canonical helper presence.

## Phase 1: fix canonical architecture

### Task 1.1 — formalize the multi-exchange canonical trade schema
- **Files to edit:** `models/trade_schema.py`, `models/position_state.py`, `scripts/performance-dashboard.py`, `scripts/phase1-paper-trader.py`, `scripts/timeout-monitor.py`, `scripts/supervisor-governance.py`, `scripts/portfolio-allocator.py`, `scripts/alpha-intelligence-layer.py`
- **Why:** exchange identity and Polymarket-specific fields are not first-class canonical fields today.
- **Dependency/order:** after Phase 0.
- **Risk:** medium.
- **Done criteria:** normalized trades include at minimum `exchange`, `strategy`, and exchange-specific identity fields in a documented canonical schema; downstream readers stop depending on `raw` for exchange routing.

### Task 1.2 — remove alternate Polymarket persistence from active support paths
- **Files to edit:** `scripts/polymarket-executor.py`, `scripts/live-readiness-validator.py`, `scripts/stability-monitor.py`, any docs referencing `polymarket-state.json` or `polymarket-trades.jsonl`
- **Why:** one repo cannot honestly claim one canonical state model while active files still read/write separate Polymarket state.
- **Dependency/order:** after 1.1.
- **Risk:** medium.
- **Done criteria:** active-tree support scripts either use canonical `phase1-paper-trades.jsonl` / `position-state.json` or are explicitly archived/non-executable.

### Task 1.3 — decide what mixed mode is supposed to mean
- **Files to edit:** `scripts/phase1-paper-trader.py`, `scripts/trading-agency-phase1.py`, `README.md`, `docs/SYSTEM_ARCHITECTURE.md`
- **Why:** current docs imply side-by-side evaluation, but implementation admits only one new entry per cycle.
- **Dependency/order:** after 1.1.
- **Risk:** medium.
- **Done criteria:** either (a) mixed mode docs are reduced to “shared-mode accumulation over multiple cycles,” or (b) the planner is updated to support explicit multi-entry mixed-mode behavior with tests.

## Phase 2: repair/add tests

### Task 2.1 — add orchestrator integration tests for all three modes
- **Files to edit:** add `tests/destructive/trading-agency-hyperliquid-test.py`, `tests/destructive/trading-agency-polymarket-test.py`, `tests/destructive/trading-agency-mixed-test.py`; update `scripts/ci-safe-verification.sh`
- **Why:** the canonical entrypoint is currently untested.
- **Dependency/order:** after Phase 1 decisions.
- **Risk:** medium.
- **Done criteria:** CI exercises `scripts/trading-agency-phase1.py` in isolated temp workspaces with mocked API responses and validates final agency/state artifacts.

### Task 2.2 — add schema contract tests
- **Files to edit:** add `tests/trade-schema-contract-test.py`, `tests/position-state-contract-test.py`
- **Why:** schema drift is the highest structural risk in the repo.
- **Dependency/order:** after 1.1.
- **Risk:** low.
- **Done criteria:** any new consumer or producer that drops required canonical exchange fields fails CI.

### Task 2.3 — add negative-path tests for safety and mixed mode
- **Files to edit:** add targeted tests under `tests/`
- **Why:** current suite proves happy-path persistence better than it proves halts/blocks/skips.
- **Dependency/order:** after 2.1.
- **Risk:** low.
- **Done criteria:** CI proves duplicate-order rejection, breaker halts, stale signal rejection, and mixed-mode semantics.

## Phase 3: Polymarket integration completion

### Task 3.1 — make canonical Polymarket support the only active Polymarket path
- **Files to edit:** `scripts/phase1-signal-scanner.py`, `scripts/execution-safety-layer.py`, `scripts/phase1-paper-trader.py`, `scripts/polymarket-executor.py`, `README.md`
- **Why:** Polymarket currently exists as both canonical paper support and separate helper/scaffold logic.
- **Dependency/order:** after Phase 1 schema cleanup.
- **Risk:** medium.
- **Done criteria:** there is one Polymarket paper path, one state model, one source of truth, and one documented runtime story.

### Task 3.2 — harden Polymarket price/market identity handling
- **Files to edit:** `scripts/phase1-signal-scanner.py`, `scripts/phase1-paper-trader.py`, `scripts/timeout-monitor.py`, `models/trade_schema.py`
- **Why:** Polymarket entry/exit logic currently depends on heuristic token/market lookups over Gamma responses.
- **Dependency/order:** after 3.1.
- **Risk:** medium.
- **Done criteria:** token identity, market identity, and exit pricing are explicit in the canonical schema and tested with realistic fixtures.

### Task 3.3 — add real canonical Polymarket orchestrator test coverage
- **Files to edit:** new tests plus `scripts/ci-safe-verification.sh`
- **Why:** current proof is isolated to the trader.
- **Dependency/order:** after 3.1 and 3.2.
- **Risk:** low.
- **Done criteria:** CI proves full Polymarket paper path through the agency entrypoint in `polymarket_only` and `mixed` modes.

## Phase 4: observability and docs cleanup

### Task 4.1 — label every support script as canonical or non-canonical in-code and in docs
- **Files to edit:** headers in `scripts/*.py`, `README.md`, `docs/SYSTEM_ARCHITECTURE.md`
- **Why:** the repo still makes reviewers work too hard to separate runtime truth from support tooling.
- **Dependency/order:** after architecture cleanup.
- **Risk:** low.
- **Done criteria:** every active-tree script advertises its status in the first docstring block and docs match it.

### Task 4.2 — reduce runtime report sprawl
- **Files to edit:** `scripts/trading-agency-phase1.py`, `scripts/timeout-monitor.py`, docs covering outputs
- **Why:** many support artifacts are written, but only a few are authoritative.
- **Dependency/order:** after 4.1.
- **Risk:** low.
- **Done criteria:** docs clearly separate authoritative state from support reports, and operator quickstart highlights only the authoritative files first.

### Task 4.3 — add a machine-readable truth manifest
- **Files to edit:** add `TRUTH_MANIFEST.json` or `TRUTH_MANIFEST.md`; update docs to reference it
- **Why:** the repo repeatedly re-documents canonical vs non-canonical status in prose.
- **Dependency/order:** last.
- **Risk:** low.
- **Done criteria:** one manifest lists each script’s status, state files used, and whether CI proves it.

## Priority order summary

1. Tighten claims.
2. Remove alternate Polymarket state from active code.
3. Formalize one multi-exchange canonical schema.
4. Add orchestrator integration tests.
5. Decide and enforce real mixed-mode semantics.
6. Finish Polymarket canonicalization.
7. Clean up observability/docs labeling.
