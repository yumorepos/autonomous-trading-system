# CODEX Audit Report

Date: 2026-03-22
Repo: `autonomous-trading-system`
Audit scope: current checked-in code, docs, CI workflow, and executable tests.
Method: code-first audit, then test execution, then truth-surface comparison.

---

## A. Executive verdict

| Question | Verdict | Basis |
|---|---|---|
| Is Hyperliquid properly integrated? | **Yes, for the canonical paper-trading path** | The canonical runtime wires Hyperliquid through bootstrap -> data integrity -> scanner -> safety -> trader -> canonical persistence -> timeout monitor, and the agency-level offline tests prove entry, exit, state update, reports, and monitor execution in that path. |
| Is Polymarket properly integrated? | **Partial** | Polymarket is wired into the same canonical paper-trading path and is proven offline in `polymarket_only`, but it is still only a paper path, uses read-only market data rather than authenticated order placement/fill handling, and mixed mode does not prove true dual-exchange runtime semantics. |
| Is the repo truthfully represented? | **Partial** | Top-level docs are mostly honest about paper-only scope, but there are still active contradictions: some docs understate current CI proof, and active root audit/plan files contain stale claims about files that no longer exist. |
| Is the system paper-trading only? | **Yes** | No live execution path exists in the canonical runtime; all execution records are paper records written into workspace JSON/JSONL artifacts. |
| Is there any live-ready claim that should be removed? | **Yes** | Any remaining live-readiness or “fully integrated” phrasing for both exchanges should be removed unless explicitly scoped to paper trading. |

### Bottom line

1. **Hyperliquid is the strongest and most coherent canonical path.**
2. **Polymarket is in the canonical paper-trading flow, but not execution-grade and not fully integrated in the sense a production reviewer would expect.**
3. **The repository is not live-ready and should not be presented that way.**
4. **The truthful headline is:** Hyperliquid integrated; Polymarket experimental/partial; mixed mode limited; paper trading only.

---

## B. Evidence table

| Component | Status | Evidence file paths | Exact reason |
|---|---|---|---|
| bootstrap/runtime check | **working** | `scripts/bootstrap-runtime-check.py`, `tests/bootstrap-runtime-check-test.py`, `.github/workflows/basic.yml` | Canonical bootstrap exists, checks required deps, runs in CI, and has an explicit regression test. |
| orchestrator | **working** | `scripts/trading-agency-phase1.py`, `tests/destructive/trading-agency-hyperliquid-test.py`, `tests/destructive/trading-agency-polymarket-test.py`, `tests/destructive/trading-agency-negative-path-test.py` | Real entrypoint is the agency script. It runs all canonical stages and is exercised offline for positive and negative paths. |
| data integrity layer | **working** | `scripts/data-integrity-layer.py`, `tests/data-integrity-mode-gate-test.py` | Mode-aware gate exists and correctly scopes required sources by runtime mode. |
| signal scanner | **working** | `scripts/phase1-signal-scanner.py`, `tests/paper-mode-schema-test.py` | Scanner emits normalized Hyperliquid and Polymarket paper signals into the canonical signal history. |
| execution safety | **working** | `scripts/execution-safety-layer.py`, `tests/destructive/trading-agency-negative-path-test.py` | Critical gates block stale signals, duplicates, breaker halts, and capacity overflow before persistence. |
| paper trader | **working** | `scripts/phase1-paper-trader.py`, `tests/destructive/full-lifecycle-integration-test.py`, `tests/destructive/polymarket-paper-flow-test.py` | Trader builds/persists canonical open/closed records and updates canonical position state for both exchanges. |
| trade schema | **working** | `models/trade_schema.py`, `tests/trade-schema-contract-test.py` | One normalized schema supports Hyperliquid and Polymarket records and downstream readers. |
| position state | **working** | `models/position_state.py`, `tests/trade-schema-contract-test.py`, `tests/destructive/full-lifecycle-integration-test.py` | One authoritative open-position state file is used and cleared on close. |
| timeout monitor | **working** | `scripts/timeout-monitor.py`, `tests/timeout-monitor-polymarket-threshold-test.py`, agency destructive tests | Timeout monitor reads canonical state and is the only monitor actually executed by the orchestrator. |
| exit monitor | **non-canonical** | `scripts/exit-monitor.py`, `scripts/trading-agency-phase1.py`, `tests/destructive/trading-agency-polymarket-test.py` | Script can inspect positions and write proof artifacts, but it does not authoritatively close trades and is intentionally skipped in the canonical loop. |
| performance dashboard | **working** | `scripts/performance-dashboard.py`, `tests/performance-dashboard-canonical-test.py` | Dashboard reads canonical history/state and handles mixed-mode history correctly. |
| Hyperliquid path | **working** | `scripts/phase1-signal-scanner.py`, `scripts/phase1-paper-trader.py`, `scripts/trading-agency-phase1.py`, `tests/destructive/trading-agency-hyperliquid-test.py`, `tests/destructive/trading-agency-hyperliquid-repeat-cycle-test.py` | Hyperliquid is fully wired through the canonical paper path and proven at agency level offline. |
| Polymarket path | **partial** | `scripts/phase1-signal-scanner.py`, `scripts/execution-safety-layer.py`, `scripts/phase1-paper-trader.py`, `scripts/trading-agency-phase1.py`, `tests/destructive/trading-agency-polymarket-test.py`, `tests/destructive/polymarket-paper-flow-test.py` | Canonical paper path exists and is offline-proven, but no authenticated trading, order lifecycle, fill capture, settlement, or live execution path exists. |
| mixed mode | **partial** | `config/runtime.py`, `scripts/phase1-paper-trader.py`, `tests/destructive/trading-agency-mixed-test.py`, `tests/destructive/mixed-mode-integration-test.py` | Mixed mode scans both exchanges but admits only one new entry per cycle with deterministic Hyperliquid priority. It is not a true side-by-side runtime. |
| CI workflow | **working but scoped** | `.github/workflows/basic.yml`, `scripts/ci-safe-verification.sh` | CI proves the paper runtime offline and intentionally avoids live network reachability as a blocker. |
| destructive/integration tests | **working but offline-only** | `tests/destructive/*.py`, `tests/support/offline_requests_sitecustomize.py` | Tests prove orchestrator behavior using deterministic offline fixtures, not real exchange integration. |
| docs truthfulness | **partial** | `README.md`, `SYSTEM_STATUS.md`, `docs/SYSTEM_ARCHITECTURE.md`, `docs/OPERATOR_QUICKSTART.md`, `PROOF_MATRIX.md`, existing root audit files | Core docs are mostly truthful, but `docs/SYSTEM_ARCHITECTURE.md` understates current CI proof and several root audit/plan files are stale and reference removed artifacts. |

---

## C. Canonical flow map

The real current canonical flow is:

1. **Operator entrypoint**
   - File: `scripts/trading-agency-phase1.py`
   - Role: top-level canonical runtime.
   - Immediate outputs later in cycle: `workspace/logs/agency-phase1-report.json`, `workspace/logs/agency-cycle-summary.json`, `workspace/AGENCY_CYCLE_SUMMARY.md`.

2. **Bootstrap stage**
   - File invoked: `scripts/bootstrap-runtime-check.py`
   - Purpose: verify required local dependencies before loading networked/runtime-dependent stages.
   - Output: stage result only; no authoritative trading state written.

3. **Data-integrity pre-scan gate**
   - File loaded: `scripts/data-integrity-layer.py`
   - Purpose: mode-aware source availability/freshness/completeness checks.
   - Outputs: `workspace/logs/data-integrity-state.json`, `workspace/logs/source-reliability-metrics.json`, runtime events, incident updates.

4. **Signal scan**
   - File invoked: `scripts/phase1-signal-scanner.py`
   - Purpose: fetch Hyperliquid and/or Polymarket market data based on mode and emit normalized paper signals.
   - Canonical output: `workspace/logs/phase1-signals.jsonl`.
   - Support output: `workspace/PHASE1_SIGNAL_REPORT.md`.

5. **Safety validation**
   - Files loaded: `scripts/execution-safety-layer.py`, `scripts/phase1-paper-trader.py`
   - Purpose: select one candidate signal, normalize/validate it, run critical safety gates.
   - Output: `workspace/logs/execution-safety-state.json`; blocked actions may be written to `workspace/logs/blocked-actions.jsonl`.

6. **Trader planning**
   - File loaded: `scripts/phase1-paper-trader.py`
   - Purpose: evaluate exits for existing positions, then optionally plan one new entry.
   - Output at this stage: in-memory execution plan only; no authoritative trade persistence yet.

7. **Authoritative state update**
   - File loaded: `scripts/phase1-paper-trader.py`
   - Purpose: persist planned close/open trade records and refresh performance.
   - Canonical outputs:
     - `workspace/logs/phase1-paper-trades.jsonl`
     - `workspace/logs/position-state.json`
     - `workspace/logs/phase1-performance.json`

8. **Monitor stage**
   - File invoked: `scripts/timeout-monitor.py`
   - Purpose: read canonical open positions and write monitoring artifacts.
   - Outputs:
     - `workspace/logs/timeout-history.jsonl`
     - `workspace/TIMEOUT_MONITOR_REPORT.md`
   - `scripts/exit-monitor.py` is explicitly not run as canonical.

9. **Cycle report packaging**
   - File: `scripts/trading-agency-phase1.py`
   - Purpose: assemble stage results, health status, runtime summary, file map, and operator-facing summaries.
   - Outputs:
     - `workspace/logs/agency-phase1-report.json`
     - `workspace/logs/agency-cycle-summary.json`
     - `workspace/AGENCY_CYCLE_SUMMARY.md`
     - `workspace/system_status.json`

### Authoritative persisted state

The authoritative current-state/trade-history surfaces are:
- `workspace/logs/phase1-signals.jsonl`
- `workspace/logs/phase1-paper-trades.jsonl`
- `workspace/logs/position-state.json`
- `workspace/logs/phase1-performance.json`

### Non-authoritative/support outputs

These should not be treated as canonical execution truth:
- `workspace/TIMEOUT_MONITOR_REPORT.md`
- `workspace/logs/timeout-history.jsonl`
- `workspace/logs/execution-safety-state.json`
- `workspace/logs/agency-phase1-report.json`
- `workspace/logs/agency-cycle-summary.json`
- `workspace/AGENCY_CYCLE_SUMMARY.md`
- all artifacts from `scripts/exit-monitor.py`

---

## D. Gap analysis: what blocks a truthful “both fully integrated” claim

These gaps block a truthful claim that **both Hyperliquid and Polymarket are fully integrated end-to-end**:

1. **No live execution exists at all.**
   - The canonical runtime never signs, routes, or confirms real orders.
   - Both exchanges are paper-only in the actual runtime.

2. **Polymarket integration is market-data-driven paper simulation, not execution integration.**
   - Scanner, safety, timeout monitor, and trader all use read-only Polymarket market data.
   - There is no authenticated order creation, no order status reconciliation, no fill handling, no settlement handling, and no wallet/auth path.

3. **Tests prove offline determinism, not real exchange interoperability.**
   - Agency tests patch network calls via `sitecustomize.py` and JSON fixtures.
   - That proves canonical flow wiring, not live API behavior.

4. **Mixed mode is intentionally limited.**
   - It scans both exchanges but only persists one new entry per cycle.
   - Priority is deterministic and favors Hyperliquid.
   - That is not a fully integrated concurrent dual-exchange runtime.

5. **Metadata does not consistently reflect the repo’s own “Polymarket is experimental” claim.**
   - `models/exchange_metadata.py` marks Polymarket `paper_status` as `canonical`.
   - `scripts/phase1-signal-scanner.py` and `utils/paper_exchange_adapters.py` emit Polymarket signals/trades with `experimental: False`.
   - `utils/runtime_logging.py` marks runtime events as experimental when exchange is Polymarket.
   - Result: docs, runtime events, and persisted trade records do not agree on Polymarket experimental status.

6. **Truth surfaces are not fully clean.**
   - `docs/SYSTEM_ARCHITECTURE.md` says the full orchestrator path is not exercised end-to-end in CI, but current CI does run offline agency entrypoint tests.
   - Existing root audit/plan files were stale before this audit and referenced removed helper files.

7. **Real runtime connectivity is not currently proven in this environment.**
   - The read-only connectivity script failed against both Hyperliquid and Polymarket here due proxy/network restrictions.
   - This does not break the offline proof, but it means no current live API reachability claim is supported by this audit run.

---

## E. Truthfulness findings by topic

### 1. True current repo state

- Canonical runtime exists and is `scripts/trading-agency-phase1.py`.
- Canonical persistence is unified through `phase1-paper-trades.jsonl` plus `position-state.json`.
- Hyperliquid and Polymarket both flow through the same paper architecture.
- Mixed mode is real but intentionally limited.
- The repo is paper-only.
- CI proves the offline paper runtime, not live exchange integration.

### 2. Hyperliquid integration verdict

**Yes, integrated for the canonical paper path.**

Why:
- Hyperliquid is enabled by default.
- Scanner emits Hyperliquid signals.
- Safety validates Hyperliquid proposals.
- Trader opens and closes Hyperliquid positions.
- Position state and performance update correctly.
- Agency-level offline tests prove entry and exit over multiple cycles.

### 3. Polymarket integration verdict

**Partial.**

Why:
- It is genuinely wired into the canonical paper flow.
- It is not just dead helper code or research-only scaffolding.
- It has dedicated scanner logic, adapter logic, safety checks, trader persistence, timeout-monitor support, schema support, and agency-level offline tests.
- But it is still only a paper-trading simulation path backed by read-only market data. That is not full end-to-end exchange integration in a production-readiness sense.

### 4. Docs/README statements not fully supported by code/tests

#### Supported
- Paper trading only.
- Hyperliquid canonical default.
- Polymarket paper path exists.
- Mixed mode is limited.
- Live trading not implemented.

#### Not fully supported or contradicted
1. **`docs/SYSTEM_ARCHITECTURE.md` understates CI proof.**
   - It still says the full orchestrator path is not exercised end-to-end in CI.
   - Current CI includes offline agency entrypoint tests for Hyperliquid, Polymarket, mixed, and negative paths.

2. **The repo says Polymarket is experimental, but persisted metadata often says otherwise.**
   - Signals/trades set `experimental: False` for Polymarket.
   - Runtime events mark Polymarket as experimental.
   - Exchange metadata marks Polymarket `paper_status` as `canonical`.

3. **Any claim that both exchanges are “fully integrated end-to-end” is still too strong.**
   - Code/tests only support canonical paper-runtime integration, not live exchange execution.

4. **Any claim that mixed mode is a true combined runtime should be rejected.**
   - Mixed mode is one-entry-per-cycle with deterministic Hyperliquid preference.

### 5. Authoritative vs non-canonical/historical files

#### Authoritative for current execution truth
- `config/runtime.py`
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
- `.github/workflows/basic.yml`
- `scripts/ci-safe-verification.sh`

#### Support-only / non-canonical
- `scripts/exit-monitor.py`
- `scripts/stability-monitor.py`
- `scripts/live-readiness-validator.py`
- `scripts/supervisor-governance.py`
- `scripts/exit-safeguards.py`
- `scripts/alpha-intelligence-layer.py`

#### Historical / scaffold / archive
- `scripts/archive/*`
- `docs/archive/*`

---

## Final verdict paragraph

Yes — you can truthfully say: **“Hyperliquid is integrated; Polymarket is experimental and not yet fully integrated.”** That sentence matches the actual code and tests if “integrated” is understood as **canonical paper-trading integration**, not live exchange execution. Hyperliquid is the proven canonical paper path. Polymarket is genuinely wired into that same paper runtime and is not just scaffold code, but it remains partial because the repo still lacks real authenticated execution, fill/settlement handling, and fully matured mixed-mode semantics.
