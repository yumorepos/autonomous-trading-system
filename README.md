# Autonomous Trading System

Version: 5.2  
Status: CI-backed research repository for **paper trading only**

## Summary

This repository implements a **Phase 1 paper-trading execution path** for truthful research and portfolio review.

Current repo truth:
- **canonical paper-trading path:** Hyperliquid via `scripts/trading-agency-phase1.py`
- **canonical paper-trading path:** Polymarket in `polymarket_only`, using the same shared architecture and deterministic offline agency proof
- **limited evaluation mode:** `mixed`
- **live trading:** not implemented
- **real-money execution:** not supported

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
3. signal scanning for the enabled exchange set
4. execution-safety validation
5. paper-trade planning and persistence
6. canonical state update in `workspace/logs/`
7. timeout monitoring and operator visibility

`scripts/bootstrap-runtime-check.py` is the first stage inside that flow. It is not the top-level operator entrypoint.

## Supported Modes

| Mode | Purpose | Truthful status |
|---|---|---|
| `hyperliquid_only` | Default paper-trading run | canonical and best-supported |
| `polymarket_only` | Polymarket paper-trading run | canonical paper-trading path with offline proof |
| `mixed` | Shared-state evaluation across both exchanges | limited experimental mode; not the canonical proof path |

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
- `workspace/logs/agency-cycle-summary.json` — structured per-cycle operator summary
- `workspace/AGENCY_CYCLE_SUMMARY.md` — human-readable per-cycle summary

Non-canonical/support-only artifacts:
- `scripts/exit-monitor.py` — proof/audit generator only; not authoritative close persistence
- `scripts/live-readiness-validator.py` — future-scope research model only
- `docs/archive/` and `scripts/archive/` — historical context only

## What CI Proves

The safe verification suite proves:
- bootstrap dependency checks behave correctly
- compile/syntax validation succeeds for active Python code
- mode-aware data-integrity gating respects the selected runtime mode
- Hyperliquid and Polymarket paper signal schemas normalize into the expected structure
- isolated paper-trader lifecycle flows persist and clear canonical state correctly
- offline agency-entrypoint proofs now cover Hyperliquid success, Polymarket success, mixed-mode limitation, and orchestrator negative-path blocking
- deterministic repeat-cycle Hyperliquid validation confirms stable offline trade/performance/state behavior across multiple cycles
- the performance dashboard can read canonical mixed-mode trade history
- timeout monitoring exposes Polymarket-specific paper thresholds

Run the same suite locally with:

```bash
./scripts/ci-safe-verification.sh
```

## What CI Does Not Prove

- the agency entrypoint in `scripts/trading-agency-phase1.py` is exercised offline in CI for Hyperliquid, Polymarket, mixed-mode limitation confirmation, and orchestrator negative-path blocking
- runtime connectivity to external APIs is not a blocking CI guarantee
- no live trading support exists
- no real-money execution path exists
- `mixed` is not proven as a simultaneous dual-entry runtime; it remains a limited deterministic evaluation mode
- Polymarket is canonical at the paper-trading level but does not imply live readiness

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
- **Canonical exchange path:** Hyperliquid
- **Experimental exchange path:** Polymarket paper trading with deterministic offline agency-level proof and canonical persistence compatibility
- **Mixed mode:** limited experimental evaluation mode
- **Live trading:** not implemented
- **Production deployment claim:** unsupported
- **Audience:** research, audit, portfolio review

## Disclaimer

This repository is for research, auditing, and portfolio presentation. It is **not** a production trading system, does **not** provide live execution support, and does **not** constitute financial advice.
