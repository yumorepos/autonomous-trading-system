# System Architecture Summary

## Scope

This document describes the **current canonical Phase 1 paper-trading system** in this repository.

Supported runtime modes:
- **`hyperliquid_only`** — default canonical mode
- **`polymarket_only`** — optional experimental paper mode
- **`mixed`** — optional paper-only evaluation mode

The architecture is strictly **paper trading only**. No live exchange execution path is implemented.

## Canonical Execution Flow

The canonical operator path starts with `scripts/trading-agency-phase1.py`.

1. **Bootstrap/runtime verification**
   - `scripts/bootstrap-runtime-check.py` verifies local runtime dependencies before the orchestrator loads networked scripts.
2. **Optional component detection**
   - The orchestrator reports which optional components are present for the selected mode.
3. **Data integrity gate**
   - `scripts/data-integrity-layer.py` validates source health only for exchanges enabled by the current mode.
4. **Signal scanning**
   - `scripts/phase1-signal-scanner.py` emits canonical executable paper signals.
5. **Pre-trade safety validation**
   - `scripts/execution-safety-layer.py` validates the next candidate paper entry.
6. **Paper trade planning**
   - `scripts/phase1-paper-trader.py` builds normalized entry/exit records for both exchanges.
7. **Authoritative state update**
   - Canonical records are persisted to `workspace/logs/phase1-paper-trades.jsonl` and `workspace/logs/position-state.json`.
8. **Monitor/report stage**
   - `scripts/timeout-monitor.py` reads canonical open positions and writes paper-trading monitoring artifacts.

## Canonical State Model

### Append-only trade history
- File: `workspace/logs/phase1-paper-trades.jsonl`
- Purpose: durable event log of canonical paper-trade records for all supported exchange paths
- Shape: normalized by `models/trade_schema.py`

### Authoritative open-position state
- File: `workspace/logs/position-state.json`
- Purpose: current open positions only
- Shape: managed by `models/position_state.py`

### Supporting state
- `workspace/logs/phase1-performance.json` stores normalized closed-trade performance summaries.
- `workspace/operator_control.json` stores human override inputs.
- `workspace/system_status.json` stores current health, recovery, and permissions decisions.

## Mode-Aware Behavior

### `hyperliquid_only`
- scans Hyperliquid only
- validates Hyperliquid only
- baseline review mode and best-supported path

### `polymarket_only`
- scans Polymarket only
- validates Polymarket only
- optional, paper-only, experimental

### `mixed`
- scans both exchanges
- persists both exchanges into the same canonical state model
- intended for side-by-side paper evaluation only

## What Is Proven

The verification suite currently proves:

- bootstrap dependency checking works
- active Python code compiles cleanly
- mode-aware integrity gating respects selected runtime mode
- Hyperliquid and Polymarket paper signals conform to expected normalized schema
- canonical state survives isolated lifecycle tests for Hyperliquid, Polymarket, and mixed-mode flows
- dashboard and timeout-monitor support scripts can read canonical outputs as expected

## What Is Not Proven

- no live-trading path exists to verify
- external API reachability is not enforced in CI
- forward performance is not represented as a production-readiness claim

## Non-Canonical Artifacts

The repository still contains supporting scripts useful for review, but they should not be mistaken for authoritative execution:

- `scripts/polymarket-executor.py` — standalone helper/scaffold
- `scripts/exit-monitor.py` — proof/audit generator, not authoritative close persistence
- `scripts/live-readiness-validator.py` — future-scope research model only
- `scripts/archive/` — historical or simulation-only artifacts
- `docs/archive/` — historical reports and prior audit history

## Explicitly Out of Scope

The following must **not** be presented as current capabilities:

- live capital deployment
- production-ready exchange execution
- autonomous real-money Hyperliquid or Polymarket trading
- anything beyond paper-trading orchestration, persistence, observability, and reviewable research validation
