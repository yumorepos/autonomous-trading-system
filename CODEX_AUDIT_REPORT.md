# CODEX Audit Report

Date: 2026-03-22 UTC  
Repo: `yumorepos/autonomous-trading-system`

## Scope

Audit target:
- actual canonical entrypoint and execution path
- Hyperliquid and Polymarket wiring in code
- mode handling (`hyperliquid_only`, `polymarket_only`, `mixed`)
- state-model agreement across orchestrator, scanner, safety, trader, monitors, schemas, and persistence
- CI/test proof surface versus documentation claims
- dead code, stale docs, duplicate state models, and misleading artifacts

Method:
- inspected runtime/config/model/test/doc/workflow files in the active tree
- ran the repo verification suite: `./scripts/ci-safe-verification.sh`
- ran read-only connectivity checks for Hyperliquid and Polymarket from this environment
- treated code/tests as authoritative over markdown

---

## A. Executive Verdict

| Question | Verdict | Exact basis |
|---|---|---|
| Is Hyperliquid properly integrated? | **Yes, for the paper-trading canonical path** | The canonical flow is wired end-to-end through `scripts/trading-agency-phase1.py` -> integrity -> scanner -> safety -> trader -> canonical persistence -> timeout monitor, and CI runs offline agency tests that prove the Hyperliquid path across entry, exit, reports, and state files. |
| Is Polymarket properly integrated? | **Partial** | Polymarket is wired into the same canonical paper-trading flow and CI now proves the offline agency path in `polymarket_only`, but it remains explicitly experimental, has no live execution path, still coexists with a non-canonical `polymarket-executor.py`, and depends on the same read-only market-data endpoint for scan/safety/exit pricing. |
| Is the repo truthfully represented? | **Partial** | Top-level docs are mostly honest about paper-only scope and Polymarket being experimental, but some active docs and previously generated root audit files are stale and now contradict the current code/test reality. |
| Is the system paper-trading only? | **Yes** | The canonical flow only produces paper records. Live execution is not implemented in the canonical runtime, and `scripts/polymarket-executor.py` explicitly states real Polymarket execution is incomplete/disabled. |
| Is there any live-ready claim that should be removed? | **Yes** | Any remaining live-readiness framing should be removed or quarantined to future-scope research files because the repo is not live-ready and does not implement real-money execution. |

### Direct conclusion

Current truthful statement:
- **Hyperliquid is integrated in the canonical paper-trading path.**
- **Polymarket is integrated into that same paper-trading path, but only as an experimental paper-runtime.**
- **Nothing in this repo is live-ready.**

---

## B. Evidence Table

| Component | Status | Evidence file paths | Exact reason |
|---|---|---|---|
| bootstrap/runtime check | **working** | `scripts/bootstrap-runtime-check.py`, `tests/bootstrap-runtime-check-test.py` | Minimal dependency gate; proves required imports only. |
| orchestrator | **working** | `scripts/trading-agency-phase1.py`, `tests/destructive/trading-agency-hyperliquid-test.py`, `tests/destructive/trading-agency-polymarket-test.py`, `tests/destructive/trading-agency-mixed-test.py`, `scripts/ci-safe-verification.sh`, `.github/workflows/basic.yml` | This is the real canonical entrypoint and CI now executes it offline for Hyperliquid, Polymarket, mixed-mode limitation, and negative paths. |
| data integrity layer | **working** | `scripts/data-integrity-layer.py`, `config/runtime.py`, `tests/data-integrity-mode-gate-test.py`, `tests/support/offline_requests_sitecustomize.py` | Mode-aware gate is real; `polymarket_only` no longer requires Hyperliquid. It writes its own state/metrics and participates in the agency flow. |
| signal scanner | **working** | `scripts/phase1-signal-scanner.py`, `utils/api_connectivity.py`, `tests/paper-mode-schema-test.py`, `tests/destructive/trading-agency-hyperliquid-test.py`, `tests/destructive/trading-agency-polymarket-test.py`, `tests/destructive/trading-agency-mixed-test.py` | Scanner emits canonical Hyperliquid and Polymarket paper signals, writes `phase1-signals.jsonl`, and is exercised through the agency path offline. |
| execution safety | **working** | `scripts/execution-safety-layer.py`, `scripts/trading-agency-phase1.py`, `tests/destructive/trading-agency-negative-path-test.py`, `tests/destructive/trading-agency-polymarket-test.py` | Safety layer is in the canonical loop, refreshes breakers from canonical history, blocks stale/duplicate/capacity/breaker cases, and persists safety state. |
| paper trader | **working** | `scripts/phase1-paper-trader.py`, `tests/destructive/full-lifecycle-integration-test.py`, `tests/destructive/real-exit-integration-test.py`, `tests/destructive/polymarket-paper-flow-test.py` | Canonical planner/persistence layer for both exchanges. Proven for isolated lifecycle entry/exit/persistence. |
| trade schema | **working** | `models/trade_schema.py`, `tests/trade-schema-contract-test.py`, `tests/paper-mode-schema-test.py` | Current schema normalization and validation support both Hyperliquid and Polymarket records, including `market_id` enforcement for Polymarket. |
| position state | **working** | `models/position_state.py`, `tests/trade-schema-contract-test.py`, `tests/destructive/trading-agency-hyperliquid-test.py`, `tests/destructive/trading-agency-polymarket-test.py` | `position-state.json` is the authoritative open-position file and both exchanges persist through it. |
| timeout monitor | **working** | `scripts/timeout-monitor.py`, `scripts/trading-agency-phase1.py`, `tests/timeout-monitor-polymarket-threshold-test.py`, `tests/destructive/trading-agency-hyperliquid-test.py`, `tests/destructive/trading-agency-polymarket-test.py` | Monitor reads only canonical open state, supports Polymarket thresholds, and is executed by the orchestrator. It is monitoring-only, not authoritative close persistence. |
| exit monitor | **non-canonical** | `scripts/exit-monitor.py`, `scripts/trading-agency-phase1.py` | Explicitly skipped by the canonical loop because it can write proof artifacts without authoritative close persistence. |
| performance dashboard | **working** | `scripts/performance-dashboard.py`, `tests/performance-dashboard-canonical-test.py`, `tests/trade-schema-contract-test.py` | Reads canonical closed-trade history and authoritative open-position state. |
| Hyperliquid path | **working** | `scripts/phase1-signal-scanner.py`, `scripts/execution-safety-layer.py`, `scripts/phase1-paper-trader.py`, `scripts/trading-agency-phase1.py`, `tests/destructive/trading-agency-hyperliquid-test.py`, `tests/destructive/trading-agency-hyperliquid-repeat-cycle-test.py` | Strongest path in the repo. Proven offline through the actual orchestrator, including repeat-cycle stability. |
| Polymarket path | **partial** | `scripts/phase1-signal-scanner.py`, `scripts/execution-safety-layer.py`, `scripts/phase1-paper-trader.py`, `scripts/trading-agency-phase1.py`, `tests/destructive/trading-agency-polymarket-test.py`, `tests/destructive/polymarket-paper-flow-test.py`, `scripts/polymarket-executor.py` | Canonical paper path exists and is offline-proven through the orchestrator, but the repo still keeps a separate non-canonical Polymarket helper/state model and no live execution exists. |
| mixed mode | **partial** | `config/runtime.py`, `scripts/phase1-signal-scanner.py`, `scripts/phase1-paper-trader.py`, `tests/destructive/trading-agency-mixed-test.py`, `tests/destructive/mixed-mode-integration-test.py` | Real mode. Scanner sees both exchanges. Shared persistence is real. Limitation: planner selects at most one new entry per cycle. Mixed is not simultaneous dual-entry execution. |
| CI workflow | **working** | `.github/workflows/basic.yml`, `scripts/ci-safe-verification.sh` | CI runs on push/PR and executes compile checks, regression tests, and destructive offline agency tests. |
| destructive/integration tests | **working, but offline-only** | `tests/destructive/*.py`, `tests/support/trading_agency_offline.py`, `tests/support/offline_requests_sitecustomize.py` | Test suite now proves the agency entrypoint offline. It does not prove live API reliability or live order placement. |
| docs truthfulness | **partial** | `README.md`, `SYSTEM_STATUS.md`, `PROOF_MATRIX.md`, `docs/SYSTEM_ARCHITECTURE.md`, `docs/OPERATOR_QUICKSTART.md`, `docs/DATA_INTEGRITY_LAYER.md`, old root report files replaced by this audit | README/SYSTEM_STATUS/PROOF_MATRIX are mostly aligned. `docs/SYSTEM_ARCHITECTURE.md` and `docs/DATA_INTEGRITY_LAYER.md` contain stale statements, and the previous root audit files were outdated. |

---

## C. Canonical Flow Map

### Actual canonical entrypoint

1. **Operator entrypoint:** `scripts/trading-agency-phase1.py`.
   - This is the only script that sequences the full runtime.
   - `scripts/bootstrap-runtime-check.py` is stage 1 inside that flow, not the top-level operator entrypoint.

### Real canonical execution sequence

1. `scripts/trading-agency-phase1.py`
   - resolves mode from `config/runtime.py`
   - initializes health/operator-control plumbing through `utils/system_health.py`
   - reports non-canonical helper files separately
   - writes/refreshes support state such as:
     - `workspace/operator_control.json`
     - `workspace/system_status.json`
     - `workspace/system_health.json`
     - `workspace/logs/operator-control-audit.json`

2. `scripts/bootstrap-runtime-check.py`
   - verifies required runtime imports
   - blocks the cycle on missing dependencies
   - writes no canonical trade state

3. `scripts/data-integrity-layer.py` via `run_pre_scan_gate()`
   - checks only the exchanges enabled by the selected mode
   - writes:
     - `workspace/logs/data-integrity-state.json`
     - `workspace/logs/source-reliability-metrics.json`
     - `workspace/logs/runtime-events.jsonl`
     - `workspace/logs/system-incidents.jsonl` when incidents change

4. `scripts/phase1-signal-scanner.py`
   - scans Hyperliquid and/or Polymarket depending on mode
   - appends canonical signals to:
     - `workspace/logs/phase1-signals.jsonl`
   - writes support artifacts:
     - `workspace/PHASE1_SIGNAL_REPORT.md`
     - `workspace/logs/runtime-events.jsonl`

5. `scripts/execution-safety-layer.py` via orchestrator calls
   - loads open positions and latest signals through trader helpers
   - selects a candidate entry
   - validates kill switch, freshness, dedupe, position size, circuit breakers, exchange health, liquidity, spread, and data integrity
   - writes:
     - `workspace/logs/execution-safety-state.json`
     - `workspace/logs/blocked-actions.jsonl` when blocking
     - incident logs and runtime events indirectly through health/state handling

6. `scripts/phase1-paper-trader.py`
   - evaluates exits for authoritative open positions first
   - selects at most one new entry for the cycle
   - persists canonical trade records only after orchestrator approval
   - authoritative outputs:
     - `workspace/logs/phase1-paper-trades.jsonl`
     - `workspace/logs/position-state.json`
     - `workspace/logs/phase1-performance.json`
   - support output:
     - `workspace/logs/runtime-events.jsonl`

7. `scripts/timeout-monitor.py`
   - reads only `workspace/logs/position-state.json`
   - writes monitoring-only outputs:
     - `workspace/logs/timeout-history.jsonl`
     - `workspace/TIMEOUT_MONITOR_REPORT.md`
     - `workspace/logs/runtime-events.jsonl`

8. `scripts/trading-agency-phase1.py` finalization
   - writes:
     - `workspace/logs/agency-phase1-report.json`
     - `workspace/logs/agency-cycle-summary.json`
     - `workspace/AGENCY_CYCLE_SUMMARY.md`
     - refreshed `workspace/system_status.json`

### Authoritative state hierarchy

**Tier 1: authoritative trading state**
- `workspace/logs/phase1-paper-trades.jsonl`
- `workspace/logs/position-state.json`
- `workspace/logs/phase1-performance.json`

**Tier 2: control/health state**
- `workspace/operator_control.json`
- `workspace/system_status.json`
- `workspace/system_health.json`
- `workspace/logs/execution-safety-state.json`
- `workspace/logs/data-integrity-state.json`

**Tier 3: observability/support artifacts**
- `workspace/logs/runtime-events.jsonl`
- `workspace/logs/system-incidents.jsonl`
- `workspace/logs/blocked-actions.jsonl`
- `workspace/logs/timeout-history.jsonl`
- `workspace/logs/agency-phase1-report.json`
- `workspace/logs/agency-cycle-summary.json`
- `workspace/AGENCY_CYCLE_SUMMARY.md`
- `workspace/PHASE1_SIGNAL_REPORT.md`
- `workspace/TIMEOUT_MONITOR_REPORT.md`

### Non-canonical / helper / historical paths

These are not part of the canonical trading loop:
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

---

## D. Gap Analysis

These are the gaps that block a truthful claim that **both Hyperliquid and Polymarket are fully integrated**.

1. **Polymarket still has a second, non-canonical implementation surface.**
   - `scripts/polymarket-executor.py` writes `workspace/logs/polymarket-trades.jsonl` and `workspace/logs/polymarket-state.json`.
   - That is separate from the canonical `phase1-paper-trades.jsonl` + `position-state.json` model.
   - Result: Polymarket is not cleanly single-path inside the repo.

2. **There is no live Polymarket execution path at all.**
   - `scripts/polymarket-executor.py` explicitly says real execution is incomplete/disabled.
   - The canonical flow only paper-trades.
   - Result: any “fully integrated” statement must be scoped to paper trading only.

3. **Polymarket exit pricing is still based on read-only market lookups, not execution-grade order handling.**
   - Scanner, safety, and trader all query the Gamma markets endpoint.
   - There is no authenticated order path, signed order handling, fill handling, or settlement handling.
   - Result: good enough for paper simulation, not full exchange integration.

4. **Mixed mode is not true side-by-side dual-entry execution.**
   - `scripts/phase1-paper-trader.py` selects one candidate entry per cycle.
   - `tests/destructive/trading-agency-mixed-test.py` proves the limitation explicitly.
   - Result: “mixed” is a shared-state evaluation mode, not a full dual-exchange engine.

5. **External runtime connectivity is not proven in this environment.**
   - `python3 scripts/runtime-connectivity-check.py` failed for Hyperliquid here.
   - `OPENCLAW_TRADING_MODE=polymarket_only python3 scripts/runtime-connectivity-check.py` failed for Polymarket here.
   - Failures were proxy/tunnel `403 Forbidden` errors from the audit environment, not code exceptions.
   - Result: there is no fresh live market-data proof from this audit run.

6. **Support/documentation surfaces still create ambiguity about truth.**
   - `docs/SYSTEM_ARCHITECTURE.md` still says the full orchestrator path is not exercised end-to-end in CI.
   - `docs/DATA_INTEGRITY_LAYER.md` still documents Hyperliquid as a universal primary source whose failure halts all signal generation.
   - Result: repo truth is not uniformly represented.

7. **The checked-in workspace is not evidence of real runtime activity.**
   - The repo ships only `workspace/README.md`, `workspace/operator_control.json`, and `workspace/system_status.json`.
   - No canonical trade log or open-position state is committed.
   - Result: truth comes from code/tests, not bundled runtime artifacts.

---

## E. Claims in docs/README that are not fully supported by code/tests

### Confirmed truthful or conservative

- `README.md`: paper-trading only, Hyperliquid canonical, Polymarket experimental, mixed limited.
- `SYSTEM_STATUS.md`: paper-only, no live trading, Polymarket experimental, mixed limited.
- `PROOF_MATRIX.md`: current CI/offline proof surface is described substantially correctly.

### Stale or incorrect

1. **`docs/SYSTEM_ARCHITECTURE.md` says the full orchestrator path is not exercised end-to-end in CI.**
   - That is now false.
   - CI runs `tests/destructive/trading-agency-hyperliquid-test.py`, `trading-agency-polymarket-test.py`, `trading-agency-mixed-test.py`, and `trading-agency-negative-path-test.py` from `scripts/ci-safe-verification.sh`.

2. **`docs/DATA_INTEGRITY_LAYER.md` still describes Hyperliquid as a universal primary source whose failure halts all signal generation.**
   - That is no longer the runtime behavior.
   - `polymarket_only` mode can pass without Hyperliquid, and there is a dedicated test proving that.

3. **Previously generated root audit files were stale.**
   - The old `CODEX_AUDIT_REPORT.md`, `INTEGRATION_GAP_MATRIX.md`, `EXECUTION_TRUTH_MAP.md`, and `REMEDIATION_PLAN.md` claimed the orchestrator was not exercised in CI and understated the current paper-path proof surface.
   - Those files are replaced by this audit set.

### Important nuance: conservative statements are not bugs

The following wording is conservative, not false:
- “Polymarket is experimental and not fully proven end-to-end.”
- That remains a fair statement because the repo proves only an offline paper-runtime path, not full execution-grade integration.

---

## F. Final verdict

You can truthfully say:

**“Hyperliquid is integrated; Polymarket is experimental and not yet fully integrated.”**

That sentence is accurate **only if you mean the current paper-trading repository**:
- Hyperliquid is integrated in the canonical paper-runtime and is the strongest/proven path.
- Polymarket is wired into the canonical paper-runtime and is offline-proven, but it is still experimental, still has non-canonical helper leftovers, and is not execution-grade or live-ready.
