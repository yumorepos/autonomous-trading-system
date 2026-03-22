# Execution Truth Map

Date: 2026-03-22 UTC

## 1. Canonical entrypoint

**Canonical operator entrypoint:** `scripts/trading-agency-phase1.py`

Why:
- it sequences bootstrap, data integrity, scanning, safety, trade planning, authoritative persistence, timeout monitoring, and final agency reporting
- no other script in the repo performs that full sequence

`scripts/bootstrap-runtime-check.py` is stage 1 inside the canonical loop, not the top-level runtime.

## 2. Canonical flow

1. `scripts/trading-agency-phase1.py`
2. `scripts/bootstrap-runtime-check.py`
3. `scripts/data-integrity-layer.py` (`run_pre_scan_gate`)
4. `scripts/phase1-signal-scanner.py`
5. `scripts/execution-safety-layer.py`
6. `scripts/phase1-paper-trader.py`
7. `scripts/timeout-monitor.py`
8. `scripts/trading-agency-phase1.py` final report generation

## 3. Read/write truth map

| Step | Reads | Writes |
|---|---|---|
| orchestrator startup | env, `config/runtime.py`, health/operator state if present | `workspace/operator_control.json`, `workspace/system_status.json`, `workspace/system_health.json`, `workspace/logs/operator-control-audit.json` |
| bootstrap | importable modules | none |
| data integrity | enabled exchange APIs, existing integrity state | `workspace/logs/data-integrity-state.json`, `workspace/logs/source-reliability-metrics.json`, `workspace/logs/runtime-events.jsonl`, incident logs |
| scanner | enabled exchange APIs | `workspace/logs/phase1-signals.jsonl`, `workspace/PHASE1_SIGNAL_REPORT.md`, `workspace/logs/runtime-events.jsonl` |
| safety | `phase1-signals.jsonl`, `position-state.json`, `phase1-paper-trades.jsonl`, exchange APIs | `workspace/logs/execution-safety-state.json`, `workspace/logs/blocked-actions.jsonl` (optional), incident logs |
| trader persistence | `phase1-signals.jsonl`, `position-state.json`, `phase1-paper-trades.jsonl` | `workspace/logs/phase1-paper-trades.jsonl`, `workspace/logs/position-state.json`, `workspace/logs/phase1-performance.json`, `workspace/logs/runtime-events.jsonl` |
| timeout monitor | `position-state.json`, exchange APIs, `timeout-history.jsonl` | `workspace/logs/timeout-history.jsonl`, `workspace/TIMEOUT_MONITOR_REPORT.md`, `workspace/logs/runtime-events.jsonl` |
| agency finalization | performance/open positions/latest signals/system health | `workspace/logs/agency-phase1-report.json`, `workspace/logs/agency-cycle-summary.json`, `workspace/AGENCY_CYCLE_SUMMARY.md`, refreshed `workspace/system_status.json` |

## 4. Authoritative vs non-authoritative outputs

### Authoritative
- `workspace/logs/phase1-paper-trades.jsonl`
- `workspace/logs/position-state.json`
- `workspace/logs/phase1-performance.json`

### Control/health
- `workspace/operator_control.json`
- `workspace/system_status.json`
- `workspace/system_health.json`
- `workspace/logs/execution-safety-state.json`
- `workspace/logs/data-integrity-state.json`

### Observability/support
- `workspace/logs/runtime-events.jsonl`
- `workspace/logs/system-incidents.jsonl`
- `workspace/logs/blocked-actions.jsonl`
- `workspace/logs/timeout-history.jsonl`
- `workspace/logs/agency-phase1-report.json`
- `workspace/logs/agency-cycle-summary.json`
- `workspace/AGENCY_CYCLE_SUMMARY.md`
- `workspace/PHASE1_SIGNAL_REPORT.md`
- `workspace/TIMEOUT_MONITOR_REPORT.md`

## 5. Authoritative files vs non-canonical files

### Canonical runtime files
- `config/runtime.py`
- `models/trade_schema.py`
- `models/position_state.py`
- `scripts/trading-agency-phase1.py`
- `scripts/bootstrap-runtime-check.py`
- `scripts/data-integrity-layer.py`
- `scripts/phase1-signal-scanner.py`
- `scripts/execution-safety-layer.py`
- `scripts/phase1-paper-trader.py`
- `scripts/timeout-monitor.py`
- `utils/json_utils.py`
- `utils/runtime_logging.py`
- `utils/system_health.py`

### Support-only / non-canonical / historical
- `scripts/polymarket-executor.py`
- `scripts/exit-monitor.py`
- `scripts/enhanced-exit-capture.py`
- `scripts/exit-safeguards.py`
- `scripts/position-exit-tracker.py`
- `scripts/live-readiness-validator.py`
- `scripts/stability-monitor.py`
- `scripts/alpha-intelligence-layer.py`
- `scripts/portfolio-allocator.py`
- `scripts/supervisor-governance.py`
- `scripts/archive/`
- `docs/archive/`

## 6. Mode truth map

### `hyperliquid_only`
- canonical default mode
- strongest coverage and proof
- real canonical path from scanner through persistence is present and offline-proven

### `polymarket_only`
- real canonical paper mode
- scanner, safety, trader, persistence, and timeout monitor all have explicit Polymarket handling
- still experimental because there is no live execution path and the repo still has non-canonical Polymarket leftovers

### `mixed`
- real mode, not fake
- scanner can emit both Hyperliquid and Polymarket signals in the same cycle
- canonical persistence model is shared across exchanges
- limitation: one cycle selects at most one new entry, so mixed is not a dual-entry-per-cycle engine

## 7. Current evidence source

Truth in this repo comes from:
1. active code
2. CI-safe offline tests
3. support docs that still match the code

Truth does **not** come from checked-in runtime logs. The committed `workspace/` directory contains only defaults, not real canonical trade history.
