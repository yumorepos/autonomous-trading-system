# Execution Truth Map

Audit date: 2026-03-23 UTC

## Canonical entrypoint

- **Canonical operator entrypoint:** `scripts/trading-agency-phase1.py`
- **Not the canonical entrypoint:** `scripts/bootstrap-runtime-check.py`
- **Explicitly non-canonical in the main loop:** `scripts/exit-monitor.py`

## Authoritative code path

1. `config/runtime.py`
   - Resolves workspace paths and creates directories.

2. `scripts/trading-agency-phase1.py`
   - Main orchestrator.
   - Prints mode truth statement.
   - Creates `SystemHealthManager`.

3. `scripts/bootstrap-runtime-check.py`
   - Dependency-only bootstrap stage.

4. `utils/system_health.py`
   - Writes / refreshes:
     - `workspace/operator_control.json`
     - `workspace/system_health.json`
     - `workspace/system_status.json`
     - `workspace/logs/operator-control-audit.json`
     - incident/operator logs as needed

5. `scripts/data-integrity-layer.py`
   - Pre-scan source health gate.
   - Writes:
     - `workspace/logs/data-integrity-state.json`
     - `workspace/logs/source-reliability-metrics.json`
     - `workspace/DATA_HEALTH_REPORT.md` in standalone mode
     - runtime events / incidents

6. `scripts/phase1-signal-scanner.py`
   - Generates paper signals for enabled exchanges.
   - Calls signal integrity validation before append.
   - Writes:
     - `workspace/logs/phase1-signals.jsonl`
     - `workspace/PHASE1_SIGNAL_REPORT.md`
     - runtime events

7. `scripts/execution-safety-layer.py`
   - Validates one selected candidate entry.
   - Writes:
     - `workspace/logs/execution-safety-state.json`
     - `workspace/logs/blocked-actions.jsonl` when blocking
     - `workspace/logs/incident-log.jsonl`

8. `scripts/phase1-paper-trader.py`
   - Builds exit records first, then possibly one new entry record.
   - Uses `utils/paper_exchange_adapters.py`.
   - Persists via:
     - `workspace/logs/phase1-paper-trades.jsonl`
     - `workspace/logs/position-state.json`
     - `workspace/logs/phase1-performance.json`
     - runtime events

9. `scripts/timeout-monitor.py`
   - Reads authoritative open-position state only.
   - Writes monitoring artifacts only:
     - `workspace/logs/timeout-history.jsonl`
     - `workspace/TIMEOUT_MONITOR_REPORT.md`
     - runtime events

10. `scripts/trading-agency-phase1.py` final reporting
    - Writes:
      - `workspace/logs/agency-cycle-summary.json`
      - `workspace/AGENCY_CYCLE_SUMMARY.md`
      - `workspace/logs/agency-phase1-report.json`

## State model agreement

### Files that agree on the canonical trade/state model

- `models/trade_schema.py`
- `models/position_state.py`
- `scripts/phase1-paper-trader.py`
- `scripts/performance-dashboard.py`
- `scripts/execution-safety-layer.py`
- `scripts/timeout-monitor.py`
- `scripts/exit-monitor.py` (reader only; non-canonical)

### What currently agrees

- One append-only trade history file for both exchanges.
- One authoritative open-position file for both exchanges.
- Performance is derived from normalized closed trades only.
- Dashboard and monitors read the same canonical outputs.
- Scanner integrity now enforces the paper adapter's declared exchange-specific signal contracts before persistence.

### Where agreement is still imperfect

- Signal executability and canonical paper-trade/open-position requirements are now centralized in `models/paper_contracts.py` and consumed by the canonical validators, trader, persistence layer, and key readers.
- Remaining asymmetries are intentional, not accidental: Polymarket records require `market_id`, Polymarket stays experimental overall, and mixed mode still gives deterministic priority to Hyperliquid.

## Mode truth map

### `hyperliquid_only`

- Includes Hyperliquid scanner/integrity/safety/trader path.
- Excludes Polymarket from scanner and pre-scan integrity gate.
- This is the best-supported canonical mode.

### `polymarket_only`

- Includes Polymarket scanner/integrity/safety/trader path.
- Excludes Hyperliquid from scanner and pre-scan integrity gate.
- This is a real canonical **paper** path, but still experimental overall.

### `mixed`

- Scans both exchanges.
- Data integrity treats Polymarket as secondary/advisory when Hyperliquid is also enabled.
- Trader selects at most **one** new candidate per cycle.
- Exchange priority prefers Hyperliquid.
- This is not a dual-entry proof path.

## Non-canonical and historical surfaces

### Non-canonical support scripts

- `scripts/exit-monitor.py`
- `scripts/live-readiness-validator.py`
- `scripts/stability-monitor.py`
- `scripts/supervisor-governance.py`

### Historical/scaffold surfaces

- `scripts/archive/`
- `docs/archive/`

### Labeled active-doc examples that remain non-authoritative

- `docs/TIMEOUT_MONITOR_REPORT.md`
- `docs/POSITION_TRACKING_REPORT.md`
- `docs/EXIT_TRACKER_REPORT.md`

These files are now explicitly marked non-canonical/historical examples and should not be used as canonical capability evidence.
