# Repository Truthfulness Audit

**Date:** 2026-03-21  
**Purpose:** define the current truthful scope of the repository after aligning Hyperliquid and optional Polymarket paper-trading paths to one canonical architecture.

## Canonical Truth

The repository's active, reviewable architecture is the **Phase 1 paper-trading flow** driven by:

- `scripts/bootstrap-runtime-check.py`
- `scripts/trading-agency-phase1.py`
- `scripts/data-integrity-layer.py`
- `scripts/phase1-signal-scanner.py`
- `scripts/execution-safety-layer.py`
- `scripts/phase1-paper-trader.py`
- `scripts/timeout-monitor.py`

Supported runtime modes:
- `hyperliquid_only` — default canonical mode
- `polymarket_only` — optional experimental paper mode
- `mixed` — optional paper-only evaluation mode

## What Is Active and Truthful Now

| Artifact | Current Truthful Classification | Why |
|---|---|---|
| `scripts/trading-agency-phase1.py` | KEEP_ACTIVE | Canonical orchestrator for paper-trading modes. |
| `scripts/phase1-signal-scanner.py` | KEEP_ACTIVE | Emits canonical executable paper signals for enabled exchanges. |
| `scripts/phase1-paper-trader.py` | KEEP_ACTIVE | Canonical paper trade planner/persistence path for both exchanges. |
| `models/trade_schema.py` | KEEP_ACTIVE | Canonical normalized trade schema. |
| `models/position_state.py` | KEEP_ACTIVE | Authoritative open-position state model. |
| `scripts/timeout-monitor.py` | KEEP_ACTIVE | Canonical monitor script run by orchestrator. |
| `scripts/polymarket-executor.py` | KEEP_NON_CANONICAL | Standalone helper/scaffold only; not the authoritative Polymarket path. |
| `scripts/exit-monitor.py` | KEEP_NON_CANONICAL | Proof/audit generator only; not authoritative close persistence. |
| `scripts/performance-dashboard.py` | KEEP_ACTIVE_RELABELED | Useful dashboard, but labels now distinguish canonical vs optional experimental paths. |
| `scripts/stability-monitor.py` | KEEP_ACTIVE_RESCOPED | Mode-aware support monitor rather than an unconditional multi-exchange status claim. |
| `tests/destructive/*.py` | KEEP_ACTIVE_REPAIRED | Temp-workspace lifecycle tests updated to canonical state model. |

## Explicit Scope Limits

- paper trading only
- Hyperliquid remains the default mode
- Polymarket remains optional and experimental
- live trading is not supported
- supporting dashboards/reports are not proof of live readiness

## Reviewer Guidance

Trust these files first:

- `README.md`
- `SYSTEM_STATUS.md`
- `docs/SYSTEM_ARCHITECTURE.md`
- `docs/REPO_TRUTHFULNESS_AUDIT.md`

Use `docs/archive/` for historical provenance only.
