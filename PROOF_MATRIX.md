# Proof Matrix

This repository is a paper-trading research system. The table below maps each material claim to the exact test or script that currently supports it.

## Proven Surface

| Claim | Status | Evidence | Notes |
|---|---|---|---|
| Hyperliquid canonical paper-trading path runs end-to-end offline through the agency entrypoint. | Proven | `python3 tests/destructive/trading-agency-hyperliquid-test.py` | Covers bootstrap, data integrity, scan, safety, paper entry, authoritative persistence, exit, monitor stage. |
| Canonical runtime now emits cycle-level summaries that operators can inspect without reading raw JSONL. | Proven | `python3 tests/destructive/trading-agency-hyperliquid-test.py` and `python3 tests/destructive/trading-agency-negative-path-test.py` | Verifies `workspace/AGENCY_CYCLE_SUMMARY.md`, `workspace/logs/agency-cycle-summary.json`, and `agency-phase1-report.json.runtime_summary`. |
| Canonical Hyperliquid runtime remains deterministic across repeated isolated offline cycles. | Proven in offline repeat-cycle scope | `python3 tests/destructive/trading-agency-hyperliquid-repeat-cycle-test.py` | Verifies stable cycle summaries, stable position-state schema, no duplicate open-position leakage, and monotonic performance updates over multiple cycles. |
| Hyperliquid negative-path entry blocking works for stale signals, duplicate entries, breaker halts, and capacity limits. | Proven | `python3 tests/destructive/trading-agency-negative-path-test.py` | Also verifies blocked-cycle summaries remain truthful. |
| Polymarket paper runtime can run offline through the agency entrypoint and persist through the same canonical trade/state files. | Proven at the paper-trading level | `python3 tests/destructive/trading-agency-polymarket-test.py`, `python3 tests/destructive/polymarket-paper-flow-test.py`, `python3 tests/trade-schema-contract-test.py`, and `python3 tests/polymarket-metadata-truth-test.py` | Canonical paper path; experimental overall; does not prove live readiness. |
| Mixed mode exists as a limited evaluation path with deterministic single-entry selection, Hyperliquid preferred for the one entry admitted per cycle, and advisory-only secondary-source health. | Limited | `python3 tests/destructive/trading-agency-mixed-test.py`, `python3 tests/destructive/mixed-mode-integration-test.py`, and `python3 tests/mixed-mode-policy-test.py` | Not presented as a fully proven dual-entry runtime. |
| Canonical position/trade schemas remain normalized and readable by analytics/reporting code. | Proven | `python3 tests/trade-schema-contract-test.py`, `python3 tests/paper-mode-schema-test.py`, `python3 tests/performance-dashboard-canonical-test.py` | Covers schema normalization and downstream reader compatibility. |
| Timeout monitor still reads canonical state safely in paper mode. | Proven | `python3 tests/timeout-monitor-polymarket-threshold-test.py` and runtime execution inside agency destructive tests | Monitoring only; not authoritative close persistence. |
| CI-safe verification remains deterministic and network-nonblocking. | Proven | `./scripts/ci-safe-verification.sh` | Offline fixtures patch network requests during destructive agency tests. |

## Operator-Run Validation

| Validation command | Purpose | CI default |
|---|---|---|
| `./scripts/ci-safe-verification.sh` | Fast deterministic regression and canonical offline proof suite. | Yes |
| `python3 scripts/hyperliquid-offline-soak.py --cycles 12` | Longer repeat-cycle Hyperliquid soak validation in an isolated offline workspace. | No |

## Explicitly Unproven or Limited

| Area | Status | Why |
|---|---|---|
| Live Hyperliquid trading | Unproven / not implemented | Repository remains paper-trading only. |
| Live Polymarket trading | Unproven / not implemented | Current evidence is canonical paper-trading only. |
| Mixed-mode simultaneous dual-entry semantics | Limited | Existing tests confirm constraints and safe handling, not full operator-grade dual execution. |
| Real-money execution | Unsupported | No truthful evidence exists because the capability is not implemented. |

## Review Order

For a quick technical review, read in this order:
1. `README.md`
2. `TRUTH_INDEX.md`
3. `SYSTEM_STATUS.md`
4. `docs/RUNTIME_OBSERVABILITY.md`
5. `docs/OPERATOR_EVIDENCE_GUIDE.md`
6. `PROOF_MATRIX.md`
