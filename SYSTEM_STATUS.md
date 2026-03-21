# System Status

**Last Updated:** 2026-03-21 UTC  
**Verdict:** Hyperliquid paper-trading path only; repository cleaned for truthful review

---

## Canonical Active Path

The active path in this repository is limited to the following scripts:

1. `scripts/trading-agency-phase1.py`
2. `scripts/data-integrity-layer.py`
3. `scripts/phase1-signal-scanner.py` in default `hyperliquid_only` mode
4. `scripts/execution-safety-layer.py`
5. `scripts/phase1-paper-trader.py`
6. `scripts/timeout-monitor.py`

This is a **paper-trading-only** path. It is the only path that should be described as canonical.

---

## Explicitly Non-Canonical or Inactive

- **Polymarket execution:** present only as exploratory/incomplete code and research; not active in the canonical flow.
- **`scripts/exit-monitor.py`:** useful as a standalone audit artifact generator, but not safe to describe as part of authoritative close-state persistence.
- **Archived reports:** historical only; retained for review context, not current operational truth.
- **Simulation-only lifecycle artifacts:** archived so they cannot be mistaken for current integration evidence.

---

## What Reviewers Should Trust

Use these files for the current repository description:

- `README.md`
- `docs/SYSTEM_ARCHITECTURE.md`
- `SYSTEM_STATUS.md`
- `docs/REPO_TRUTHFULNESS_AUDIT.md`

Use `docs/archive/` only for historical context.

---

## Scope Limits

- **Execution mode:** paper trading only
- **Canonical exchange:** Hyperliquid only
- **Canonical strategy path:** funding-arbitrage signals accepted by `phase1-paper-trader.py`
- **Polymarket:** disabled/non-canonical
- **Live deployment claim:** not supported

---

## Cleanup Outcome

The repository presentation no longer treats stale repair attempts, speculative rebuild plans, or simulation-only test artifacts as active implementation evidence.
