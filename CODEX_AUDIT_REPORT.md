# CODEX Audit Report

Audit date: 2026-03-23 UTC
Repository scope: current local checkout only
Standard: production-readiness and truthfulness audit with zero assumptions

## A. Executive verdict

- **Hyperliquid properly integrated?** **Yes, for the repository's canonical paper-trading path only.**
- **Polymarket properly integrated?** **Partial.** It is wired into the same canonical paper-trading path, but remains experimental, paper-only, asymmetric in mixed mode, and unproven for any live-execution meaning.
- **Repo truthfully represented?** **Partial.** Main truth surfaces are mostly aligned with code/tests, but active non-archive docs still contain stale/generated report content that can mislead reviewers.
- **System paper-trading only?** **Yes.**
- **Any live-ready claim that should be removed?** **No direct active live-ready claim remains in the main truth surfaces, but stale active docs and future-scope script names should be moved/labeled more aggressively because they can imply maturity the canonical path does not prove.**

### Bottom line

1. The real canonical entrypoint is `scripts/trading-agency-phase1.py`.
2. Hyperliquid is the strongest, best-supported end-to-end path in the repo.
3. Polymarket is **not** helper-only or research-only anymore; it is in the canonical paper flow.
4. Polymarket is still **not fully integrated** in any stronger sense than paper-trading runtime integration.
5. Mixed mode is real but deliberately limited: scan both, admit one new entry, prefer Hyperliquid.
6. CI proves offline paper behavior, schema normalization, and orchestration logic. It does **not** prove current external API reachability or live execution.

## B. Evidence table

| Component | Status | Evidence file paths | Exact reason |
|---|---|---|---|
| bootstrap/runtime check | working | `scripts/bootstrap-runtime-check.py`, `.github/workflows/basic.yml`, `scripts/ci-safe-verification.sh`, `tests/bootstrap-runtime-check-test.py` | Canonical bootstrap exists, is stage 1 in the orchestrator, and CI executes/tests it. It only checks Python dependencies, not exchange reachability. |
| orchestrator | working | `scripts/trading-agency-phase1.py`, `tests/destructive/trading-agency-hyperliquid-test.py`, `tests/destructive/trading-agency-polymarket-test.py`, `tests/destructive/trading-agency-negative-path-test.py` | Canonical flow is explicit and exercised offline through bootstrap → integrity → scan → safety → trader → persistence → monitor/report. |
| data integrity layer | working | `scripts/data-integrity-layer.py`, `tests/data-integrity-mode-gate-test.py`, `tests/signal-integrity-canonical-test.py`, `tests/mixed-mode-policy-test.py` | Pre-scan health gating and signal integrity are wired in and mode-aware. Scanner acceptance now enforces the same exchange-specific canonical signal contract that the trader uses later. |
| signal scanner | working | `scripts/phase1-signal-scanner.py`, `utils/api_connectivity.py`, `tests/paper-mode-schema-test.py`, `tests/signal-integrity-canonical-test.py` | Scanner emits both Hyperliquid and Polymarket paper signals, passes them through integrity validation, and appends to one canonical signal log. |
| execution safety | working | `scripts/execution-safety-layer.py`, `scripts/trading-agency-phase1.py`, `tests/execution-safety-schema-test.py`, `tests/destructive/trading-agency-negative-path-test.py` | Safety layer validates the next candidate entry, persists safety state, and can block new entries. It uses canonical trade history for breaker refresh. |
| paper trader | working | `scripts/phase1-paper-trader.py`, `utils/paper_exchange_adapters.py`, `tests/destructive/full-lifecycle-integration-test.py`, `tests/destructive/real-exit-integration-test.py`, `tests/destructive/polymarket-paper-flow-test.py` | Trader builds OPEN/CLOSED paper records, persists them, and updates canonical open-position state. This is paper simulation, not live execution. |
| trade schema | working | `models/trade_schema.py`, `tests/trade-schema-contract-test.py`, `tests/execution-safety-schema-test.py`, `tests/performance-dashboard-canonical-test.py` | Shared normalization layer covers both exchanges and downstream readers consume the same schema. |
| position state | working | `models/position_state.py`, `tests/trade-schema-contract-test.py`, `tests/destructive/trading-agency-hyperliquid-test.py`, `tests/destructive/trading-agency-polymarket-test.py` | One authoritative `position-state.json` is maintained from trade records and supports both exchanges. |
| timeout monitor | working | `scripts/timeout-monitor.py`, `scripts/trading-agency-phase1.py`, `tests/timeout-monitor-polymarket-threshold-test.py`, destructive agency tests | Monitor reads authoritative open-position state and writes monitoring artifacts. It does not authoritatively close trades. |
| exit monitor | non-canonical | `scripts/exit-monitor.py`, `scripts/trading-agency-phase1.py` | Explicitly skipped in the canonical loop because it writes proof artifacts without authoritative close persistence. |
| performance dashboard | working support reader | `scripts/performance-dashboard.py`, `tests/performance-dashboard-canonical-test.py`, `tests/trade-schema-contract-test.py` | Reads canonical trade/state files and splits output by exchange. Support-only reader, not execution proof. |
| Hyperliquid path | working | `scripts/phase1-signal-scanner.py`, `utils/paper_exchange_adapters.py`, `scripts/phase1-paper-trader.py`, `tests/destructive/trading-agency-hyperliquid-test.py`, `tests/destructive/trading-agency-hyperliquid-repeat-cycle-test.py` | Hyperliquid is fully wired through the canonical paper path and has the strongest orchestration proof coverage. |
| Polymarket path | partial | `scripts/phase1-signal-scanner.py`, `utils/paper_exchange_adapters.py`, `scripts/phase1-paper-trader.py`, `tests/destructive/trading-agency-polymarket-test.py`, `tests/destructive/polymarket-paper-flow-test.py`, `tests/polymarket-canonical-path-guard-test.py` | Polymarket is in the canonical paper flow and not helper-only, but remains experimental, public-data-only, paper-only, and lacks authenticated order placement/fill/settlement/live integration coverage. |
| mixed mode | partial | `config/runtime.py`, `models/exchange_metadata.py`, `scripts/data-integrity-layer.py`, `scripts/phase1-paper-trader.py`, `tests/destructive/trading-agency-mixed-test.py`, `tests/destructive/mixed-mode-integration-test.py`, `tests/mixed-mode-policy-test.py` | Mixed mode scans both exchanges and can store both in canonical state over time, but the agency loop allows only one new entry per cycle and deterministically prefers Hyperliquid. It is not a peer-symmetric dual-entry runtime. |
| CI workflow | working | `.github/workflows/basic.yml`, `scripts/ci-safe-verification.sh` | CI runs compile checks, regression tests, and destructive offline lifecycle proofs on push/PR. |
| destructive/integration tests | working but offline-only | `scripts/ci-safe-verification.sh`, `tests/destructive/*.py`, `tests/support/trading_agency_offline.py`, `tests/support/offline_requests_sitecustomize.py` | Integration-style tests exist and are valuable, but they are fixture-driven offline proofs, not live-network integration tests. |
| docs truthfulness | partial | `README.md`, `SYSTEM_STATUS.md`, `TRUTH_INDEX.md`, `PROOF_MATRIX.md`, `docs/SYSTEM_ARCHITECTURE.md`, `docs/POLYMARKET_EXECUTION_SCOPE.md`, `docs/TIMEOUT_MONITOR_REPORT.md`, `docs/POSITION_TRACKING_REPORT.md`, `docs/EXIT_TRACKER_REPORT.md` | Main truth docs are mostly aligned. Problem: active docs root still contains stale/generated report files that read like current operational evidence and in one case contradict current limits (`max open positions` 10 vs code 3). |

## C. Canonical flow map

Real current canonical flow, as implemented now:

1. **Workspace/bootstrap initialization**
   - `config/runtime.py` resolves `WORKSPACE_ROOT`, `LOGS_DIR`, `DATA_DIR` and creates directories.
   - `utils/system_health.py` ensures `workspace/operator_control.json` and `workspace/system_health.json` exist when the orchestrator instantiates `SystemHealthManager`.

2. **Canonical entrypoint starts**
   - Entry: `scripts/trading-agency-phase1.py::main()`.
   - Early output: mode banner, support-component visibility, canonical-path statement.

3. **Bootstrap dependency stage**
   - `scripts/trading-agency-phase1.py::run_bootstrap_check()` shells out to `scripts/bootstrap-runtime-check.py`.
   - No canonical trade/state file is written here.

4. **Health snapshot/state write**
   - `SystemHealthManager.write_system_status()` writes `workspace/system_status.json`.
   - Operator-control audit state may also exist in `workspace/logs/operator-control-audit.json`.

5. **Pre-scan data-integrity gate**
   - `scripts/trading-agency-phase1.py::run_data_integrity_gate()` calls `DataIntegrityLayer.run_pre_scan_gate()`.
   - Writes:
     - `workspace/logs/data-integrity-state.json`
     - `workspace/logs/source-reliability-metrics.json`
     - runtime events / possible incidents
   - Mode handling is here: Hyperliquid only, Polymarket only, or both with advisory secondary health in mixed mode.

6. **Signal generation**
   - `scripts/trading-agency-phase1.py::run_signal_scanner()` shells out to `scripts/phase1-signal-scanner.py`.
   - Scanner calls:
     - `scan_hyperliquid_funding()` if mode includes Hyperliquid
     - `scan_polymarket_markets()` if mode includes Polymarket
   - Signals then pass `DataIntegrityLayer.validate_signal()`.
   - Writes:
     - `workspace/logs/phase1-signals.jsonl`
     - `workspace/PHASE1_SIGNAL_REPORT.md`
     - updates data-integrity state/metrics again
     - runtime events

7. **Safety validation of the single next candidate**
   - `scripts/trading-agency-phase1.py::run_safety_validation()` loads trader + safety modules.
   - Candidate selection comes from `phase1-paper-trader.py::select_trade_candidate()`.
   - Safety layer persists `workspace/logs/execution-safety-state.json` before/after validation and may append `workspace/logs/blocked-actions.jsonl` or `workspace/logs/incident-log.jsonl`.

8. **Trader planning**
   - `scripts/trading-agency-phase1.py::run_trader()` calls `phase1-paper-trader.py::build_execution_plan()`.
   - Exit planning is evaluated first from current open positions.
   - New-entry planning is then allowed only if safety and health permit it.
   - Mixed mode still returns at most one new entry because candidate selection is singular and exchange priority is deterministic.

9. **Authoritative persistence**
   - `scripts/trading-agency-phase1.py::run_state_update()` calls:
     - `phase1-paper-trader.py::persist_trade_records()`
     - `phase1-paper-trader.py::calculate_performance()`
   - Writes:
     - `workspace/logs/phase1-paper-trades.jsonl` (append-only trade history)
     - `workspace/logs/position-state.json` (authoritative open positions only)
     - `workspace/logs/phase1-performance.json` (closed-trade summary)
     - refreshed `workspace/logs/execution-safety-state.json`
     - runtime events

10. **Monitor/report stage**
    - `scripts/trading-agency-phase1.py::evaluate_monitor_scripts()` runs `timeout-monitor.py` and explicitly skips `exit-monitor.py`.
    - Timeout monitor writes:
      - `workspace/logs/timeout-history.jsonl`
      - `workspace/TIMEOUT_MONITOR_REPORT.md`
      - runtime events
    - Exit monitor is **not** part of canonical close persistence.

11. **Cycle summary/report generation**
    - `scripts/trading-agency-phase1.py::build_cycle_summary()` writes:
      - `workspace/logs/agency-cycle-summary.json`
      - `workspace/AGENCY_CYCLE_SUMMARY.md`
    - `scripts/trading-agency-phase1.py::generate_agency_report()` writes:
      - `workspace/logs/agency-phase1-report.json`
    - `SystemHealthManager.write_system_status()` refreshes `workspace/system_status.json` again.

## D. Gap analysis: what blocks any truthful claim that both Hyperliquid and Polymarket are fully integrated

1. **No live execution path exists for either exchange.**
   - The repo is paper-only by design and by docs.
   - There is no order signing, authenticated placement, fill reconciliation, or settlement logic.

2. **Polymarket uses only public market-data APIs in the canonical path.**
   - Scanner and price lookups use Gamma/public endpoints.
   - That is enough for paper simulation, not enough for full exchange integration.

3. **Polymarket is explicitly marked experimental in runtime metadata.**
   - This is not just a docs label; the runtime propagates `experimental=True` in signals, trades, and events.

4. **Mixed mode is intentionally asymmetric.**
   - It scans both, but only one new entry is admitted per cycle.
   - Hyperliquid has deterministic priority.
   - Therefore Polymarket is not a peer-symmetric participant in mixed mode.

5. **CI proves offline fixture behavior, not live network integration.**
   - Tests patch requests and use deterministic fixtures.
   - Useful for correctness of repo logic, not proof of present-day exchange compatibility.

6. **Current connectivity was not proven in this audit environment.**
   - Read-only connectivity checks to Hyperliquid and Polymarket both failed here with proxy 403 tunnel errors.
   - That is an environment/network limitation, but it means there is still no direct live reachability proof from this audit run.

7. **Active docs still include misleading generated report files outside archive.**
   - These files can be mistaken for authoritative current evidence.
   - They do not change the code reality, but they weaken repo truthfulness.

## E. Repair plan

### Phase 0: truth cleanup

1. **Move or relabel stale generated docs in `docs/`**
   - **Files:** `docs/TIMEOUT_MONITOR_REPORT.md`, `docs/POSITION_TRACKING_REPORT.md`, `docs/EXIT_TRACKER_REPORT.md`
   - **Why:** these are generated/example artifacts in active docs scope; they look current and one contradicts code limits.
   - **Dependency/order:** first.
   - **Risk:** low.
   - **Done criteria:** each file is either archived/moved or has a top-of-file banner declaring historical/example-only, non-canonical, and non-current.

2. **Add one explicit truth note about offline-only proof scope**
   - **Files:** `README.md`, `SYSTEM_STATUS.md`, `docs/OPERATOR_EVIDENCE_GUIDE.md`
   - **Why:** make it impossible to confuse offline fixture proof with live integration proof.
   - **Dependency/order:** after stale-doc cleanup.
   - **Risk:** low.
   - **Done criteria:** all active truth surfaces use the same language: “canonical paper path”, “offline-proven”, “not live integration proof”.

3. **Reduce future-scope naming ambiguity**
   - **Files:** `scripts/live-readiness-validator.py`, `scripts/supervisor-governance.py`, related docs that mention them.
   - **Why:** filenames still imply a stronger operational scope than the canonical runtime supports.
   - **Dependency/order:** independent.
   - **Risk:** low-medium if imports/docs reference names.
   - **Done criteria:** support/future-scope scripts are unmistakably labeled non-canonical in filename or top-level truth docs.

### Phase 1: fix canonical architecture

1. **Make exchange-specific signal validation explicit at integrity stage** — **completed**
   - **Files:** `scripts/data-integrity-layer.py`, `utils/paper_exchange_adapters.py`, `scripts/phase1-signal-scanner.py`
   - **Why:** scanner acceptance now implies trader executability by applying exchange-specific canonical contract checks before append-only persistence.
   - **Dependency/order:** foundational architecture fix already landed; keep regression coverage in place.
   - **Risk:** medium, because scanner rejection rates may change.
   - **Done criteria:** met — signal integrity rejects exchange-invalid Hyperliquid and Polymarket signals before append-only persistence.

2. **Define canonical state contract in one place and reuse it everywhere**
   - **Files:** `models/trade_schema.py`, `models/position_state.py`, `scripts/phase1-paper-trader.py`, `scripts/performance-dashboard.py`, `scripts/timeout-monitor.py`
   - **Why:** trade/state agreement is mostly good now, but still spread across multiple modules with implicit duplication.
   - **Dependency/order:** after exchange-specific validation.
   - **Risk:** medium.
   - **Done criteria:** all readers/producers import one shared contract for canonical open/closed records and exchange-specific optional fields.

3. **Separate canonical artifacts from support artifacts in docs and code references**
   - **Files:** `README.md`, `TRUTH_INDEX.md`, `docs/SYSTEM_ARCHITECTURE.md`, `scripts/trading-agency-phase1.py`
   - **Why:** current code already skips non-canonical monitor paths; docs should be equally sharp.
   - **Dependency/order:** parallel with above.
   - **Risk:** low.
   - **Done criteria:** no active doc leaves ambiguity about which files are authoritative vs support-only.

### Phase 2: repair/add tests

1. **Add live-shape contract tests for both public APIs, gated non-blocking**
   - **Files:** add `tests/nonblocking/` or equivalent, update `scripts/ci-safe-verification.sh`, add a manual/nonblocking workflow step or documented command.
   - **Why:** current tests prove repo logic only; they do not prove current public payload compatibility.
   - **Dependency/order:** after exchange-specific validation.
   - **Risk:** medium because live APIs are flaky/changeable.
   - **Done criteria:** optional/manual tests assert expected top-level payload shape for current Hyperliquid and Polymarket public endpoints.

2. **Add canonical agency tests for negative Polymarket paths**
   - **Files:** new destructive/offline tests under `tests/destructive/`
   - **Why:** Hyperliquid has stronger negative-path coverage than Polymarket.
   - **Dependency/order:** after Phase 1 validation fixes.
   - **Risk:** low-medium.
   - **Done criteria:** offline proofs cover stale Polymarket signals, duplicate market entries, broken token metadata, and missing market_id/token_id cases.

3. **Add mixed-mode persistence/restart coverage at the orchestrator level**
   - **Files:** new `tests/destructive/` mixed-mode multi-cycle test.
   - **Why:** current mixed proof shows the limitation, but not restart/recovery behavior across multiple cycles with both exchanges appearing in shared state over time.
   - **Dependency/order:** after Phase 1 architecture cleanup.
   - **Risk:** medium.
   - **Done criteria:** test proves mixed mode across multiple cycles without duplicate leakage, state corruption, or ambiguous selection behavior.

### Phase 3: Polymarket integration completion

1. **Decide the target: remain paper-only or implement live execution**
   - **Files:** `README.md`, `SYSTEM_STATUS.md`, `docs/POLYMARKET_EXECUTION_SCOPE.md`, roadmap docs.
   - **Why:** without this decision, “full integration” stays undefined and misleading.
   - **Dependency/order:** first step in this phase.
   - **Risk:** organizational, not technical.
   - **Done criteria:** repo owners explicitly choose either “paper-only research integration” or “live execution roadmap”.

2. **If live execution is desired, add authenticated Polymarket execution path**
   - **Files:** new canonical execution module(s), `scripts/phase1-paper-trader.py` or successor, config/secrets wiring, docs.
   - **Why:** current code has no authenticated trading capability at all.
   - **Dependency/order:** after target decision.
   - **Risk:** high.
   - **Done criteria:** canonical runtime can place, track, reconcile, and settle Polymarket orders in a controlled non-paper environment.

3. **Add Polymarket fill/state reconciliation**
   - **Files:** canonical execution/persistence modules, state models, tests.
   - **Why:** “integrated” is not truthful without order/fill/state alignment.
   - **Dependency/order:** after authenticated execution exists.
   - **Risk:** high.
   - **Done criteria:** canonical state is driven by exchange-confirmed fills, not synthetic paper fills.

4. **Upgrade mixed mode only if peer-symmetric exchange handling is desired**
   - **Files:** `models/exchange_metadata.py`, `scripts/phase1-paper-trader.py`, `scripts/trading-agency-phase1.py`, tests/docs.
   - **Why:** mixed mode currently encodes Hyperliquid priority by design.
   - **Dependency/order:** only after single-exchange live semantics are stable.
   - **Risk:** high.
   - **Done criteria:** mixed mode semantics are explicit, tested, and either intentionally asymmetric or truly peer-symmetric.

### Phase 4: observability and docs cleanup

1. **Mark every generated/example report as generated/example-only**
   - **Files:** all generated docs under `docs/` that are not canonical truth docs.
   - **Why:** generated files are currently mixed with normative docs.
   - **Dependency/order:** after Phase 0 or in parallel.
   - **Risk:** low.
   - **Done criteria:** every generated/example file starts with status + truthfulness note.

2. **Publish one canonical truth map and retire duplicate truth surfaces**
   - **Files:** `TRUTH_INDEX.md`, `README.md`, `SYSTEM_STATUS.md`, `docs/SYSTEM_ARCHITECTURE.md`, root audit files.
   - **Why:** there are multiple truth-summary docs; duplication raises drift risk.
   - **Dependency/order:** after truth cleanup.
   - **Risk:** low.
   - **Done criteria:** one entry doc links to all current evidence, and duplicate historical claims are archived or removed.

3. **Add a nonblocking operator command for current API reachability**
   - **Files:** `README.md`, `docs/OPERATOR_QUICKSTART.md`, maybe `scripts/runtime-connectivity-check.py`
   - **Why:** repo already has the script; docs should frame it as current-environment reachability evidence, not repo capability proof.
   - **Dependency/order:** low.
   - **Risk:** low.
   - **Done criteria:** operators can explicitly distinguish “repo logic passes offline” from “current network path is reachable”.

## F. Contradictions called out explicitly

1. **`docs/POSITION_TRACKING_REPORT.md` says max open positions is 10, but canonical code sets `MAX_OPEN_POSITIONS = 3`.**
2. **Active docs root contains generated monitoring/tracking reports that look like current evidence, while the canonical runtime truth lives elsewhere.**
3. **Polymarket is described as canonical paper-path capable, which is true in code/tests, but mixed mode still hard-codes Hyperliquid priority, so Polymarket is not an equal participant in the main mixed loop.**
4. **Signal integrity is described as canonical validation before persistence, which is true, but that validation is generic and does not fully guarantee exchange-specific trader executability.**
5. **CI is strong for offline proofs, but any reader equating that with live exchange compatibility would be overclaiming.**

## Final verdict paragraph

Yes — you can truthfully say: **“Hyperliquid is integrated; Polymarket is experimental and not yet fully integrated.”** That sentence matches the current repository if “integrated” is understood as **integrated into the canonical paper-trading runtime from entrypoint to persistence**, not live execution. Hyperliquid is the strongest end-to-end path in that sense. Polymarket is genuinely wired into the canonical paper path and is not just helper/scaffold code, but it remains incomplete for any stronger claim because there is no authenticated execution path, no fill/settlement handling, no live integration proof, and mixed mode still gives deterministic priority to Hyperliquid.
