# System Architecture Summary

## Scope

This document describes the **current canonical Phase 1 paper-trading system** in this repository.

Supported runtime modes:
- **`hyperliquid_only`** — default canonical mode
- **`polymarket_only`** — optional experimental paper mode
- **`mixed`** — optional paper-only evaluation mode

The architecture is still **paper trading only**. No live exchange execution path is supported.

## Execution Flow

The canonical operator path starts with `scripts/trading-agency-phase1.py`.

1. **Bootstrap/runtime verification**
   - `scripts/bootstrap-runtime-check.py` verifies clean-environment runtime dependencies before the orchestrator loads networked scripts.
2. **Optional component detection**
   - The orchestrator reports whether optional components are actually active for the selected mode.
3. **Data integrity gate**
   - `scripts/data-integrity-layer.py` validates source health before scanning.
   - Hyperliquid is checked when Hyperliquid mode is active.
   - Polymarket is checked only when Polymarket mode is active.
4. **Signal scanning**
   - `scripts/phase1-signal-scanner.py` emits canonical executable paper signals.
   - Hyperliquid signals use the funding-arbitrage schema.
   - Polymarket signals use a canonical binary-market paper-trading schema.
5. **Pre-trade safety validation**
   - `scripts/execution-safety-layer.py` validates the next candidate entry.
   - Exchange health, liquidity, spread, freshness, and circuit-breaker checks are exchange-aware.
6. **Paper trade planning**
   - `scripts/phase1-paper-trader.py` builds entry and exit records for both exchanges using one canonical persistence model.
7. **Authoritative state update**
   - Planned trade records are persisted to `workspace/logs/phase1-paper-trades.jsonl`.
   - Canonical open-position state is updated in `workspace/logs/position-state.json`.
8. **Monitor/report stage**
   - The orchestrator runs `scripts/timeout-monitor.py`, which reads canonical open positions and writes monitoring artifacts.
   - The orchestrator does **not** run `scripts/exit-monitor.py` in the canonical loop because that script writes proof artifacts without performing authoritative close-state persistence.

## Canonical State Model

### Append-only trade history
- File: `workspace/logs/phase1-paper-trades.jsonl`
- Purpose: durable event log of canonical paper-trade records for all exchanges
- Shape: normalized by `models/trade_schema.py`

### Authoritative open-position state
- File: `workspace/logs/position-state.json`
- Purpose: current open positions only
- Shape: managed by `models/position_state.py`

### Supporting state
- `workspace/logs/phase1-performance.json` stores normalized closed-trade performance summaries.
- `workspace/operator_control.json` stores human override inputs.
- `workspace/system_status.json` stores current health, recovery, and permissions decisions.

## Exchange-Specific Truth

### Hyperliquid
- Default mode and best-supported path
- Uses funding-arbitrage scanner signals
- Remains the baseline paper-trading mode for reviewers/operators

### Polymarket
- Optional mode only
- Paper-trading only
- Experimental until broader runtime evidence exists
- Uses canonical binary-market paper signals and canonical persistence
- Real execution remains intentionally unsupported

## Non-Canonical Artifacts

The repository still contains supporting scripts that are useful for review but should not be mistaken for authoritative execution:

- `scripts/polymarket-executor.py` — standalone helper/scaffold, not the canonical Polymarket path
- `scripts/exit-monitor.py` — proof/audit generator, not authoritative close persistence
- `scripts/archive/` — legacy or simulation-only artifacts
- `docs/archive/` — historical reports and prior audit history

## What Is Explicitly Out of Scope

To keep the repository truthful, the following should **not** be presented as current capabilities:

- live capital deployment
- production-ready exchange execution
- autonomous real-money Polymarket or Hyperliquid trading
- anything beyond paper-trading orchestration and truth-based operational review
