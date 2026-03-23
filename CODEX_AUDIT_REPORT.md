# CODEX Audit Report

Date: 2026-03-23 UTC
Repo: `yumorepos/autonomous-trading-system`
Scope: production-readiness and truthfulness audit of the current repository state

## A. Executive verdict

- **Hyperliquid properly integrated?** **Yes, for the paper-trading canonical path only.**
- **Polymarket properly integrated?** **Partial.** It is integrated into the same paper-trading path, but not into any live execution path, and mixed mode does not treat it as a first-class peer.
- **Repo truthfully represented?** **Partial.** Top-level truth surfaces are mostly honest, but some active support docs still describe stronger data/safety behavior than the canonical code actually executes.
- **System paper-trading only?** **Yes.**
- **Any live-ready claim that should be removed?** **No direct active live-ready claim remains in the main truth surfaces, but support docs should still be tightened because they describe broader behavior than the canonical path actually enforces.**

Bottom line:
- Hyperliquid is the real canonical exchange path.
- Polymarket is not helper-only; it is wired into the canonical paper path.
- Polymarket is still **not** fully integrated in any live or production sense.
- Mixed mode is explicitly limited and asymmetrical.

## B. Evidence table

| Component | Status | Evidence | Exact reason |
|---|---|---|---|
| bootstrap/runtime check | working | `scripts/bootstrap-runtime-check.py`; `tests/bootstrap-runtime-check-test.py`; `.github/workflows/basic.yml`; `scripts/ci-safe-verification.sh` | Bootstrap is the first runtime stage, checks only Python deps, and is covered by CI. It does not prove exchange connectivity. |
| orchestrator | working | `scripts/trading-agency-phase1.py`; `tests/destructive/trading-agency-hyperliquid-test.py`; `tests/destructive/trading-agency-polymarket-test.py` | Canonical entrypoint is `scripts/trading-agency-phase1.py`. It runs bootstrap → data integrity → scanner → safety → trader → persistence → monitors, then writes cycle/report artifacts. |
| data integrity layer | partial | `scripts/data-integrity-layer.py`; `tests/data-integrity-mode-gate-test.py`; `tests/mixed-mode-policy-test.py`; `docs/DATA_INTEGRITY_LAYER.md` | Pre-scan API/freshness/completeness gating is wired. But the richer signal-level logic (`validate_signal`, duplicate detection, decay, rejected-signal logging) exists in code and is described in docs, yet is not called by the canonical scanner/orchestrator. |
| signal scanner | working | `scripts/phase1-signal-scanner.py`; `tests/paper-mode-schema-test.py` | Scanner emits canonical Hyperliquid and Polymarket paper signals into one shared schema and appends them to canonical signal history. |
| execution safety | working | `scripts/execution-safety-layer.py`; `tests/execution-safety-schema-test.py` | Safety is in the canonical loop and blocks on stale signals, duplicates, size limits, kill switch, circuit breakers, and exchange-health failures. Liquidity/spread/data-integrity checks are advisory or warning-level depending on the check. |
| paper trader | working | `scripts/phase1-paper-trader.py`; `tests/destructive/full-lifecycle-integration-test.py`; `tests/destructive/polymarket-paper-flow-test.py` | Trader builds paper-only OPEN/CLOSED records for both exchanges, persists them, and updates canonical position state. |
| trade schema | working | `models/trade_schema.py`; `tests/trade-schema-contract-test.py` | One normalized trade schema supports both exchanges and validates required fields, including Polymarket `market_id`. |
| position state | working | `models/position_state.py`; `tests/trade-schema-contract-test.py`; `tests/destructive/mixed-mode-integration-test.py` | One canonical `position-state.json` stores open positions for both exchanges. Close events remove positions by `trade_id`. |
| timeout monitor | working | `scripts/timeout-monitor.py`; `tests/timeout-monitor-polymarket-threshold-test.py`; `tests/destructive/trading-agency-polymarket-test.py` | Timeout monitor reads canonical open positions, uses exchange adapters, and applies exchange-specific thresholds. It is the only monitor run by the orchestrator. |
| exit monitor | non-canonical | `scripts/trading-agency-phase1.py`; `scripts/exit-monitor.py`; `tests/destructive/trading-agency-polymarket-test.py` | Orchestrator intentionally skips `exit-monitor.py` because it writes proof/report artifacts without authoritative close persistence. |
| performance dashboard | working | `scripts/performance-dashboard.py`; `tests/performance-dashboard-canonical-test.py` | Dashboard reads canonical trade history plus canonical open-position state; it is a reader only. |
| Hyperliquid path | working | `scripts/phase1-signal-scanner.py`; `utils/paper_exchange_adapters.py`; `tests/destructive/trading-agency-hyperliquid-test.py`; `tests/destructive/trading-agency-hyperliquid-repeat-cycle-test.py` | Hyperliquid is fully wired through scanner, safety, trader, persistence, monitor, and CI-backed offline agency tests. |
| Polymarket path | partial | `scripts/phase1-signal-scanner.py`; `utils/paper_exchange_adapters.py`; `tests/destructive/trading-agency-polymarket-test.py`; `docs/POLYMARKET_EXECUTION_SCOPE.md` | Polymarket is wired through the same paper path and proven offline. But it only uses public market-data endpoints and paper execution. No authenticated order path, wallet/signing flow, fill reconciliation, or settlement exists. |
| mixed mode | partial | `models/exchange_metadata.py`; `scripts/phase1-paper-trader.py`; `scripts/data-integrity-layer.py`; `tests/destructive/trading-agency-mixed-test.py`; `tests/mixed-mode-policy-test.py` | Mixed mode scans both exchanges and can accumulate both exchanges in shared state over time, but admits only one new entry per cycle and deterministically favors Hyperliquid. Secondary Polymarket health is advisory when Hyperliquid is enabled. |
| CI workflow | working with bounded scope | `.github/workflows/basic.yml`; `scripts/ci-safe-verification.sh` | CI runs compile checks plus offline regression/destructive tests. It explicitly excludes blocking network-dependent checks. |
| destructive/integration tests | partial | `tests/destructive/*.py`; `tests/support/trading_agency_offline.py` | Integration proof is strong for offline paper mode. There are no live exchange integration tests, authenticated execution tests, or network-backed end-to-end tests. |
| docs truthfulness | partial | `README.md`; `SYSTEM_STATUS.md`; `docs/POLYMARKET_EXECUTION_SCOPE.md`; `docs/DATA_INTEGRITY_LAYER.md`; `docs/EXECUTION_SAFETY_LAYER.md` | Main truth surfaces are mostly accurate. Support docs for the data-integrity and safety layers still describe stronger guarantees and a broader architecture than the canonical flow actually enforces. |

## C. Canonical flow map

Real canonical execution flow as implemented now:

1. **Entrypoint:** `scripts/trading-agency-phase1.py`
   - Prints mode/truth banner.
   - Declares `hyperliquid_only` and `polymarket_only` as canonical paper-trading modes.
   - Declares `mixed` as experimental/non-canonical proof mode.

2. **Bootstrap stage:** subprocess call to `scripts/bootstrap-runtime-check.py`
   - Output: no canonical state files.
   - Purpose: check import-time runtime dependencies only.

3. **Health snapshot and operator-control evaluation:** `utils/system_health.py`
   - Writes/updates:
     - `workspace/system_health.json`
     - `workspace/system_status.json`
     - `workspace/operator_control.json` if missing
     - `workspace/logs/operator-actions.jsonl`
     - `workspace/logs/operator-control-audit.json`
     - `workspace/logs/system-incidents.jsonl`

4. **Pre-scan data gate:** `scripts/data-integrity-layer.py` via imported module
   - Writes/updates:
     - `workspace/logs/data-integrity-state.json`
     - `workspace/logs/source-reliability-metrics.json`
     - runtime event stream in `workspace/logs/runtime-events.jsonl`
   - In mixed mode, Hyperliquid is primary; Polymarket health can degrade to warning-only.

5. **Signal scan:** subprocess call to `scripts/phase1-signal-scanner.py`
   - Fetches market data using `utils/api_connectivity.py`.
   - Writes:
     - `workspace/logs/phase1-signals.jsonl`
     - `workspace/PHASE1_SIGNAL_REPORT.md`
     - runtime event stream in `workspace/logs/runtime-events.jsonl`

6. **Safety validation:** `scripts/execution-safety-layer.py` via imported module
   - Reads latest signals and current open positions.
   - Chooses exactly one candidate signal.
   - Writes/updates:
     - `workspace/logs/execution-safety-state.json`
     - `workspace/logs/blocked-actions.jsonl` when blocked
     - `workspace/logs/incident-log.jsonl`

7. **Trader plan construction:** `scripts/phase1-paper-trader.py`
   - Builds planned closes first, then at most one planned entry.
   - In mixed mode, selection order is by exchange priority then EV score; Hyperliquid priority is lower numeric value and therefore wins ties/ordering.

8. **Authoritative persistence:** `scripts/phase1-paper-trader.py` + `models/position_state.py`
   - Writes:
     - `workspace/logs/phase1-paper-trades.jsonl`
     - `workspace/logs/position-state.json`
     - `workspace/logs/phase1-performance.json`
     - runtime events in `workspace/logs/runtime-events.jsonl`

9. **Monitor stage:** `scripts/trading-agency-phase1.py`
   - Skips `scripts/exit-monitor.py` intentionally.
   - Runs `scripts/timeout-monitor.py` only.
   - Writes:
     - `workspace/logs/timeout-history.jsonl`
     - `workspace/TIMEOUT_MONITOR_REPORT.md`

10. **Cycle/report packaging:** `scripts/trading-agency-phase1.py`
    - Writes:
      - `workspace/logs/agency-cycle-summary.json`
      - `workspace/AGENCY_CYCLE_SUMMARY.md`
      - `workspace/logs/agency-phase1-report.json`

## D. Gap analysis: what blocks any truthful claim that both Hyperliquid and Polymarket are fully integrated

1. **No live execution path exists for either exchange.**
   - The repo is paper-trading only.
   - There is no truthful basis for “fully integrated” if that phrase implies executable real trading.

2. **Polymarket code is paper-trading only and market-data only.**
   - Adapter methods call public Gamma market endpoints for health, liquidity, spread, and current price.
   - There is no authenticated Polymarket order client, no signing flow, no order placement, no fills, and no settlement.

3. **Hyperliquid is also only paper-trading here.**
   - Hyperliquid has a stronger canonical path than Polymarket, but it is still not a live trading integration.
   - “Integrated” is truthful only with a paper-trading qualifier.

4. **Mixed mode is not a dual-exchange operator-grade runtime.**
   - It is asymmetrical by design.
   - New entries are capped at one per cycle.
   - Hyperliquid is the deterministic priority winner.
   - Polymarket is not a peer in mixed-mode entry selection.

5. **CI proves offline fixtures, not network-backed exchange execution.**
   - The repo has strong offline proof.
   - It does not have live authenticated integration tests.
   - It does not even make read-only network success a CI requirement.

6. **Signal-level data-integrity logic is not wired into the canonical scanner flow.**
   - The code contains duplicate detection, signal decay, rejected-signal logging, and per-signal validation.
   - The canonical scanner does not call that logic before persisting signals.
   - Some active docs imply this richer behavior is active now.

7. **Some active support docs are stronger than the code path.**
   - `docs/DATA_INTEGRITY_LAYER.md` says no data enters the system without passing validation, but canonical execution only runs the pre-scan gate; it does not run `validate_signal` on emitted signals.
   - `docs/EXECUTION_SAFETY_LAYER.md` still describes a broader architecture position and future/live concepts; the top note mitigates this, but the document still reads broader than the code path actually proves.

8. **There is extra non-canonical surface area that can still confuse reviewers.**
   - `scripts/exit-monitor.py`, `scripts/live-readiness-validator.py`, `scripts/stability-monitor.py`, `scripts/portfolio-allocator.py`, `scripts/supervisor-governance.py`, and other support scripts are outside the canonical path.
   - Historical material remains extensive under `docs/archive/` and `scripts/archive/`.

## E. Repair plan

### Phase 0: truth cleanup

1. **Tighten active support docs to match the canonical path exactly**
   - **Files to edit:** `docs/DATA_INTEGRITY_LAYER.md`, `docs/EXECUTION_SAFETY_LAYER.md`, `docs/OPERATOR_QUICKSTART.md`, `docs/SYSTEM_ARCHITECTURE.md`
   - **Why:** current top-level truth is mostly good, but support docs still describe behavior that is broader than what the canonical flow executes.
   - **Dependency/order:** first.
   - **Risk:** low.
   - **Done criteria:** every active doc describes only code paths that are actually executed by `scripts/trading-agency-phase1.py` or clearly marks future/support-only behavior.

2. **Make canonical/non-canonical status explicit in one root index and stop duplicating status language**
   - **Files to edit:** `TRUTH_INDEX.md`, `README.md`, `SYSTEM_STATUS.md`
   - **Why:** repo already trends this way, but duplicated wording increases drift risk.
   - **Dependency/order:** after doc tightening.
   - **Risk:** low.
   - **Done criteria:** one canonical status block is referenced by the other docs, and non-canonical/support-only scripts are consistently labeled.

### Phase 1: fix canonical architecture

3. **Wire signal-level integrity validation into the canonical scanner before signal persistence**
   - **Files to edit:** `scripts/phase1-signal-scanner.py`, `scripts/data-integrity-layer.py`
   - **Why:** `validate_signal`, `apply_signal_decay`, duplicate detection, and rejected-signal logging exist but are not used in the canonical flow.
   - **Dependency/order:** after Phase 0 doc cleanup.
   - **Risk:** medium because this can change signal volume and downstream tests.
   - **Done criteria:** every persisted signal has passed canonical per-signal validation; rejected signals are logged in `workspace/logs/rejected-signals.jsonl`; scanner report clearly counts accepted vs rejected signals.

4. **Reduce duplicate/non-canonical monitor surface**
   - **Files to edit:** `scripts/exit-monitor.py`, `scripts/timeout-monitor.py`, `docs/RUNTIME_OBSERVABILITY.md`, `docs/SYSTEM_ARCHITECTURE.md`
   - **Why:** exit monitoring/reporting is split between a canonical timeout monitor and a deliberately skipped exit monitor, which confuses reviewers.
   - **Dependency/order:** after task 3.
   - **Risk:** medium.
   - **Done criteria:** either `exit-monitor.py` is archived/retired or rewritten as a pure reader over canonical state with no pseudo-authoritative semantics.

5. **Make mixed-mode limitation machine-readable in runtime outputs**
   - **Files to edit:** `scripts/trading-agency-phase1.py`, `scripts/phase1-paper-trader.py`, `models/exchange_metadata.py`
   - **Why:** current behavior is limited but correct; reports should expose that no more than one new mixed-mode entry is allowed and why a specific exchange won selection.
   - **Dependency/order:** after task 3.
   - **Risk:** low.
   - **Done criteria:** cycle summary/report includes `mixed_mode_policy` details and selected-vs-rejected candidate metadata.

### Phase 2: repair/add tests

6. **Add a test that proves signal-level integrity validation is executed in the canonical path**
   - **Files to edit:** `tests/paper-mode-schema-test.py`, add new focused test under `tests/`
   - **Why:** current tests prove schema output, not signal-level integrity enforcement inside the canonical scanner runtime.
   - **Dependency/order:** after Phase 1 task 3.
   - **Risk:** low.
   - **Done criteria:** a test fails if scanner persists a stale/duplicate/expired signal without calling the integrity layer.

7. **Add integration coverage for mixed-mode multi-cycle accumulation with canonical orchestrator, not just trader-only state tests**
   - **Files to edit:** add new destructive test under `tests/destructive/`
   - **Why:** current mixed-mode agency proof covers one-cycle Hyperliquid-preferred entry and separate trader-only state accumulation, but not a stronger multi-cycle orchestrator proof of both exchanges coexisting under canonical flow.
   - **Dependency/order:** after Phase 1 task 5.
   - **Risk:** medium.
   - **Done criteria:** orchestrator-level mixed-mode test shows both exchanges can appear in canonical shared state across multiple cycles while preserving the one-entry-per-cycle rule.

8. **Add a negative-path Polymarket test suite around bad market payloads and schema rejection**
   - **Files to edit:** add tests under `tests/` and `tests/destructive/` as needed
   - **Why:** current Polymarket proof is mostly happy-path paper-mode coverage.
   - **Dependency/order:** parallel with task 7.
   - **Risk:** low.
   - **Done criteria:** malformed token structures, missing `market_id`, bad price ranges, and low-liquidity markets are explicitly rejected and covered by tests.

### Phase 3: Polymarket integration completion

9. **Decide the target truth: keep Polymarket paper-only, or implement real execution**
   - **Files to edit:** `README.md`, `docs/POLYMARKET_EXECUTION_SCOPE.md`, architecture docs
   - **Why:** right now Polymarket is in a clear paper-only middle state.
   - **Dependency/order:** before any live implementation work.
   - **Risk:** medium product/strategy risk.
   - **Done criteria:** repo owners explicitly choose either “paper-only research integration” or “live execution roadmap”.

10. **If live Polymarket execution is desired, add real execution components instead of continuing to imply completeness from paper mode**
   - **Files to edit:** new client module(s) plus `utils/paper_exchange_adapters.py` split into paper vs live adapters; orchestrator; tests; docs
   - **Why:** current Polymarket adapter is only public market-data + paper math.
   - **Dependency/order:** only after task 9.
   - **Risk:** high.
   - **Done criteria:** authenticated client, signing/wallet flow, order placement, fill reconciliation, settlement handling, and live integration tests exist.

11. **If live Polymarket execution is not desired, rename surfaces to remove any residual ambiguity**
   - **Files to edit:** `models/exchange_metadata.py`, docs, possibly adapter names
   - **Why:** “canonical” currently means canonical paper path, not production completeness.
   - **Dependency/order:** after task 9 if live work is explicitly out of scope.
   - **Risk:** low.
   - **Done criteria:** docs and code consistently say `canonical paper path` or `paper adapter`, never just `canonical integration` without qualification.

### Phase 4: observability and docs cleanup

12. **Emit a canonical runtime manifest each cycle**
   - **Files to edit:** `scripts/trading-agency-phase1.py`
   - **Why:** reviewers currently have to infer active vs skipped support scripts from stage output and docs.
   - **Dependency/order:** after Phase 1.
   - **Risk:** low.
   - **Done criteria:** one JSON artifact explicitly lists entrypoint, stages run, scripts skipped, state files touched, and mode policy applied.

13. **Archive or demote support-only docs that read like active subsystem specs**
   - **Files to edit:** move or relabel `docs/CAPITAL_ALLOCATION.md`, `docs/THREE_STAGE_GOVERNANCE.md`, `docs/EXIT_TRACKER_REPORT.md`, `docs/POSITION_TRACKING_REPORT.md`, `docs/STABILITY_REPORT.md` as needed
   - **Why:** they increase truth-surface area beyond the canonical loop.
   - **Dependency/order:** after Phase 0.
   - **Risk:** low.
   - **Done criteria:** active docs directory contains only canonical runtime, operator, proof, and bounded support docs.

14. **Add a docs truth guard for support docs, not just README/SYSTEM_STATUS/PROOF_MATRIX**
   - **Files to edit:** `tests/repo-truth-guard-test.py` or new docs truth test
   - **Why:** current truth guard protects only a subset of active docs.
   - **Dependency/order:** after doc cleanup.
   - **Risk:** low.
   - **Done criteria:** CI fails if active docs reintroduce unsupported claims about live readiness, mixed-mode maturity, or unwired signal-integrity behavior.

## F. Authoritative vs non-canonical files

### Authoritative for the current runtime

- `scripts/trading-agency-phase1.py`
- `scripts/bootstrap-runtime-check.py`
- `scripts/data-integrity-layer.py` (**pre-scan gate portion only is canonical in runtime**)
- `scripts/phase1-signal-scanner.py`
- `scripts/execution-safety-layer.py`
- `scripts/phase1-paper-trader.py`
- `scripts/timeout-monitor.py`
- `models/trade_schema.py`
- `models/position_state.py`
- `utils/paper_exchange_adapters.py`
- `utils/api_connectivity.py`
- `.github/workflows/basic.yml`
- `scripts/ci-safe-verification.sh`
- the tests under `tests/` and `tests/destructive/` that are invoked by the CI script

### Non-canonical, support-only, or historical

- `scripts/exit-monitor.py` — intentionally skipped by orchestrator
- `scripts/live-readiness-validator.py` — future-scope modeling only
- `scripts/stability-monitor.py`, `scripts/exit-safeguards.py`, `scripts/position-exit-tracker.py`, `scripts/enhanced-exit-capture.py`, `scripts/supervisor-governance.py`, `scripts/portfolio-allocator.py`, `scripts/alpha-intelligence-layer.py` — support-only, not on canonical execution path
- `docs/archive/` and `scripts/archive/` — historical

## Explicit contradictions called out

1. **Docs say the data-integrity layer ensures “No data enters the system without passing validation.”**
   - Real code only runs the pre-scan gate in the canonical orchestrator.
   - The signal-level validation path exists but is not wired into scanner persistence.

2. **Docs can make mixed mode sound broader than it is.**
   - Real code and tests show mixed mode is constrained to one new entry per cycle and Hyperliquid-priority selection.

3. **Polymarket is not helper/scaffold code.**
   - It is present in the scanner, adapter layer, safety path, trader, state model, timeout monitor, and offline agency tests.
   - But it is still not fully integrated in the live-execution sense.

## Final verdict paragraph

Yes — you can truthfully say: **“Hyperliquid is integrated; Polymarket is experimental and not yet fully integrated.”** That sentence matches the current code and tests if “integrated” is understood as **integrated into the repository’s canonical paper-trading runtime**, not live execution. Hyperliquid is the real canonical path. Polymarket is genuinely wired into that same paper-only path and is not just helper code, but it remains incomplete for any stronger claim because there is no authenticated execution path, no settlement/fill handling, no live integration tests, and mixed mode still treats Hyperliquid as the deterministic primary exchange.
