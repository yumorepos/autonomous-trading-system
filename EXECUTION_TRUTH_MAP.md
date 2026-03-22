# Execution Truth Map

Date: 2026-03-21 UTC
Purpose: map the real canonical execution path and separate it from adjacent support or historical paths.

## 1. Actual canonical entrypoint

**Canonical operator entrypoint:** `scripts/trading-agency-phase1.py`

Reason:
- It is the only script that sequences bootstrap, integrity, scanner, safety, trader, authoritative persistence, monitors, health snapshots, and final agency reporting.
- `scripts/bootstrap-runtime-check.py` is stage 1 inside that flow, not the top-level operator runtime.

## 2. Canonical flow, exactly

1. `scripts/trading-agency-phase1.py`
2. `scripts/bootstrap-runtime-check.py`
3. `scripts/data-integrity-layer.py` (`run_pre_scan_gate` via module load)
4. `scripts/phase1-signal-scanner.py`
5. `scripts/execution-safety-layer.py` (proposal validation via module load)
6. `scripts/phase1-paper-trader.py` (build plan, then persist)
7. `scripts/timeout-monitor.py`
8. `scripts/trading-agency-phase1.py` writes final agency report

## 3. Canonical read/write map

| Step | Reads | Writes |
|---|---|---|
| `trading-agency-phase1.py` startup | env, `config/runtime.py`, health/operator files if present | `workspace/operator_control.json`, `workspace/system_status.json`, `workspace/system_health.json`, `workspace/logs/operator-control-audit.json` |
| bootstrap | importable modules | none |
| data integrity gate | exchange APIs, existing integrity metrics/state | `workspace/logs/data-integrity-state.json`, `workspace/logs/source-reliability-metrics.json`, `workspace/logs/runtime-events.jsonl`, incident logs |
| signal scanner | exchange APIs | `workspace/logs/phase1-signals.jsonl`, `workspace/PHASE1_SIGNAL_REPORT.md`, `workspace/logs/runtime-events.jsonl` |
| safety validation | `phase1-signals.jsonl`, `position-state.json`, `phase1-paper-trades.jsonl`, exchange APIs | `workspace/logs/execution-safety-state.json`, `workspace/logs/blocked-actions.jsonl` (optional), incident logs |
| trader persistence | `phase1-signals.jsonl`, `position-state.json`, `phase1-paper-trades.jsonl` | `workspace/logs/phase1-paper-trades.jsonl`, `workspace/logs/position-state.json`, `workspace/logs/phase1-performance.json`, `workspace/logs/runtime-events.jsonl` |
| timeout monitor | `position-state.json`, exchange APIs, `timeout-history.jsonl` | `workspace/logs/timeout-history.jsonl`, `workspace/TIMEOUT_MONITOR_REPORT.md`, `workspace/logs/runtime-events.jsonl` |
| agency finalization | performance/open positions/latest signals/system health | `workspace/logs/agency-phase1-report.json`, refreshed `workspace/system_status.json` |

## 4. State truth hierarchy

### Tier 1: authoritative state
- `workspace/logs/phase1-paper-trades.jsonl`
- `workspace/logs/position-state.json`
- `workspace/logs/phase1-performance.json`

### Tier 2: control/health state
- `workspace/operator_control.json`
- `workspace/system_status.json`
- `workspace/system_health.json`
- `workspace/logs/execution-safety-state.json`
- `workspace/logs/data-integrity-state.json`

### Tier 3: observability/support artifacts
- `workspace/logs/runtime-events.jsonl`
- `workspace/logs/system-incidents.jsonl`
- `workspace/logs/incident-log.jsonl`
- `workspace/logs/timeout-history.jsonl`
- `workspace/logs/agency-phase1-report.json`
- `workspace/PHASE1_SIGNAL_REPORT.md`
- `workspace/TIMEOUT_MONITOR_REPORT.md`

## 5. Non-canonical paths that must not be mistaken for canonical runtime

| File | Why non-canonical |
|---|---|
| `scripts/polymarket-executor.py` | Standalone helper; maintains its own `polymarket-trades.jsonl` and `polymarket-state.json`; not called by the orchestrator. |
| `scripts/exit-monitor.py` | Produces audit/proof artifacts only; orchestrator explicitly skips it. |
| `scripts/exit-safeguards.py` | Support utility; not part of canonical state mutation. |
| `scripts/enhanced-exit-capture.py` | Support/proof workflow; not the authoritative close path. |
| `scripts/position-exit-tracker.py` | Support analytics, not canonical execution. |
| `scripts/live-readiness-validator.py` | Future-scope research model, not runtime execution. |
| `scripts/stability-monitor.py` | Support monitor; also references non-canonical Polymarket state. |
| `scripts/alpha-intelligence-layer.py` | Research analytics on canonical trade history; not execution. |
| `scripts/portfolio-allocator.py` | Research allocation layer; not runtime gating in the canonical loop. |
| `scripts/supervisor-governance.py` | Governance metadata, not execution. |

## 6. State-model agreement audit

### Where the model agrees
- All canonical entry/close persistence flows use `workspace/logs/phase1-paper-trades.jsonl`.
- All canonical open-position reads use `workspace/logs/position-state.json`.
- Timeout monitor, dashboard, and paper trader all read the same authoritative open-position file.

### Where the model does not fully agree
- `models/trade_schema.py` normalizes a reduced flat schema.
- `models/position_state.py` stores exchange and Polymarket-specific fields outside that reduced canonical field list.
- `scripts/performance-dashboard.py` recovers exchange membership from raw data rather than a first-class normalized field.
- `scripts/live-readiness-validator.py` still reads `workspace/logs/polymarket-trades.jsonl`, which is not canonical.
- `scripts/stability-monitor.py` still treats `polymarket-state.json` as a state file when Polymarket mode is active.

## 7. Mode truth map

### `hyperliquid_only`
- Canonical and strongest path.
- Scanner, safety, trader, persistence, and timeout monitor all support it.
- Best lifecycle test coverage exists here.

### `polymarket_only`
- Canonical paper path exists.
- Scanner, safety, trader, persistence, and timeout monitor all contain explicit Polymarket handling.
- Still experimental and less proven than Hyperliquid.

### `mixed`
- Mode is real and canonical.
- Scanner can include both exchanges.
- Shared persistence model is used.
- Limitation: one cycle selects at most one new entry, so mixed mode is not a fully parallel dual-entry engine.

## 8. Current runtime evidence in the checked-in workspace

The checked-in `workspace/` contains only:
- `workspace/README.md`
- `workspace/operator_control.json`
- `workspace/system_status.json`

It does **not** contain checked-in canonical trade logs or position state from a real repo run. Current truth therefore comes from code and tests, not repository-shipped runtime evidence.
