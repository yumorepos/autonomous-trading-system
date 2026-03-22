# Repository Truthfulness Audit

**Date:** 2026-03-21  
**Purpose:** define the current truthful scope of the repository after tightening the canonical paper-trading path and downgrading overstated claims.

## Canonical Truth

The repository's active, reviewable canonical path is the **Phase 1 paper-trading flow** driven by:
- `scripts/trading-agency-phase1.py`
- `scripts/bootstrap-runtime-check.py`
- `scripts/data-integrity-layer.py`
- `scripts/phase1-signal-scanner.py`
- `scripts/execution-safety-layer.py`
- `scripts/phase1-paper-trader.py`
- `scripts/timeout-monitor.py`

Supported runtime modes:
- `hyperliquid_only` — default canonical mode
- `polymarket_only` — experimental paper mode
- `mixed` — limited experimental evaluation mode

## What Is Active and Truthful Now

| Artifact | Current Truthful Classification | Why |
|---|---|---|
| `scripts/trading-agency-phase1.py` | KEEP_ACTIVE | Canonical orchestrator for the paper-trading path. |
| `scripts/phase1-signal-scanner.py` | KEEP_ACTIVE | Emits canonical executable paper signals for enabled exchanges. |
| `scripts/phase1-paper-trader.py` | KEEP_ACTIVE | Canonical paper trade planner/persistence path. |
| `models/trade_schema.py` | KEEP_ACTIVE | Canonical normalized trade schema for the paper-trading path. |
| `models/position_state.py` | KEEP_ACTIVE | Authoritative open-position state model. |
| `scripts/timeout-monitor.py` | KEEP_ACTIVE | Canonical monitor script run by the orchestrator. |
| `scripts/performance-dashboard.py` | KEEP_ACTIVE_SUPPORT | Reads canonical trade/state outputs only. |
| `scripts/polymarket-executor.py` | KEEP_NON_CANONICAL | Standalone helper/scaffold only; not the authoritative Polymarket path. |
| `scripts/exit-monitor.py` | KEEP_NON_CANONICAL | Proof/audit generator only; not authoritative close persistence. |
| `scripts/live-readiness-validator.py` | KEEP_NON_CANONICAL_FUTURE_SCOPE | Research model for hypothetical future criteria only. |
| `scripts/stability-monitor.py` | KEEP_NON_CANONICAL_SUPPORT | Support monitor; not part of canonical execution. |
| `.github/workflows/basic.yml` | KEEP_ACTIVE | Required CI-safe verification workflow for every push and pull request. |
| `tests/destructive/*.py` | KEEP_ACTIVE_REPAIRED | Isolated temp-workspace lifecycle tests for canonical paper-trader behavior. |

## Explicit Scope Limits

- paper trading only
- Hyperliquid remains the canonical mode
- Polymarket remains experimental and not fully proven end-to-end
- mixed mode remains limited and should not be presented as a fully proven side-by-side runtime
- live trading is not supported
- supporting dashboards/reports are not proof of live readiness
- CI intentionally avoids flaky network-dependent requirements

## Reviewer Guidance

Trust these files first:
- `README.md`
- `SYSTEM_STATUS.md`
- `docs/OPERATOR_QUICKSTART.md`
- `docs/SYSTEM_ARCHITECTURE.md`
- `docs/REPO_TRUTHFULNESS_AUDIT.md`

Use `docs/archive/` for historical provenance only.
