# CODEX Audit Report

Date: 2026-03-21 UTC
Repo audited: `yumorepos/autonomous-trading-system`
Audit scope: repository truthfulness, canonical execution path, subsystem wiring, mode handling, CI proof surface, and Hyperliquid/Polymarket integration completeness.

## A. Executive Verdict

| Question | Verdict | Basis |
|---|---|---|
| Is Hyperliquid properly integrated? | **Partial** | The canonical paper path is wired for Hyperliquid from scanner -> safety -> trader -> persistence -> timeout monitor, but CI does not run the orchestrator end-to-end and the strongest lifecycle tests inject signals directly into `phase1-paper-trader.py` rather than proving the full agency path. |
| Is Polymarket properly integrated? | **Partial** | Polymarket is wired into the same paper path and has isolated paper-flow tests, but it is explicitly experimental, depends on the same market-data endpoint for scan/safety/price checks, is not exercised through the orchestrator in CI, and still coexists with non-canonical helper/state files. |
| Is the repo truthfully represented? | **Partial** | The active docs are mostly honest about paper-only scope and Polymarket being experimental, but they overstate what CI proves, treat mixed mode as stronger than the code/test proof supports, and leave active-tree future/live-oriented artifacts and non-canonical Polymarket state around. |
| Is the system paper-trading only? | **Yes** | No live order path is implemented in the canonical flow; non-canonical helper scripts also explicitly say real execution is incomplete/disabled. |
| Is there any live-ready claim that should be removed? | **Yes** | Active-tree files still expose future/live-readiness framing (`live-readiness-validator.py`, supervisor `LIVE` stage, `Portfolio-ready` wording) that is not backed by current code or tests. |

### Bottom line

This repository is a **paper-trading research system**, not a production-ready trading system. Hyperliquid is the strongest path, but even that path is only **partially proven end-to-end**. Polymarket is **paper-wired but experimental** rather than fully integrated.

## B. Evidence Table

| Component | Status | Evidence file paths | Exact reason |
|---|---|---|---|
| bootstrap/runtime check | Working | `scripts/bootstrap-runtime-check.py`, `tests/bootstrap-runtime-check-test.py`, `requirements.txt` | Bootstrap is small and direct: it checks importable dependencies and is covered by a dedicated regression test. It proves runtime package presence only, not exchange reachability. |
| orchestrator | Partial | `scripts/trading-agency-phase1.py`, `.github/workflows/basic.yml`, `scripts/ci-safe-verification.sh` | The agency script is the real canonical entrypoint, but CI never executes it. The repo has no orchestrator integration test covering actual stage sequencing, real module loading, or final agency report generation. |
| data integrity layer | Partial | `scripts/data-integrity-layer.py`, `tests/data-integrity-mode-gate-test.py` | Mode-aware gating exists and the Polymarket-only mode gate is tested, but the gate remains network-bound in real runs and CI only proves a mocked mode-selection path. |
| signal scanner | Partial | `scripts/phase1-signal-scanner.py`, `tests/paper-mode-schema-test.py` | Hyperliquid and Polymarket scanners emit normalized paper signals, but CI only proves schema generation with fake responses. It does not prove scanner -> orchestrator -> persistence in one canonical run. |
| execution safety | Partial | `scripts/execution-safety-layer.py`, `scripts/trading-agency-phase1.py` | Safety validation is wired into the agency path, refreshes breaker state from canonical history, and persists runtime state. But there is no dedicated integration test proving scanner output actually survives safety validation in the canonical orchestrator path. |
| paper trader | Working | `scripts/phase1-paper-trader.py`, `tests/destructive/full-lifecycle-integration-test.py`, `tests/destructive/real-exit-integration-test.py`, `tests/destructive/polymarket-paper-flow-test.py` | The paper trader is the strongest proven subsystem. Isolated temp-workspace tests prove open -> close -> performance flows for Hyperliquid and Polymarket using the canonical trade log and position state. |
| trade schema | Partial | `models/trade_schema.py`, `scripts/performance-dashboard.py`, `scripts/live-readiness-validator.py` | The normalized schema does not carry `exchange`, `strategy`, `market_id`, `market_question`, or `token_id` as canonical top-level fields. Downstream readers recover exchange/type from `raw` or source records, so the claimed “same state model” is incomplete. |
| position state | Partial | `models/position_state.py`, `scripts/phase1-paper-trader.py`, `scripts/timeout-monitor.py` | `position-state.json` is authoritative for open positions, but it extends the normalized trade schema with exchange/strategy/Polymarket extras outside the canonical field list. Schema alignment is practical, not formally unified. |
| timeout monitor | Partial | `scripts/timeout-monitor.py`, `tests/timeout-monitor-polymarket-threshold-test.py` | It reads canonical open positions and supports Polymarket-specific thresholds, but it is non-authoritative by design and CI only proves threshold math, not a real orchestrated runtime monitor cycle. |
| exit monitor | Non-canonical | `scripts/exit-monitor.py`, `scripts/trading-agency-phase1.py` | The exit monitor explicitly says it is standalone/non-canonical and the orchestrator explicitly skips it because it can write proof artifacts without authoritative close persistence. |
| performance dashboard | Partial | `scripts/performance-dashboard.py`, `tests/performance-dashboard-canonical-test.py` | The dashboard reads canonical closed trade history in tests, but it depends on `raw.exchange`/extra fields because the normalized schema does not include exchange as a first-class canonical field. |
| Hyperliquid path | Partial | `scripts/phase1-signal-scanner.py`, `scripts/execution-safety-layer.py`, `scripts/phase1-paper-trader.py`, `tests/destructive/full-lifecycle-integration-test.py`, `tests/destructive/real-exit-integration-test.py` | Hyperliquid is the default path and best-covered path. Still, the full orchestrator path is not CI-proven and current runtime connectivity from this environment failed. |
| Polymarket path | Partial | `scripts/phase1-signal-scanner.py`, `scripts/execution-safety-layer.py`, `scripts/phase1-paper-trader.py`, `tests/destructive/polymarket-paper-flow-test.py`, `scripts/polymarket-executor.py` | Canonical paper wiring exists, but it is explicitly experimental, not orchestrator-tested in CI, and still coexists with a non-canonical executor/state model (`polymarket-trades.jsonl`, `polymarket-state.json`). |
| mixed mode | Partial | `config/runtime.py`, `scripts/phase1-paper-trader.py`, `tests/destructive/mixed-mode-integration-test.py`, `docs/SYSTEM_ARCHITECTURE.md` | Mixed mode is supported in config and can accumulate positions from both exchanges, but each cycle selects only one new candidate signal. The test proves this only by calling the trader twice, not by one agency cycle or simultaneous dual-entry handling. |
| CI workflow | Working / Limited proof | `.github/workflows/basic.yml`, `scripts/ci-safe-verification.sh` | CI reliably runs compile checks and isolated tests on every push/PR. It intentionally excludes live network checks and does not run the orchestrator end-to-end. |
| destructive/integration tests | Partial | `tests/destructive/*.py` | They prove canonical temp-workspace lifecycle behavior inside the paper trader, not full runtime orchestration. Scanner and safety are bypassed in the strongest lifecycle tests by injecting signals or monkeypatching price functions. |
| docs truthfulness | Partial | `README.md`, `SYSTEM_STATUS.md`, `docs/SYSTEM_ARCHITECTURE.md`, `docs/REPO_TRUTHFULNESS_AUDIT.md`, `scripts/live-readiness-validator.py`, `scripts/supervisor-governance.py` | Core docs are substantially more honest than typical trading repos, but they still overstate CI-backed architecture proof, keep active-tree live/future language, and understate schema/model drift plus non-canonical Polymarket state leftovers. |

## C. Canonical Flow Map

### Actual canonical operator entrypoint

1. **Operator entrypoint:** `scripts/trading-agency-phase1.py`.
   - This is the real top-level canonical runner.
   - `scripts/bootstrap-runtime-check.py` is *not* the repo’s operator entrypoint; it is invoked as the first stage by the agency script.

### Real canonical execution sequence

1. `scripts/trading-agency-phase1.py`
   - Detects mode using `config/runtime.py`.
   - Detects optional components.
   - Ensures workspace/status plumbing via `SystemHealthManager`.
   - Writes/updates:
     - `workspace/operator_control.json` (if missing)
     - `workspace/system_status.json`
     - `workspace/system_health.json`
     - `workspace/logs/operator-control-audit.json`

2. `scripts/bootstrap-runtime-check.py` (subprocess from orchestrator)
   - Verifies importable dependencies only.
   - Writes no canonical state.

3. `scripts/data-integrity-layer.py` (loaded as module; `run_pre_scan_gate`)
   - Checks mode-required source availability/completeness.
   - Writes/updates:
     - `workspace/logs/data-integrity-state.json`
     - `workspace/logs/source-reliability-metrics.json`
     - `workspace/logs/runtime-events.jsonl`
     - `workspace/logs/system-incidents.jsonl` when incidents are raised/resolved

4. `scripts/phase1-signal-scanner.py` (subprocess)
   - Scans Hyperliquid and/or Polymarket depending on mode.
   - Appends to:
     - `workspace/logs/phase1-signals.jsonl`
     - `workspace/logs/runtime-events.jsonl`
   - Writes:
     - `workspace/PHASE1_SIGNAL_REPORT.md`

5. `scripts/execution-safety-layer.py` (loaded as module by orchestrator)
   - Selects the next candidate from the latest signals using trader helpers.
   - Validates kill switch, signal freshness, position size, breaker state, exchange health, liquidity, spread.
   - Writes/updates:
     - `workspace/logs/execution-safety-state.json`
     - `workspace/logs/blocked-actions.jsonl` when a trade is blocked
     - `workspace/logs/incident-log.jsonl`
     - `workspace/logs/system-incidents.jsonl`

6. `scripts/phase1-paper-trader.py` (loaded as module by orchestrator)
   - Reads:
     - `workspace/logs/phase1-signals.jsonl`
     - `workspace/logs/position-state.json`
     - `workspace/logs/phase1-paper-trades.jsonl`
   - Plans exits first, then at most one new entry.
   - Persists authoritative state only after orchestrator approval:
     - appends `workspace/logs/phase1-paper-trades.jsonl`
     - rewrites `workspace/logs/position-state.json`
     - rewrites `workspace/logs/phase1-performance.json`
     - appends `workspace/logs/runtime-events.jsonl`

7. `scripts/timeout-monitor.py` (subprocess from orchestrator)
   - Reads authoritative open state from `workspace/logs/position-state.json`.
   - Appends:
     - `workspace/logs/timeout-history.jsonl`
     - `workspace/logs/runtime-events.jsonl`
   - Writes:
     - `workspace/TIMEOUT_MONITOR_REPORT.md`

8. `scripts/trading-agency-phase1.py` finalization
   - Generates and writes:
     - `workspace/logs/agency-phase1-report.json`
     - refreshed `workspace/system_status.json`

### Authoritative vs non-authoritative outputs

**Authoritative runtime state**
- `workspace/logs/phase1-paper-trades.jsonl`
- `workspace/logs/position-state.json`
- `workspace/logs/phase1-performance.json`

**Support / observability state**
- `workspace/logs/execution-safety-state.json`
- `workspace/logs/data-integrity-state.json`
- `workspace/logs/source-reliability-metrics.json`
- `workspace/logs/runtime-events.jsonl`
- `workspace/logs/system-incidents.jsonl`
- `workspace/logs/timeout-history.jsonl`
- `workspace/logs/agency-phase1-report.json`
- `workspace/system_status.json`
- `workspace/system_health.json`

**Explicitly non-canonical side paths**
- `scripts/polymarket-executor.py` -> `workspace/logs/polymarket-trades.jsonl`, `workspace/logs/polymarket-state.json`
- `scripts/exit-monitor.py` -> proof artifacts only
- `scripts/exit-safeguards.py`, `scripts/enhanced-exit-capture.py`, `scripts/position-exit-tracker.py` -> support tooling, not canonical trade-state mutation

## D. Gap Analysis: blockers to any claim that both Hyperliquid and Polymarket are fully integrated

1. **No orchestrator integration test exists.**
   - The canonical entrypoint is `scripts/trading-agency-phase1.py`.
   - CI never runs it in any mode.
   - Result: stage sequencing, agency reporting, and final state handoff are not formally proven.

2. **The strongest lifecycle tests bypass scanner and safety.**
   - Hyperliquid and Polymarket lifecycle tests inject signals directly into the paper trader.
   - Result: they prove persistence and exit behavior, not full source -> gate -> scan -> safety -> persist orchestration.

3. **Mixed mode is not truly “dual-path per cycle.”**
   - `select_trade_candidate()` returns a single best signal.
   - `build_execution_plan()` produces at most one new entry per cycle.
   - The mixed-mode test opens both exchanges by invoking the trader twice.
   - Result: mixed mode is accumulative, not fully side-by-side inside one canonical cycle.

4. **The canonical trade schema is incomplete for a multi-exchange system.**
   - `models/trade_schema.py` normalizes only a flat subset.
   - Exchange identity and Polymarket-specific fields are not first-class canonical fields.
   - Result: readers must depend on `raw` or out-of-band extras.

5. **Position state and trade schema are not the same formal model.**
   - `models/position_state.py` preserves exchange/strategy/Polymarket extras beyond the normalized schema.
   - Result: practical compatibility exists, but formal schema agreement does not.

6. **Dashboard/analytics layers recover exchange from raw records instead of canonical schema.**
   - Result: schema drift risk and misleading confidence in “one canonical state model.”

7. **Non-canonical Polymarket state still exists in active code.**
   - `scripts/polymarket-executor.py` writes `polymarket-trades.jsonl` and `polymarket-state.json`.
   - `scripts/live-readiness-validator.py` and `scripts/stability-monitor.py` still reference those files.
   - Result: the repo still contains an alternate Polymarket persistence model.

8. **Optional component detection is misleading.**
   - The orchestrator reports `polymarket_execution` as enabled when the helper file exists and the mode includes Polymarket.
   - The helper is not actually part of the canonical execution flow.
   - Result: runtime status output can overstate what is truly active.

9. **Monitor/support tooling is uneven across exchanges.**
   - Timeout monitor is mode-aware.
   - Several support utilities remain Hyperliquid-centric or conceptually outside the canonical flow.
   - Result: repository breadth exceeds the truly aligned canonical architecture.

10. **No committed runtime evidence exists in the repository workspace.**
   - The checked-in `workspace/` contains only defaults, not actual canonical logs.
   - Result: current truth rests on code/tests, not persisted runtime evidence.

11. **Current external connectivity was not verified successfully from this audit environment.**
   - Both Hyperliquid and Polymarket read-only connectivity checks failed here with proxy `403 Forbidden` tunneling errors.
   - This is environment-specific, but it means there is no fresh external runtime proof from this audit run.

12. **Active-tree future/live framing should not coexist with production-readiness language.**
   - `live-readiness-validator.py` and governance `LIVE` language are explicitly caveated, but still create avoidable ambiguity.

## E. Truthfulness findings vs README/docs claims

### Claims that are supported

- **Paper trading only**: supported.
- **No live trading implemented**: supported.
- **Hyperliquid is the default/best-supported path**: supported.
- **Polymarket is optional and experimental**: supported.
- **Timeout monitor is canonical; exit monitor is not**: supported.

### Claims that are only partially supported

1. **“canonical paper-trade orchestration across Hyperliquid and optional Polymarket modes”**
   - Mostly true in code wiring.
   - Not fully proven by tests because the orchestrator is not exercised end-to-end.

2. **“canonical state persistence … shared across supported modes”**
   - Mostly true for the paper trader and timeout monitor.
   - Not completely true repo-wide because active support scripts still reference `polymarket-state.json` / `polymarket-trades.jsonl`.

3. **“mixed mode … side-by-side paper evaluation across both exchanges”**
   - Only partially true.
   - One cycle selects one new entry; the mixed-mode test accumulates both exchanges over multiple trader invocations.

4. **“isolated end-to-end paper-trading lifecycle flows persist and clear canonical state correctly”**
   - True for isolated paper-trader flows.
   - Not true for the full orchestrator path.

5. **“test-backed architecture” / “CI-backed verification”**
   - True, but narrower than the wording suggests.
   - CI proves compileability and isolated module behavior, not full canonical runtime orchestration.

## F. Authoritative vs non-canonical inventory

### Authoritative / canonical
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
- canonical state files under `workspace/logs/phase1-*` and `position-state.json`

### Active but non-canonical / support only
- `scripts/polymarket-executor.py`
- `scripts/exit-monitor.py`
- `scripts/exit-safeguards.py`
- `scripts/enhanced-exit-capture.py`
- `scripts/position-exit-tracker.py`
- `scripts/stability-monitor.py`
- `scripts/live-readiness-validator.py`
- `scripts/supervisor-governance.py`
- `scripts/alpha-intelligence-layer.py`
- `scripts/portfolio-allocator.py`

### Historical / scaffold / archive
- `scripts/archive/*`
- `docs/archive/*`

## Final verdict paragraph

You **cannot** truthfully make a strong unqualified claim that “Hyperliquid and Polymarket are both fully integrated.” The most accurate short form is:

**Hyperliquid is the canonical paper-trading path and is the most integrated path in the repo; Polymarket is experimental and not yet fully integrated.**

That wording is truthful. The shorter sentence **“Hyperliquid is integrated; Polymarket is experimental and not yet fully integrated”** is directionally correct, but it should still be tightened to **“integrated in the paper-trading path”** to avoid overstating end-to-end proof.
