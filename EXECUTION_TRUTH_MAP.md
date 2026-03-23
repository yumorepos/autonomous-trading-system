# Execution Truth Map

Date: 2026-03-23 UTC

## Canonical entrypoint

- **Actual entrypoint:** `scripts/trading-agency-phase1.py`
- **Not the entrypoint:** `scripts/bootstrap-runtime-check.py`

## Real execution sequence

1. `scripts/trading-agency-phase1.py`
2. `scripts/bootstrap-runtime-check.py`
3. `utils/system_health.py` state/override refresh
4. `scripts/data-integrity-layer.py` pre-scan gate
5. `scripts/phase1-signal-scanner.py`
6. `scripts/execution-safety-layer.py`
7. `scripts/phase1-paper-trader.py`
8. `models/position_state.py`
9. `scripts/timeout-monitor.py`
10. cycle/report packaging inside `scripts/trading-agency-phase1.py`

## State written in canonical flow

| File | Writer | Truth |
|---|---|---|
| `workspace/logs/phase1-signals.jsonl` | `scripts/phase1-signal-scanner.py` | canonical append-only signal history |
| `workspace/logs/execution-safety-state.json` | `scripts/execution-safety-layer.py` via orchestrator | canonical safety-state snapshot |
| `workspace/logs/blocked-actions.jsonl` | `scripts/execution-safety-layer.py` | canonical record of blocked entries |
| `workspace/logs/phase1-paper-trades.jsonl` | `scripts/phase1-paper-trader.py` | canonical append-only paper trade history |
| `workspace/logs/position-state.json` | `models/position_state.py` | authoritative open-position state |
| `workspace/logs/phase1-performance.json` | `scripts/phase1-paper-trader.py` | canonical closed-trade performance summary |
| `workspace/logs/timeout-history.jsonl` | `scripts/timeout-monitor.py` | monitor-only history |
| `workspace/TIMEOUT_MONITOR_REPORT.md` | `scripts/timeout-monitor.py` | monitor-only human report |
| `workspace/logs/agency-cycle-summary.json` | `scripts/trading-agency-phase1.py` | canonical small per-cycle summary |
| `workspace/AGENCY_CYCLE_SUMMARY.md` | `scripts/trading-agency-phase1.py` | human-readable cycle summary |
| `workspace/logs/agency-phase1-report.json` | `scripts/trading-agency-phase1.py` | full cycle report |
| `workspace/system_health.json` | `utils/system_health.py` | health-state record |
| `workspace/system_status.json` | `utils/system_health.py` | current computed operator/system status |

## Mode truth map

### `hyperliquid_only`

- Scanner includes Hyperliquid only.
- Data-integrity gate requires Hyperliquid only.
- Trade candidate selection can admit only Hyperliquid signals.
- This is the strongest and most-proven path.

### `polymarket_only`

- Scanner includes Polymarket only.
- Data-integrity gate requires Polymarket only.
- Trader, schema, position state, performance, and timeout monitor all support Polymarket.
- This is a real canonical **paper** path, but still experimental overall.

### `mixed`

- Scanner includes both exchanges.
- Data-integrity gate requires Hyperliquid but downgrades Polymarket availability to advisory if Hyperliquid is present.
- Candidate selection sorts by exchange priority then EV score.
- `models/exchange_metadata.py` sets Hyperliquid priority `0` and Polymarket priority `1`.
- Only one new entry is admitted per cycle.
- This is not a dual-entry proof path.

## State-model agreement check

| Subsystem | Shared model alignment |
|---|---|
| scanner | emits exchange-tagged paper signals for both exchanges |
| safety | consumes one candidate signal and uses exchange adapters for health/liquidity/spread |
| trader | converts the signal into OPEN/CLOSED trade records |
| trade schema | normalizes both Hyperliquid and Polymarket records |
| position state | stores open positions from both exchanges in one map |
| timeout monitor | reads canonical open positions and uses exchange thresholds |
| performance dashboard | reads normalized closed trades and canonical open positions |

Conclusion: the main canonical subsystems agree on a single paper-trading state model. The biggest drift risk is not schema mismatch; it is **truth-surface mismatch** between active docs and what the canonical runtime actually calls.

## Non-canonical map

| File | Truth |
|---|---|
| `scripts/exit-monitor.py` | proof/audit only; skipped by orchestrator |
| `scripts/live-readiness-validator.py` | future-scope research model |
| `scripts/stability-monitor.py` | support-only observability |
| `scripts/exit-safeguards.py` | support utility |
| `scripts/position-exit-tracker.py` | support utility |
| `scripts/enhanced-exit-capture.py` | support utility |
| `scripts/archive/*` | historical/scaffold |
| `docs/archive/*` | historical/scaffold |
