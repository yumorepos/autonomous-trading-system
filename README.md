# Autonomous Trading System

Version: 5.2  
Status: CI-backed research repository for **paper trading only**

## Summary

This repository implements a **Phase 1 paper-trading execution path** for truthful research and portfolio review.

Current repo truth:
- **Hyperliquid:** canonical paper-trading path
- **Polymarket:** canonical paper path, experimental overall, not live-integrated
- **Mixed mode:** limited, asymmetric (one entry per cycle, Hyperliquid priority)
- **CI:** offline proof only, not live exchange validation
- **Live trading:** not implemented
- **Real-money execution:** not supported

Phase 4 adds:
- cycle-level runtime summaries for the canonical path
- deterministic repeat-cycle Hyperliquid validation in CI-safe verification
- operator-facing proof packaging that maps claims to exact tests/scripts

## What the Repository Actually Does

The real canonical operator entrypoint is:

- `scripts/trading-agency-phase1.py`

That script runs this Phase 1 paper-trading flow:

1. bootstrap/runtime dependency verification
2. mode-aware data-integrity validation
3. signal scanning for the enabled exchange set, with signal-level integrity validation before persistence
4. execution-safety validation
5. paper-trade planning and persistence
6. canonical state update in `workspace/logs/`
7. timeout monitoring and operator visibility

`scripts/bootstrap-runtime-check.py` is the first stage inside that flow. It is not the top-level operator entrypoint.

## Supported Modes

| Mode | Purpose | Truthful status |
|---|---|---|
| `hyperliquid_only` | Default paper-trading run | Hyperliquid = canonical paper-trading path |
| `polymarket_only` | Polymarket paper-trading run | Polymarket = canonical paper path, experimental overall, not live-integrated |
| `mixed` | Shared-state evaluation across both exchanges | Mixed mode = limited, asymmetric (one entry per cycle, Hyperliquid priority) |

## Canonical Architecture

Canonical execution files:
- `scripts/trading-agency-phase1.py` — canonical operator entrypoint
- `scripts/bootstrap-runtime-check.py` — stage 1 bootstrap check
- `scripts/data-integrity-layer.py`
- `scripts/phase1-signal-scanner.py`
- `scripts/execution-safety-layer.py`
- `scripts/phase1-paper-trader.py`
- `scripts/timeout-monitor.py`

Canonical state files:
- `workspace/logs/phase1-signals.jsonl` — append-only paper signals
- `workspace/logs/phase1-paper-trades.jsonl` — append-only canonical paper trade history
- `workspace/logs/position-state.json` — authoritative open-position state only
- `workspace/logs/phase1-performance.json` — normalized closed-trade performance summary
- `workspace/logs/paper-account.json` — explicit paper-account state derived from closed canonical trades
- `workspace/logs/agency-cycle-summary.json` — structured per-cycle operator summary
- `workspace/AGENCY_CYCLE_SUMMARY.md` — human-readable per-cycle summary
- `workspace/OPERATOR_EVIDENCE_DASHBOARD.md` — one-file operator evidence summary with truth disclaimers

Non-canonical/support-only artifacts:
- `scripts/exit-monitor.py` — proof/audit generator only; not authoritative close persistence
- `scripts/live-readiness-validator.py` — future-scope research model only
- `scripts/support/` — support-only analytics/monitor/report scripts outside canonical execution
- `docs/archive/` and `scripts/archive/` — historical context only

## What CI Proves

The safe verification suite proves, offline only:
- bootstrap dependency checks behave correctly
- compile/syntax validation succeeds for active Python code
- mode-aware data-integrity gating respects the selected runtime mode
- generated paper signals are validated by the data-integrity layer before they are appended to canonical signal history
- Hyperliquid and Polymarket paper signal schemas normalize into the expected structure
- isolated paper-trader lifecycle flows persist and clear canonical state correctly
- canonical position-state recovery can rebuild open positions from append-only trade history after malformed or drifted state
- offline agency-entrypoint proofs now cover Hyperliquid success, Polymarket success, mixed-mode limitation, and orchestrator negative-path blocking
- deterministic repeat-cycle Hyperliquid validation confirms stable offline trade/performance/state behavior across multiple cycles
- the performance dashboard can read canonical mixed-mode trade history
- timeout monitoring exposes Polymarket-specific paper thresholds
- paper-account balance/peak state is synchronized from append-only canonical trade history
- operator-control negative paths (invalid values and HALT_NEW_TRADES override) are enforced in canonical loop

Machine-checkable truth claim source:
- `truth/claims.yaml` (JSON-compatible YAML) is validated by `tests/repo-truth-guard-test.py` and enforced in CI.

Run the same suite locally with:

```bash
./scripts/ci-safe-verification.sh
```

## What CI Does Not Prove

- live API reachability during `scripts/trading-agency-phase1.py` execution is not proven by CI
- runtime connectivity to external APIs is not a blocking CI guarantee
- CI is offline proof only, not live exchange validation
- no live trading support exists
- no real-money execution path exists
- `mixed` is not proven as a simultaneous dual-entry runtime; it remains a limited deterministic evaluation mode with one new entry per cycle and Hyperliquid-primary selection semantics
- Polymarket is canonical at the paper-trading level, experimental overall, and does not imply live integration or production capability

## Operator Quickstart

### 1) Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 2) Bootstrap check

```bash
python3 scripts/bootstrap-runtime-check.py
```

### 3) Optional read-only connectivity check

```bash
python3 scripts/runtime-connectivity-check.py
```

This performs read-only API validation only. It never places trades and is **not** part of blocking CI.

### 4) Run the paper-trading entrypoint

```bash
OPENCLAW_TRADING_MODE=hyperliquid_only python3 scripts/trading-agency-phase1.py
OPENCLAW_TRADING_MODE=polymarket_only python3 scripts/trading-agency-phase1.py
OPENCLAW_TRADING_MODE=mixed python3 scripts/trading-agency-phase1.py
```

### 5) Inspect outputs

```bash
find workspace -maxdepth 2 -type f | sort
```

Key output locations:
- `workspace/logs/` — runtime JSON/JSONL logs and reports
- `workspace/operator_control.json` — operator overrides
- `workspace/system_status.json` — latest computed health/recovery status
- `workspace/logs/agency-cycle-summary.json` — structured cycle verdict
- `workspace/AGENCY_CYCLE_SUMMARY.md` — human-readable cycle verdict

For a copy-paste operator guide, see `docs/OPERATOR_QUICKSTART.md`.

## Proof Surface

Start here if you need evidence instead of feature descriptions:

- `TRUTH_INDEX.md` — authoritative reviewer index for canonical code, state, tests, and non-canonical surfaces
- `PROOF_MATRIX.md` — claim-to-test mapping
- `docs/OPERATOR_EVIDENCE_GUIDE.md` — concise operator review path
- `docs/RUNTIME_OBSERVABILITY.md` — runtime summary artifact guide
- `SYSTEM_STATUS.md` — current truthful status and limitations

Longer offline validation outside default CI:

```bash
python3 scripts/hyperliquid-offline-soak.py --cycles 12
```

## Repository Layout

```text
config/      Runtime path configuration and mode selection helpers.
docs/        Active documentation plus historical/audit materials.
models/      Canonical trade and position-state schemas.
scripts/     Canonical paper-trading workflow plus support tools.
tests/       Safe regression and isolated lifecycle verification scripts.
utils/       JSON helpers and system health management.
workspace/   Runtime state, operator controls, logs, and generated artifacts.
```

## Current Truthful Status

- **Execution mode:** paper trading only
- **Hyperliquid:** canonical paper-trading path
- **Polymarket:** canonical paper path, experimental overall, not live-integrated
- **Mixed mode:** limited, asymmetric (one entry per cycle, Hyperliquid priority)
- **CI:** offline proof only, not live exchange validation
- **Live trading:** not implemented
- **Production deployment claim:** unsupported
- **Audience:** research, audit, portfolio review

## Historical Material

- `docs/archive/` and `scripts/archive/` are historical only.
- `TRUTH_INDEX.md` lists the current authoritative review path.
- `docs/POLYMARKET_EXECUTION_SCOPE.md` explains the present paper-only Polymarket boundary.

## Disclaimer

This repository is for research, auditing, and portfolio presentation. It is **not** a production trading system, does **not** provide live execution support, and does **not** constitute financial advice.
