# System Status

**Last Updated:** 2026-03-21 UTC  
**Verdict:** Paper-trading research system with one canonical Hyperliquid path and experimental Polymarket support

---

## At-a-Glance Status

| Area | Current status |
|---|---|
| Core capability | Phase 1 paper-trading execution |
| Canonical entrypoint | `scripts/trading-agency-phase1.py` |
| Canonical default | `hyperliquid_only` |
| Experimental modes | `polymarket_only`, `mixed` |
| Live trading | **Not implemented** |
| Real-money execution | **Not supported** |
| CI | Safe verification runs on every push and pull request |
| Truthfulness | Improved, but still bounded by what code/tests actually prove |

---

## Current Capabilities

- canonical Phase 1 paper-trading execution through `scripts/trading-agency-phase1.py`
- mode-aware scanning and data-integrity validation
- normalized paper-trade persistence across Hyperliquid and experimental Polymarket paper records
- authoritative open-position state in one canonical file
- monitoring and support reporting for paper-trading operations
- isolated regression and lifecycle verification tests

## Current Limitations

- live trading is not implemented
- no production deployment claim is justified
- external API reachability is environment-dependent and not guaranteed by CI
- Polymarket support remains experimental and not fully proven end-to-end
- mixed mode remains limited and should not be presented as a fully proven side-by-side runtime
- some retained support scripts model future or helper workflows and are **not** canonical execution

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

- `scripts/polymarket-executor.py` — helper/scaffold only
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
- canonical dashboard and timeout-monitor reader behavior

CI intentionally avoids making flaky network access a merge blocker and does **not** prove the full orchestrator end-to-end.

## What Remains Unverified in CI

- current external API reachability from the runner
- full runtime execution of `scripts/trading-agency-phase1.py`
- long-duration forward performance characteristics
- any live execution behavior, because none is implemented

---

## Future Work

Future work, if pursued, should remain clearly separated from the current paper-only claim:
- accumulate more canonical paper-trading runtime evidence for Polymarket
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
