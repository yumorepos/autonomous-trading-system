# REMEDIATION_PLAN

Date: 2026-03-23 UTC
Goal: remove truth ambiguity, tighten canonical architecture, and separate proven paper-trading capability from unsupported live-trading implications.

## Phase 0 - truth cleanup

### Task 0.1 - Quarantine or index historical contradiction surfaces
- **Files to edit:** `README.md`, `SYSTEM_STATUS.md`, `docs/REPO_TRUTHFULNESS_AUDIT.md`, add/update `docs/archive/README.md`
- **Why:** Active docs are mostly truthful, but repo-wide search still lands on historical contradictory material.
- **Dependency/order:** first
- **Risk:** low
- **Done criteria:** active docs point reviewers to authoritative files first and explicitly say archive material is historical/non-authoritative.

### Task 0.2 - Rename misleading test descriptions and comments
- **Files to edit:** `tests/destructive/*.py`, `scripts/ci-safe-verification.sh`, `PROOF_MATRIX.md`
- **Why:** many tests are not destructive against real state and are not live integration tests.
- **Dependency/order:** after 0.1
- **Risk:** low
- **Done criteria:** naming and proof language make the offline/fixture-backed nature obvious.

### Task 0.3 - Tighten mixed-mode wording
- **Files to edit:** `README.md`, `SYSTEM_STATUS.md`, `docs/SYSTEM_ARCHITECTURE.md`, `PROOF_MATRIX.md`
- **Why:** docs should explicitly say mixed mode is Hyperliquid-primary, one-entry-per-cycle, and not a symmetric dual runtime.
- **Dependency/order:** after 0.1
- **Risk:** low
- **Done criteria:** no active doc can be read as implying a dual-entry mixed runtime.

## Phase 1 - fix canonical architecture

### Task 1.1 - Normalize safety-layer reads through trade schema
- **Files to edit:** `scripts/execution-safety-layer.py`, maybe `models/trade_schema.py`
- **Why:** safety currently reads raw recent trades and assumes `entry_time` and nested `signal` exist; other readers normalize first.
- **Dependency/order:** after Phase 0
- **Risk:** medium
- **Done criteria:** safety uses normalized records consistently and handles missing legacy/raw fields without implicit assumptions.

### Task 1.2 - Remove duplicated exchange-specific price/spread logic from non-canonical monitors where possible
- **Files to edit:** `scripts/exit-monitor.py`, `scripts/timeout-monitor.py`, `utils/paper_exchange_adapters.py`
- **Why:** duplicate exchange logic increases drift risk and confuses which implementation is authoritative.
- **Dependency/order:** after 1.1
- **Risk:** medium
- **Done criteria:** exchange-specific market data access is centralized in adapters or clearly isolated as non-canonical.

### Task 1.3 - Make mode semantics explicit in code, not just docs
- **Files to edit:** `models/exchange_metadata.py`, `scripts/phase1-paper-trader.py`, `scripts/data-integrity-layer.py`, `scripts/trading-agency-phase1.py`
- **Why:** mixed-mode limitations currently emerge from several places; they should be explicit and inspectable.
- **Dependency/order:** after 1.1
- **Risk:** medium
- **Done criteria:** one clearly defined policy source explains mixed-mode entry count, priority, and failure semantics.

## Phase 2 - repair/add tests

### Task 2.1 - Add explicit tests for mixed-mode asymmetry
- **Files to edit:** add `tests/mixed-mode-policy-test.py` or expand `tests/destructive/trading-agency-mixed-test.py`
- **Why:** current docs imply limits, but there is no sharply named test proving Hyperliquid-primary data-gate and selection semantics together.
- **Dependency/order:** after 1.3
- **Risk:** low
- **Done criteria:** test proves: (a) Hyperliquid outage blocks mixed mode, (b) Polymarket outage alone does not, (c) one-entry-per-cycle remains enforced.

### Task 2.2 - Add safety schema-drift regression tests
- **Files to edit:** add `tests/execution-safety-schema-test.py`
- **Why:** safety is the weakest layer for raw-vs-normalized assumptions.
- **Dependency/order:** after 1.1
- **Risk:** low
- **Done criteria:** seeded trade records lacking nested `signal` or using alternate canonical fields do not crash safety validation.

### Task 2.3 - Separate offline end-to-end tests from true integration category
- **Files to edit:** test filenames and `scripts/ci-safe-verification.sh`
- **Why:** evidence quality should be visible from the test name alone.
- **Dependency/order:** after 0.2
- **Risk:** medium
- **Done criteria:** CI names clearly distinguish offline fixture tests from any future live/integration tests.

## Phase 3 - Polymarket integration completion

### Task 3.1 - Decide the product truth: keep paper-only Polymarket or build real Polymarket execution
- **Files to edit:** `README.md`, `SYSTEM_STATUS.md`, maybe add `docs/POLYMARKET_EXECUTION_SCOPE.md`
- **Why:** the repo currently has real paper integration but no live execution path. This needs a deliberate boundary.
- **Dependency/order:** before any real implementation work
- **Risk:** high
- **Done criteria:** repo states either (a) paper-only Polymarket is final scope, or (b) live Polymarket execution is a tracked future milestone with no present claim.

### Task 3.2 - If live Polymarket execution is desired, add a real execution adapter instead of extending paper adapter semantics
- **Files to edit:** add new runtime files rather than overloading `utils/paper_exchange_adapters.py`
- **Why:** paper simulation and real execution should not share the same abstraction blindly.
- **Dependency/order:** after 3.1
- **Risk:** high
- **Done criteria:** explicit authenticated Polymarket execution path exists with credentials/bootstrap checks, isolated from paper mode.

### Task 3.3 - Add live-readiness prerequisites only if real execution is implemented
- **Files to edit:** `scripts/bootstrap-runtime-check.py`, new integration tests/workflows, secrets/config docs
- **Why:** current bootstrap checks only Python modules; that is correct for paper mode and insufficient for live mode.
- **Dependency/order:** after 3.2
- **Risk:** high
- **Done criteria:** bootstrap can prove live prerequisites for the chosen exchange without conflating them with paper mode.

## Phase 4 - observability and docs cleanup

### Task 4.1 - Produce a single authoritative reviewer index
- **Files to edit:** `README.md`, add `TRUTH_INDEX.md` or repurpose `PROOF_MATRIX.md`
- **Why:** reviewers should not need to infer authoritative docs from a large repo.
- **Dependency/order:** after Phase 0
- **Risk:** low
- **Done criteria:** one top-level file maps canonical code, canonical state, test evidence, and non-canonical surfaces.

### Task 4.2 - Mark runtime artifacts by authority level
- **Files to edit:** `docs/RUNTIME_OBSERVABILITY.md`, `scripts/trading-agency-phase1.py`, `scripts/timeout-monitor.py`, `scripts/exit-monitor.py`
- **Why:** not every generated artifact is authoritative state.
- **Dependency/order:** after Phase 1
- **Risk:** low
- **Done criteria:** reports clearly label themselves as authoritative state, derived summary, or monitoring-only output.

### Task 4.3 - Remove or clearly annotate stale root audit artifacts
- **Files to edit:** existing root audit/status markdown files as needed
- **Why:** multiple status reports at repo root create review ambiguity.
- **Dependency/order:** after 4.1
- **Risk:** low
- **Done criteria:** only one current audit/status path is presented as authoritative; others are historical or superseded.

## Priority order summary

1. Truth cleanup of archive/test naming/mixed-mode wording
2. Safety-layer schema normalization and architecture tightening
3. Better tests for mixed-mode semantics and schema drift
4. Explicit decision on whether Polymarket remains paper-only or gets a real execution implementation
5. Observability/doc consolidation

## Final repair target

After Phases 0-2, the repo can honestly claim:
- canonical paper-trading execution exists,
- Hyperliquid is the strongest supported paper path,
- Polymarket is a canonical paper path but experimental overall,
- mixed mode is limited and asymmetric,
- no live-ready claim is made.

After Phase 3, only if real authenticated execution is implemented and proven, the repo could begin making any narrower live-integration claims.
