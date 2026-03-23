# CODEX_AUDIT_REPORT

Date: 2026-03-23 UTC
Repo: `yumorepos/autonomous-trading-system`
Scope: production-readiness and truthfulness audit of the repository as checked out, with code/tests/CI/runtime verification and no reliance on README claims alone.

## A. Executive verdict

- **Hyperliquid properly integrated?** **Yes, for the repository's canonical paper-trading path only.**
  - It is wired through the canonical orchestrator, scanner, safety layer, paper trader, canonical persistence, timeout monitor, agency report, and offline CI-backed lifecycle tests.
  - It is **not** live-ready and has **no real order placement path**.
- **Polymarket properly integrated?** **Partial.**
  - It is wired through the same canonical paper-trading path and is not just helper/scaffold code.
  - It is still **experimental overall**, lacks any authenticated/live execution path, is proven only with offline fixtures plus isolated paper-flow tests, and is not symmetrical with Hyperliquid in mixed mode.
- **Repo truthfully represented?** **Partial.**
  - Active top-level docs are mostly disciplined and much more truthful than the historical material.
  - The repository still contains archived/historical documents and scripts with materially different older claims/results that can mislead casual readers or grep-based review.
- **System paper-trading only?** **Yes.**
- **Any live-ready claim that should be removed?** **Yes.**
  - Not from the active README/system status surface; those are already paper-only.
  - From retained historical/archive material that still contains old production/live-readiness language or results that are no longer authoritative.

## Bottom line

The repo is a **paper-trading research system**, not a production trading system. Hyperliquid is the best-supported canonical paper path. Polymarket is now actually present in the canonical paper path, but only as an **experimental paper-trading integration**. Saying Polymarket is merely helper code is false. Saying Polymarket is fully integrated without qualification is also false.

## B. Evidence table

| Component | Status | Evidence file paths | Exact reason |
|---|---|---|---|
| bootstrap/runtime check | working | `scripts/bootstrap-runtime-check.py`, `tests/bootstrap-runtime-check-test.py`, `scripts/ci-safe-verification.sh` | Canonical stage exists, blocks on missing required deps, and is exercised directly in CI. |
| orchestrator | working | `scripts/trading-agency-phase1.py`, `tests/destructive/trading-agency-hyperliquid-test.py`, `tests/destructive/trading-agency-polymarket-test.py`, `tests/destructive/trading-agency-mixed-test.py`, `tests/support/trading_agency_offline.py` | Canonical entrypoint is the agency script. It calls bootstrap -> data integrity -> scanner -> safety -> trader -> state update -> monitors -> report. Offline tests execute the full agency path in all declared modes. |
| data integrity layer | working with mode asymmetry | `scripts/data-integrity-layer.py`, `tests/data-integrity-mode-gate-test.py`, `tests/destructive/trading-agency-negative-path-test.py` | Mode-aware gating is real. In `mixed`, Hyperliquid is effectively primary: Hyperliquid failure is critical, Polymarket failure is warning-only. That is a design choice, not a symmetric dual-exchange gate. |
| signal scanner | working | `scripts/phase1-signal-scanner.py`, `tests/paper-mode-schema-test.py` | Scanner emits real normalized paper signals for both exchanges into the canonical signal log. |
| execution safety | partial | `scripts/execution-safety-layer.py`, `scripts/trading-agency-phase1.py`, `tests/destructive/trading-agency-negative-path-test.py` | Safety gates, breaker refresh, and blocked-action logging are real. But checks are paper-only, use public market-data lookups, and some safety checks are advisory rather than blocking. |
| paper trader | working | `scripts/phase1-paper-trader.py`, `utils/paper_exchange_adapters.py`, `tests/destructive/full-lifecycle-integration-test.py`, `tests/destructive/polymarket-paper-flow-test.py` | Canonical paper entry/exit planning and persistence work for both exchanges in isolated workspaces. |
| trade schema | working | `models/trade_schema.py`, `tests/trade-schema-contract-test.py` | A normalized flat schema exists and is actively used by readers and persistence consumers. |
| position state | working | `models/position_state.py`, `tests/trade-schema-contract-test.py`, `tests/destructive/trading-agency-hyperliquid-repeat-cycle-test.py` | `position-state.json` is the authoritative open-position file. Open/close application removes closed positions correctly. |
| timeout monitor | working | `scripts/timeout-monitor.py`, `tests/timeout-monitor-polymarket-threshold-test.py`, `scripts/trading-agency-phase1.py` | Canonical orchestrator runs timeout monitor and not exit monitor. Monitor reads canonical state and writes monitoring artifacts only. |
| exit monitor | non-canonical | `scripts/exit-monitor.py`, `scripts/trading-agency-phase1.py`, `tests/destructive/trading-agency-polymarket-test.py` | Orchestrator intentionally skips it because it writes proof artifacts but does not authoritatively persist closes. |
| performance dashboard | working | `scripts/performance-dashboard.py`, `tests/performance-dashboard-canonical-test.py`, `tests/trade-schema-contract-test.py` | Reads canonical trade history plus canonical open-position state and handles both exchanges. |
| Hyperliquid path | working (paper only) | `scripts/phase1-signal-scanner.py`, `utils/paper_exchange_adapters.py`, `tests/destructive/trading-agency-hyperliquid-test.py`, `tests/destructive/trading-agency-hyperliquid-repeat-cycle-test.py`, `tests/destructive/full-lifecycle-integration-test.py` | Hyperliquid is the default canonical paper path and has the strongest end-to-end offline proof. No live execution path exists. |
| Polymarket path | partial | `scripts/phase1-signal-scanner.py`, `utils/paper_exchange_adapters.py`, `tests/destructive/trading-agency-polymarket-test.py`, `tests/destructive/polymarket-paper-flow-test.py`, `tests/polymarket-metadata-truth-test.py` | Polymarket is in the canonical paper path and persists through the same state model. But it remains experimental, public-data-only, and unproven for live connectivity or authenticated execution. |
| mixed mode | partial | `config/runtime.py`, `models/exchange_metadata.py`, `scripts/data-integrity-layer.py`, `scripts/phase1-paper-trader.py`, `tests/destructive/trading-agency-mixed-test.py`, `tests/destructive/mixed-mode-integration-test.py` | Mixed mode exists, but the canonical orchestrator allows only one new entry per cycle and prioritizes Hyperliquid. Trader-level state can hold both exchanges, but agency-level mixed mode is intentionally limited. |
| CI workflow | working but offline-biased | `.github/workflows/basic.yml`, `scripts/ci-safe-verification.sh`, `tests/support/offline_requests_sitecustomize.py` | CI runs deterministic offline coverage and compile checks. It does not prove live API reachability or real external integration. |
| destructive/integration tests | partial / misleadingly named | `tests/destructive/*.py`, `tests/support/offline_requests_sitecustomize.py` | The tests do prove important canonical behavior, but they are isolated temp-workspace tests with patched network fixtures. They are not destructive against real state and are not live integration tests. |
| docs truthfulness | partial / mostly good on active surface | `README.md`, `SYSTEM_STATUS.md`, `docs/SYSTEM_ARCHITECTURE.md`, `PROOF_MATRIX.md`, `docs/archive/`, `scripts/archive/` | Active docs are mostly aligned with the current paper-only code. Repository-wide truthfulness is diluted by historical archived content with older contradictory conclusions/claims. |

## C. Real canonical flow map

1. `config/runtime.py`
   - Computes `WORKSPACE_ROOT`, `LOGS_DIR`, `DATA_DIR`, and resolves `OPENCLAW_TRADING_MODE`.
   - Creates workspace directories on import.

2. `scripts/trading-agency-phase1.py`
   - This is the **canonical operator entrypoint**.
   - Prints mode truth banner and loads system-health state.

3. `scripts/bootstrap-runtime-check.py`
   - Invoked as a subprocess by the orchestrator.
   - Verifies only Python dependency presence, not exchange credentials or authenticated connectivity.
   - Writes no canonical trading state.

4. `scripts/data-integrity-layer.py`
   - Loaded directly by the orchestrator.
   - Runs `run_pre_scan_gate(...)` for the active mode.
   - Writes:
     - `workspace/logs/data-integrity-state.json`
     - `workspace/logs/source-reliability-metrics.json`
     - incident/operator state via `utils/system_health.py`
   - If gate fails, canonical scan/trade path is blocked.

5. `scripts/phase1-signal-scanner.py`
   - Invoked as a subprocess by the orchestrator if the data gate passes.
   - Pulls public market data via `utils/api_connectivity.py`.
   - Writes:
     - `workspace/logs/phase1-signals.jsonl`
     - `workspace/PHASE1_SIGNAL_REPORT.md`
     - `workspace/logs/runtime-events.jsonl`

6. `scripts/execution-safety-layer.py` via orchestrator `run_safety_validation()`
   - Loads latest open positions from `models/position_state.py` and latest signals from `phase1-paper-trader.py` helpers.
   - Selects the next candidate signal.
   - Persists safety/runtime state before and after validation.
   - Writes:
     - `workspace/logs/execution-safety-state.json`
     - possibly `workspace/logs/blocked-actions.jsonl`
     - possibly `workspace/logs/incident-log.jsonl`
     - health/operator state via `utils/system_health.py`

7. `scripts/phase1-paper-trader.py` via orchestrator `run_trader()`
   - Builds the execution plan from canonical signals and canonical open positions.
   - Evaluates exit candidates first, then maybe one new entry.
   - In mixed mode, ranking uses exchange priority first, so Hyperliquid wins the canonical single-entry selection.
   - Planning does not yet persist trades.

8. `scripts/phase1-paper-trader.py` via orchestrator `run_state_update()`
   - Persists planned trade records.
   - Writes authoritative state:
     - `workspace/logs/phase1-paper-trades.jsonl`
     - `workspace/logs/position-state.json`
     - `workspace/logs/phase1-performance.json`
     - `workspace/logs/runtime-events.jsonl`
   - Position state updates flow through `models/position_state.py`.

9. `scripts/timeout-monitor.py`
   - The only monitor script actually executed in the canonical loop.
   - Reads authoritative open positions from `position-state.json`.
   - Writes:
     - `workspace/logs/timeout-history.jsonl`
     - `workspace/TIMEOUT_MONITOR_REPORT.md`
     - `workspace/logs/runtime-events.jsonl`

10. `scripts/trading-agency-phase1.py` report generation
    - Writes operator-facing artifacts:
      - `workspace/logs/agency-cycle-summary.json`
      - `workspace/AGENCY_CYCLE_SUMMARY.md`
      - `workspace/logs/agency-phase1-report.json`
      - `workspace/system_health.json`
      - `workspace/system_status.json`
      - `workspace/operator_control.json` (created if absent)
      - supporting incident/operator logs under `workspace/logs/`

## D. Authoritative vs non-canonical files

### Authoritative / canonical runtime path

- `scripts/trading-agency-phase1.py`
- `scripts/bootstrap-runtime-check.py`
- `scripts/data-integrity-layer.py`
- `scripts/phase1-signal-scanner.py`
- `scripts/execution-safety-layer.py`
- `scripts/phase1-paper-trader.py`
- `scripts/timeout-monitor.py`
- `models/trade_schema.py`
- `models/position_state.py`
- `utils/paper_exchange_adapters.py`
- `utils/api_connectivity.py`
- `workspace/logs/phase1-signals.jsonl`
- `workspace/logs/phase1-paper-trades.jsonl`
- `workspace/logs/position-state.json`
- `workspace/logs/phase1-performance.json`

### Non-canonical / support / future-scope / historical

- `scripts/exit-monitor.py` — intentionally skipped by orchestrator
- `scripts/live-readiness-validator.py` — future-scope research model only
- `scripts/stability-monitor.py`, `scripts/exit-safeguards.py`, `scripts/position-exit-tracker.py`, `scripts/enhanced-exit-capture.py`, `scripts/supervisor-governance.py`, `scripts/portfolio-allocator.py`, `scripts/alpha-intelligence-layer.py` — support-only, not on canonical execution path
- `scripts/archive/*` — historical
- `docs/archive/*` — historical and contains stale contradictory conclusions from prior repo states
- `tests/support/offline_requests_sitecustomize.py` — test-only network patching, not runtime logic

## E. State-model agreement audit

### What agrees

- Scanner emits signals with enough normalized fields for both exchanges.
- Paper trader validates against exchange-specific adapters.
- Trade persistence uses one shared trade log.
- Position state uses one shared open-position file.
- Performance dashboard reads normalized closed trades from the canonical shared log.
- Timeout monitor reads canonical shared open-position state and uses exchange metadata thresholds.

### Where the agreement is imperfect or drift-prone

1. **Canonical schema vs compatibility fields**
   - `models/trade_schema.py` defines a normalized flat schema.
   - `models/position_state.py` stores canonical open-position fields **plus** compatibility aliases (`position_id`, `direction`, `entry_time`) and may also carry `signal`, thresholds, `raw`, `market_*`, etc.
   - This is workable, but it is a drift surface rather than a tightly versioned schema contract.

2. **Safety layer reads raw recent trades, not normalized trades**
   - `ExecutionSafetyLayer.load_recent_trades()` reads JSONL records directly and assumes fields like `entry_time` and nested `signal` exist.
   - Other readers use `normalize_trade_record(...)` first.
   - This inconsistency increases schema-drift risk.

3. **Mixed-mode semantics differ by layer**
   - Scanner can emit both exchanges in one cycle.
   - Trader state model can hold both exchanges.
   - Agency/orchestrator path admits only one new entry per cycle and always prefers Hyperliquid by exchange priority.
   - Data integrity in mixed treats Hyperliquid as critical/primary and Polymarket as optional/warning-only.
   - Therefore "mixed mode" does not mean the same thing across all layers.

## F. Gap analysis: what blocks a truthful claim that both Hyperliquid and Polymarket are fully integrated

1. **No live execution path exists for either exchange**
   - There is no authenticated order placement, wallet management, signing, or settlement path.
   - Hyperliquid uses public `info` endpoints only.
   - Polymarket uses public Gamma market-data endpoints only.

2. **No live integration test exists**
   - CI and destructive tests use offline fixtures and request patching.
   - This proves canonical control flow, not live exchange integration.

3. **Polymarket is experimental by repo design, not by wording accident**
   - Exchange metadata explicitly marks it experimental.
   - Active docs repeatedly call it experimental overall.

4. **Mixed mode is not fully integrated as a true dual-exchange runtime**
   - Orchestrator admits only one entry per cycle.
   - Mixed mode is asymmetric and Hyperliquid-preferred.
   - Polymarket availability in mixed is not sufficient to keep the canonical path alive if Hyperliquid is down.

5. **Tests named "integration" or "destructive" are mostly isolated offline harness tests**
   - Useful, but not proof of real exchange runtime behavior.

6. **Archived repo content still contains materially different historical claims/results**
   - That prevents a clean repo-wide truth surface unless historical files are clearly quarantined or indexed as obsolete.

7. **No end-to-end proof of real network reachability is merge-blocking**
   - `runtime-connectivity-check.py` is optional and non-blocking.
   - In this audit environment, all live connectivity attempts failed at the proxy layer; the canonical runtime hard-failed the data gate accordingly.

## G. Docs/README claims not fully supported by code/tests

### Supported by code/tests

- Canonical entrypoint is `scripts/trading-agency-phase1.py`.
- System is paper-trading only.
- Hyperliquid is the default/best-supported paper path.
- Polymarket is present in the canonical paper path and experimental overall.
- Mixed mode is limited.
- CI proves offline behavior, not live reachability.

### Not fully supported or should be tightened

1. **Repository-wide truthfulness is overstated if archive material is considered part of the review surface**
   - Active docs are mostly accurate.
   - Repo-wide grep surface is not clean because archived historical files still contain contradictory prior verdicts and older live/prod language.

2. **"End-to-end" requires qualification**
   - Hyperliquid and Polymarket are end-to-end only in the repo's **paper-trading/offline-tested control plane**, not in a live exchange execution sense.

3. **Mixed mode description should be even more explicit**
   - Current docs say limited/deterministic, which is directionally correct.
   - They do not consistently spell out that data integrity treats Hyperliquid as primary and that agency mixed mode is not symmetrical.

## H. Dead code, stale docs, misleading naming, and simulation-only surfaces

### Dead / non-canonical / misleading

- `scripts/exit-monitor.py` is intentionally non-canonical and skipped.
- `scripts/live-readiness-validator.py` is future-scope modeling only.
- `tests/destructive/*` are not destructive against real runtime state.
- `tests/*integration*` are mostly isolated workspace tests, not live integration tests.
- `scripts/archive/*` and `docs/archive/*` contain prior repo states and contradictory conclusions.

### Duplication / maintenance risk

- Price lookup and exchange-specific logic exist in adapters, timeout monitor, and non-canonical exit monitor.
- State-model handling mixes normalized and raw record assumptions.
- Archive plus active surfaces multiply audit load and increase truthfulness risk.

## I. Real runtime verification performed during this audit

### Verified working locally/offline

- Full safe verification suite completed successfully.
- Canonical offline agency proofs passed for Hyperliquid, Polymarket, mixed limitation handling, negative paths, repeat-cycle Hyperliquid, and isolated lifecycle tests.

### Verified failing in this environment with live network enabled

- `runtime-connectivity-check.py` failed for Hyperliquid and Polymarket because outbound access hit proxy `403 Forbidden` tunnel failures.
- Running the canonical agency entrypoint without offline patching caused the data-integrity gate to fail and block the rest of the canonical trade path.
- This is evidence that the runtime correctly halts on missing external data, **not** evidence that exchange APIs themselves are down globally.

## J. Final judgment

- Hyperliquid is genuinely integrated through the repo's canonical paper-trading flow.
- Polymarket is also genuinely wired into that same canonical paper-trading flow; it is **not** just helper/scaffold/research code.
- Polymarket is still correctly described as experimental overall because the repo has no authenticated/live execution path, no live integration proof, and limited mixed-mode semantics.
- The strongest truthful one-line description is:

> Hyperliquid is integrated for the canonical paper-trading path; Polymarket is also integrated for that paper-trading path but remains experimental overall and is not live-ready.

That is more accurate than saying Polymarket is simply "not yet fully integrated," because within the repo's actual canonical paper architecture it is already wired end-to-end for paper trading.
