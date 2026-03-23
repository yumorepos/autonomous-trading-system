# EXECUTION_TRUTH_MAP

Date: 2026-03-23 UTC

## 1. Canonical execution path

```text
scripts/trading-agency-phase1.py
  -> scripts/bootstrap-runtime-check.py
  -> scripts/data-integrity-layer.py
  -> scripts/phase1-signal-scanner.py
  -> scripts/execution-safety-layer.py
  -> scripts/phase1-paper-trader.py
  -> models/position_state.py
  -> models/trade_schema.py
  -> scripts/timeout-monitor.py
  -> agency summary/report outputs
```

## 2. Real write path by stage

### bootstrap
- No authoritative trading-state writes.
- Dependency presence only.

### data integrity
Writes:
- `workspace/logs/data-integrity-state.json`
- `workspace/logs/source-reliability-metrics.json`
- health/operator files via `utils/system_health.py`

### signal scanner
Writes:
- `workspace/logs/phase1-signals.jsonl`
- `workspace/PHASE1_SIGNAL_REPORT.md`
- `workspace/logs/runtime-events.jsonl`

### safety validation
Writes:
- `workspace/logs/execution-safety-state.json`
- maybe `workspace/logs/blocked-actions.jsonl`
- maybe `workspace/logs/incident-log.jsonl`
- health/operator files via `utils/system_health.py`

### paper trader authoritative persistence
Writes:
- `workspace/logs/phase1-paper-trades.jsonl`
- `workspace/logs/position-state.json`
- `workspace/logs/phase1-performance.json`
- `workspace/logs/runtime-events.jsonl`

### monitor stage
Actually runs:
- `scripts/timeout-monitor.py`

Writes:
- `workspace/logs/timeout-history.jsonl`
- `workspace/TIMEOUT_MONITOR_REPORT.md`
- `workspace/logs/runtime-events.jsonl`

Explicitly does **not** authoritatively run:
- `scripts/exit-monitor.py`

### cycle/report packaging
Writes:
- `workspace/logs/agency-cycle-summary.json`
- `workspace/AGENCY_CYCLE_SUMMARY.md`
- `workspace/logs/agency-phase1-report.json`
- `workspace/system_health.json`
- `workspace/system_status.json`
- `workspace/operator_control.json` if missing
- incident/operator audit logs under `workspace/logs/`

## 3. State truth map

### Authoritative state

| File | Truth role |
|---|---|
| `workspace/logs/phase1-paper-trades.jsonl` | append-only canonical paper trade history |
| `workspace/logs/position-state.json` | authoritative current open positions |
| `workspace/logs/phase1-performance.json` | derived closed-trade summary |

### Supporting but non-authoritative

| File | Truth role |
|---|---|
| `workspace/logs/phase1-signals.jsonl` | scanner output history |
| `workspace/logs/execution-safety-state.json` | safety/runtime checkpoint state |
| `workspace/logs/timeout-history.jsonl` | monitoring history only |
| `workspace/logs/agency-cycle-summary.json` | cycle summary for operators |
| `workspace/logs/agency-phase1-report.json` | supervisor/operator report |
| `workspace/TIMEOUT_MONITOR_REPORT.md` | human-readable monitor report only |
| `workspace/AGENCY_CYCLE_SUMMARY.md` | human-readable cycle summary only |

## 4. Truth map by runtime mode

### `hyperliquid_only`
- Canonical default.
- Full paper path exists and is best-covered by tests.
- Real runtime still depends on external market-data availability.

### `polymarket_only`
- Canonical paper path exists.
- Uses same orchestrator/safety/trader/persistence/monitor stack.
- Experimental overall.
- No authenticated Polymarket execution path exists.

### `mixed`
- Scanner can generate both exchanges.
- Shared state model can hold both exchanges.
- Canonical agency runtime is not dual-entry; it admits at most one new entry per cycle.
- Exchange priority makes Hyperliquid the deterministic winner for the single admitted entry.
- Data-integrity semantics are asymmetric and Hyperliquid-primary.

## 5. Files that look important but are not canonical

| File | Why not canonical |
|---|---|
| `scripts/exit-monitor.py` | proof/audit only; skipped by orchestrator |
| `scripts/live-readiness-validator.py` | future-scope research model |
| `scripts/stability-monitor.py` | support-only observability |
| `scripts/exit-safeguards.py` | support utility |
| `scripts/position-exit-tracker.py` | support utility |
| `scripts/enhanced-exit-capture.py` | support utility |
| `scripts/archive/*` | historical |
| `docs/archive/*` | historical |

## 6. What tests really prove

### Proven
- Offline canonical agency path for Hyperliquid.
- Offline canonical agency path for Polymarket.
- Negative-path blocking.
- Repeat-cycle Hyperliquid stability.
- Shared state/schema compatibility across both exchanges.
- Timeout-monitor reader compatibility.

### Not proven
- Live exchange reachability as a merge blocker.
- Authenticated execution.
- Real-money trading.
- Symmetric mixed-mode dual execution.
- Production readiness.
