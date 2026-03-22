# Execution Truth Map

Date: 2026-03-22

## 1. Real canonical entrypoint

**Canonical operator entrypoint:** `scripts/trading-agency-phase1.py`

This is the real top-level runtime. `scripts/bootstrap-runtime-check.py` is only the first stage inside it.

---

## 2. Canonical runtime sequence

1. `scripts/trading-agency-phase1.py`
2. `scripts/bootstrap-runtime-check.py`
3. `scripts/data-integrity-layer.py`
4. `scripts/phase1-signal-scanner.py`
5. `scripts/execution-safety-layer.py`
6. `scripts/phase1-paper-trader.py`
7. `scripts/timeout-monitor.py`
8. report packaging back in `scripts/trading-agency-phase1.py`

---

## 3. Mode handling truth

### `hyperliquid_only`
- Hyperliquid data-integrity checks run.
- Hyperliquid scanner path runs.
- Hyperliquid candidate can be selected.
- Hyperliquid paper trades persist into canonical files.
- This is the default and strongest mode.

### `polymarket_only`
- Polymarket data-integrity checks run.
- Polymarket scanner path runs.
- Polymarket candidate can be selected.
- Polymarket paper trades persist into the same canonical files as Hyperliquid.
- This is a real canonical paper path, but still not live execution.

### `mixed`
- Both scanner paths run.
- Both signal types can be present in `phase1-signals.jsonl`.
- Candidate selection is deterministic and favors Hyperliquid by priority.
- At most one new entry is admitted per cycle.
- This is a constrained evaluation mode, not a true combined dual-entry runtime.

---

## 4. Authoritative files written by the canonical runtime

| File | Authoritative? | Writer | Purpose |
|---|---|---|---|
| `workspace/logs/phase1-signals.jsonl` | Yes for scanner output | `scripts/phase1-signal-scanner.py` | Append-only paper signal history. |
| `workspace/logs/phase1-paper-trades.jsonl` | Yes | `scripts/phase1-paper-trader.py` | Append-only canonical paper trade history. |
| `workspace/logs/position-state.json` | Yes | `models/position_state.py` via trader | Current open positions only. |
| `workspace/logs/phase1-performance.json` | Yes | `scripts/phase1-paper-trader.py` | Closed-trade performance summary. |

## 5. Non-authoritative files written by the canonical runtime

| File | Why non-authoritative |
|---|---|
| `workspace/logs/execution-safety-state.json` | Safety/audit state, not trade truth. |
| `workspace/logs/agency-phase1-report.json` | Derived cycle report. |
| `workspace/logs/agency-cycle-summary.json` | Derived cycle summary. |
| `workspace/AGENCY_CYCLE_SUMMARY.md` | Human-readable derived report. |
| `workspace/logs/timeout-history.jsonl` | Monitoring history only. |
| `workspace/TIMEOUT_MONITOR_REPORT.md` | Monitoring report only. |
| `workspace/system_status.json` | Health/governance summary only. |

---

## 6. Real Polymarket wiring status

Polymarket is **not** just helper code.

It is wired into:
- mode selection: `config/runtime.py`
- connectivity/data gate: `scripts/data-integrity-layer.py`
- scanner: `scripts/phase1-signal-scanner.py`
- adapter layer: `utils/paper_exchange_adapters.py`
- safety checks: `scripts/execution-safety-layer.py`
- trader open/close logic: `scripts/phase1-paper-trader.py`
- shared schema: `models/trade_schema.py`
- shared open-position state: `models/position_state.py`
- timeout monitor: `scripts/timeout-monitor.py`
- dashboard/performance readers: `scripts/performance-dashboard.py`
- agency-level offline tests: `tests/destructive/trading-agency-polymarket-test.py`

### But it is still not full end-to-end exchange integration

Missing pieces:
- authenticated order placement
- exchange account/session integration
- order/fill status reconciliation
- settlement handling
- live execution tests

---

## 7. Real Hyperliquid wiring status

Hyperliquid is the most complete path in the repo:
- default mode
- same canonical flow as Polymarket
- stronger proof coverage, including repeat-cycle agency validation
- deterministic negative-path coverage

Still missing for live-readiness:
- real order execution
- account integration
- fill reconciliation

---

## 8. Files that should not be used to describe current runtime truth

Do not treat these as canonical runtime proof:
- `scripts/exit-monitor.py`
- `scripts/stability-monitor.py`
- `scripts/live-readiness-validator.py`
- anything under `scripts/archive/`
- anything under `docs/archive/`

---

## 9. Current truth statement

The repository currently contains **one real canonical paper-trading architecture** shared by Hyperliquid and Polymarket. Hyperliquid is the default and best-proven path. Polymarket is genuinely wired into that architecture, but only at paper-trading scope. Mixed mode is limited. No live execution path exists.
