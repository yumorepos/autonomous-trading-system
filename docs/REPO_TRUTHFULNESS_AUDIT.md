# Repository Truthfulness Audit

**Date:** 2026-03-21  
**Purpose:** classify stale or misleading artifacts and make the canonical Hyperliquid paper-trading path easier to review.

## Canonical Truth

The repository's active, reviewable path is the **Hyperliquid Phase 1 paper-trading flow** driven by `scripts/trading-agency-phase1.py` and `scripts/phase1-paper-trader.py`.

Anything outside that path should be treated as one of:
- historical archive
- exploratory/non-canonical work
- simulation-only evidence
- standalone operational support that is not authoritative execution

## Artifact Classification

| Artifact | Classification | Action Taken | Why |
|---|---|---|---|
| `scripts/phase1-paper-trader.py` | KEEP_ACTIVE | Left untouched | Canonical paper trader. |
| `scripts/trading-agency-phase1.py` | KEEP_ACTIVE | Left untouched | Canonical orchestrator. |
| `scripts/phase1-signal-scanner.py` | KEEP_ACTIVE | Left untouched | Canonical scanner in default Hyperliquid-only mode. |
| `scripts/phase1-paper-trader-FIXED.py` | ARCHIVE | Moved to `scripts/archive/phase1-paper-trader-fixed-legacy.py` | Old alternate trader path could be mistaken for the active implementation. |
| `scripts/test-paper-trader-fixes.py` | ARCHIVE | Moved to `scripts/archive/test-paper-trader-fixes-legacy.py` | Test targeted the archived alternate trader, not the canonical one. |
| `scripts/test-full-lifecycle.py` | ARCHIVE | Moved to `scripts/archive/test-full-lifecycle-simulation.py` | Simulation-only artifact included Polymarket mock trades and looked more authoritative than it was. |
| `tests/destructive/full-lifecycle-integration-test.py` | REWRITE | Left in place, but intentionally treated as isolated/destructive only | Uses a temp workspace; still useful, but should not be cited as live-state validation. |
| `tests/destructive/real-exit-integration-test.py` | KEEP_ACTIVE | Left in place | Exercises the real exit path in an isolated temp workspace and is clearly labeled destructive. |
| `SYSTEM_STATUS.md` | REWRITE | Rewritten | Reduced to a current, scoped, reviewer-facing truth document. |
| `README.md` | KEEP_ACTIVE | Minor truthfulness alignment retained | Already reflected current canonical scope. |
| `docs/SYSTEM_ARCHITECTURE.md` | KEEP_ACTIVE | Minor truthfulness alignment retained | Already described the canonical path accurately. |
| `docs/HONEST_REAUDIT.md` | ARCHIVE | Moved to `docs/archive/HONEST_REAUDIT.md` | Historical audit snapshot, not the current repo summary. |
| `docs/PROVING_PHASE_STATUS.md` | ARCHIVE | Moved to `docs/archive/PROVING_PHASE_STATUS.md` | Time-bound status doc with stale operational claims. |
| `docs/LIFECYCLE_TEST_REPORT.md` | ARCHIVE | Moved to `docs/archive/LIFECYCLE_TEST_REPORT.md` | Simulation report included Polymarket lifecycle claims that are not canonical. |
| `CANONICAL_PATH_AUDIT.md` | ARCHIVE | Moved to `docs/archive/root-history/` | Historical investigation, not current source of truth. |
| `STRATEGY_STATUS_MATRIX.md` | ARCHIVE | Moved to `docs/archive/root-history/` | Overemphasized alternate/stale implementation paths. |
| `SYSTEM_REPAIR_REPORT.md` | ARCHIVE | Moved to `docs/archive/root-history/` | Claimed fixes via a non-canonical file. |
| `INTEGRATION_EVIDENCE_REPORT.md` | ARCHIVE | Moved to `docs/archive/root-history/` | Historical evidence snapshot; not current public truth. |
| `EVIDENCE_AUDIT_HONEST.md` | ARCHIVE | Moved to `docs/archive/root-history/` | Historical audit retained for provenance only. |
| `AUTHORITATIVE_STATE_MAP.md` | ARCHIVE | Moved to `docs/archive/root-history/` | Historical state-model critique; no longer a top-level truth doc. |
| `POLYMARKET_REBUILD_SPEC.md` | ARCHIVE | Moved to `docs/archive/root-history/` | Exploratory rebuild plan should not present Polymarket as active or near-active. |

## What Was Misleading Before

- A second trader file with `FIXED` in the filename sat beside the canonical trader, making the active path ambiguous.
- A matching test suite validated the archived alternate trader rather than the canonical one.
- A simulation-only lifecycle script and report included **Polymarket** mock trades, which could be mistaken for support in the active system.
- Several top-level reports read like current status documents even though they were point-in-time audit notes, repair plans, or contradictory findings.
- Polymarket rebuild/spec materials were easy to read as roadmap-adjacent implementation rather than dormant exploratory work.

## What Is Truthful Now

- The top-level repository entry points point reviewers toward the actual Hyperliquid paper-trading path.
- Historical and speculative materials are isolated under `docs/archive/` and `scripts/archive/`.
- Simulation-only artifacts are no longer mixed into active-looking script locations.
- The remaining active status docs are scoped to present reality rather than old repair narratives.

## Remaining Intentional Exceptions

- `scripts/polymarket-executor.py` remains in place because it is already labeled as exploratory/disabled scaffold code; removing it is not necessary for truthfulness.
- `docs/POLYMARKET_TESTNET_RESEARCH.md` remains in place because it is research, not an execution claim. It should still be read as background only.
- `tests/destructive/full-lifecycle-integration-test.py` remains because it is clearly isolated to a temp workspace and still offers review value when described honestly.

## Final Review Verdict

**TRUTHFUL_AND_CLEAN**
