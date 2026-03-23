# System Status

**Last Updated:** 2026-03-22 UTC  
**Verdict:** Paper-trading research system with canonical Hyperliquid and Polymarket paper paths, Polymarket experimental overall, and limited mixed-mode semantics

---

## At-a-Glance Status

| Area | Current status |
|---|---|
| Core capability | Phase 1 paper-trading execution |
| Canonical entrypoint | `scripts/trading-agency-phase1.py` |
| Canonical default | `hyperliquid_only` |
| Limited modes | `mixed` |
| Live trading | **Not implemented** |
| Real-money execution | **Not supported** |
| CI | Safe verification runs on every push and pull request |
| Truthfulness | Strong and explicitly bounded by current offline evidence |

---

## Current Capabilities

- canonical Phase 1 paper-trading execution through `scripts/trading-agency-phase1.py`
- mode-aware scanning and data-integrity validation
- normalized paper-trade persistence across Hyperliquid and Polymarket paper records
- authoritative open-position state in one canonical file
- monitoring and support reporting for paper-trading operations
- cycle-level operator summaries in JSON and Markdown for the canonical path
- deterministic repeat-cycle offline validation for canonical Hyperliquid execution
- isolated regression and lifecycle verification tests

## Current Limitations

- live trading is not implemented
- no production deployment claim is justified
- external API reachability is environment-dependent and not guaranteed by CI
- Polymarket now uses the same canonical paper-trading runtime stages, persistence, and monitors as Hyperliquid, but remains experimental overall
- mixed mode remains limited and should not be presented as a fully proven side-by-side runtime
- some retained support scripts model future workflows and are **not** canonical execution

---

## Canonical vs Non-Canonical

### Canonical

- `scripts/trading-agency-phase1.py`
- `scripts/bootstrap-runtime-check.py`
- `scripts/data-integrity-layer.py`
- `scripts/phase1-signal-scanner.py`
- `scripts/execution-safety-layer.py`
- `scripts/phase1-paper-trader.py`
- `scripts/timeout-monitor.py`
- `workspace/logs/phase1-paper-trades.jsonl`
- `workspace/logs/position-state.json`

### Non-Canonical / Support Only

- `scripts/exit-monitor.py` — proof/audit only
- `scripts/live-readiness-validator.py` — future-scope research model only
- `scripts/exit-safeguards.py` — support utility; not part of the canonical loop
- `scripts/stability-monitor.py` — support-only observability
- `docs/archive/` and `scripts/archive/` — historical context only

---

## What CI Proves

The required CI workflow verifies:
- bootstrap/runtime dependency checking
- Python compile/syntax validation
- script-style regression tests
- isolated lifecycle integrity for canonical paper-trader flows
- offline agency-entrypoint coverage for Hyperliquid, Polymarket, mixed-mode limitation, and negative-path reliability checks
- deterministic repeat-cycle stability for the canonical Hyperliquid path
- canonical dashboard and timeout-monitor reader behavior

CI intentionally avoids making flaky network access a merge blocker while now proving the agency entrypoint offline for success-path and negative-path execution.

## What Remains Unverified in CI

- current external API reachability from the runner
- live external API reachability during `scripts/trading-agency-phase1.py` execution
- long-duration forward performance characteristics beyond deterministic offline soak scaffolding
- any live execution behavior, because none is implemented

---

## Proof Index

Use these files to review what is actually proven:

- `PROOF_MATRIX.md` — maps major claims to exact tests/scripts
- `docs/OPERATOR_EVIDENCE_GUIDE.md` — concise operator review sequence
- `docs/RUNTIME_OBSERVABILITY.md` — explains the cycle summary artifacts
- `scripts/hyperliquid-offline-soak.py` — explicit operator-run repeat-cycle validation

---

## Future Work

Future work, if pursued, should remain clearly separated from the current paper-only claim:
- continue improving proof coverage without overstating live readiness
- decide whether mixed mode should remain limited or be upgraded with explicit multi-entry semantics
- continue improving operator reporting and paper-trading analytics

---

## Reviewer Guidance

Start here for the current truth:
- `README.md`
- `docs/OPERATOR_QUICKSTART.md`
- `docs/SYSTEM_ARCHITECTURE.md`
- `docs/REPO_TRUTHFULNESS_AUDIT.md`
- `SYSTEM_STATUS.md`
