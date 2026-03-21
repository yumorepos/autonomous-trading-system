# Autonomous Trading System

Version: 5.1  
Status: CI-backed research repository for orchestrated **paper trading only**

## Portfolio Summary

This project is a **multi-exchange paper-trading orchestration system** built for truthful research and portfolio review.

It demonstrates:
- canonical paper-trade orchestration across **Hyperliquid** and optional **Polymarket** modes
- **canonical state persistence** with append-only trade history plus authoritative open-position state
- **mode-aware validation** so each runtime path checks only the exchanges it actually uses
- **truthful failure handling** that blocks or downgrades runs when required data is unhealthy
- **observability and monitoring** through runtime events, status files, dashboards, and monitors
- a **test-backed architecture** with CI running safe verification on every push and pull request

**No live trading is implemented. No real order execution path is supported.**

## What the System Does

The repository runs a canonical Phase 1 paper-trading loop:

1. bootstrap/runtime dependency verification
2. mode-aware data-integrity validation
3. signal scanning for the enabled exchange set
4. execution-safety validation
5. paper-trade planning and persistence
6. canonical state update in `workspace/logs/`
7. timeout monitoring and supporting operator visibility

## Supported Modes

| Mode | Purpose | Truthful status |
|---|---|---|
| `hyperliquid_only` | Default baseline paper-trading path | best-supported and canonical |
| `polymarket_only` | Optional Polymarket-only paper evaluation | experimental |
| `mixed` | Side-by-side paper evaluation across both exchanges | experimental evaluation mode |

## Canonical Architecture

The active canonical path is:

- `scripts/bootstrap-runtime-check.py`
- `scripts/trading-agency-phase1.py`
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

Non-canonical but retained artifacts:

- `scripts/polymarket-executor.py` — helper/scaffold only
- `scripts/exit-monitor.py` — proof/audit generator only
- `docs/archive/` and `scripts/archive/` — historical context only

## Why This Repo Is Trustworthy

This project is designed to be convincing **without pretending to do more than it does**:

- paper-only scope is explicit throughout the codebase and docs
- CI runs a **safe verification suite** on every push and pull request
- regression tests use isolated temp workspaces and mocked network calls where appropriate
- canonical persistence is shared across supported modes instead of branching into separate state models
- status docs explicitly separate **proven**, **unproven**, **canonical**, and **future work**

## What Is Proven by Tests

The current safe verification suite proves:

- bootstrap dependency checks behave correctly
- compile/syntax validation succeeds for active Python code
- mode-aware data-integrity gating respects the selected runtime mode
- Hyperliquid and Polymarket paper signal schemas normalize into the expected structure
- canonical mixed-mode trade history can be read by the performance dashboard
- timeout monitoring exposes Polymarket-specific paper thresholds
- isolated end-to-end paper-trading lifecycle flows persist and clear canonical state correctly

Run the same suite locally with:

```bash
./scripts/ci-safe-verification.sh
```

## What Is Not Yet Proven

- no live trading support exists
- no real-money execution path exists
- runtime connectivity to external APIs is **not** a blocking CI guarantee
- Polymarket remains optional and experimental until more runtime evidence exists
- archived reports may discuss future/live concepts, but they are not the current repository truth

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

### 4) Run each paper-trading mode

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

For a copy-paste operator guide, see `docs/OPERATOR_QUICKSTART.md`.

## Local Verification

```bash
./scripts/ci-safe-verification.sh
```

The workflow used in GitHub Actions intentionally excludes flaky network-dependent checks from required CI.

## Repository Layout

```text
config/      Runtime path configuration and mode selection helpers.
docs/        Active documentation plus historical/audit materials.
models/      Canonical trade and position-state schemas.
scripts/     Operational scripts for paper-trading workflow and support tools.
tests/       Safe regression and isolated lifecycle verification scripts.
utils/       JSON helpers and system health management.
workspace/   Runtime state, operator controls, logs, and generated artifacts.
```

## Current Truthful Status

- **Execution mode:** paper trading only
- **Default exchange path:** Hyperliquid
- **Optional exchange path:** Polymarket paper trading
- **Live trading:** not implemented
- **Production deployment claim:** unsupported
- **Audience:** research, audit, portfolio review

## Disclaimer

This repository is for research, auditing, and portfolio presentation. It is **not** a production trading system, does **not** provide live execution support, and does **not** constitute financial advice.
