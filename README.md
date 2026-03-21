# Autonomous Trading System

Version: 5.0  
Status: Research repository for orchestrated paper trading only

This repository runs a **paper-trading-only** research system with one canonical architecture and three truthful runtime modes:

- `hyperliquid_only` — default canonical mode
- `polymarket_only` — optional experimental paper mode
- `mixed` — optional side-by-side paper evaluation mode

**Hyperliquid remains the default path. Polymarket is now wired into the same canonical paper-trading flow, but it is still optional, paper-only, and experimental. No live trading path is supported.**

## Current Truthful Status

- **Execution mode:** paper trading only
- **Default exchange path:** Hyperliquid
- **Optional exchange path:** Polymarket paper trading
- **Live trading:** unsupported
- **Audience:** research, audit, portfolio review

## Canonical Architecture

The active orchestrator runs a fixed Phase 1 loop:

1. Bootstrap/runtime dependency check
2. Data integrity gate validates enabled sources
3. Scanner generates canonical paper-trading signals for the selected mode
4. Execution safety validates the next candidate entry
5. Paper trader plans and persists entry/exit records
6. Authoritative state is updated in `workspace/logs/`
7. Timeout monitor reads canonical open positions and writes monitoring artifacts
8. Supervisor/analytics scripts remain optional support tools, not the authoritative execution path

## Canonical Entry Point

Run the orchestrator with the desired paper-trading mode:

```bash
python3 scripts/bootstrap-runtime-check.py
OPENCLAW_TRADING_MODE=hyperliquid_only python3 scripts/trading-agency-phase1.py
OPENCLAW_TRADING_MODE=polymarket_only python3 scripts/trading-agency-phase1.py
OPENCLAW_TRADING_MODE=mixed python3 scripts/trading-agency-phase1.py
```

Useful supporting commands:

```bash
python3 scripts/timeout-monitor.py
python3 scripts/execution-safety-layer.py
python3 scripts/performance-dashboard.py
python3 scripts/supervisor-governance.py
```

Notes:
- `timeout-monitor.py` is the only monitor script run by the orchestrator.
- `exit-monitor.py` is a standalone proof/audit script and is not part of authoritative close-state persistence.
- `polymarket-executor.py` remains a standalone helper/non-canonical scaffold; the canonical Polymarket paper path runs through the same orchestrator + trader + canonical persistence flow as Hyperliquid.

## Environment Setup

Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Before running the orchestrator, verify runtime dependencies:

```bash
python3 scripts/bootstrap-runtime-check.py
python3 scripts/runtime-connectivity-check.py
```

If you want a fully isolated environment and your machine has internet access to PyPI:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python scripts/bootstrap-runtime-check.py
python scripts/runtime-connectivity-check.py
```

`runtime-connectivity-check.py` performs **read-only** API validation for the Hyperliquid `metaAndAssetCtxs` endpoint and the Polymarket Gamma `markets` endpoint, with explicit timeout handling and schema checks. It never places trades and only verifies paper-trading data reachability.

## Repository Layout

```text
config/      Runtime path configuration and mode selection helpers.
docs/        Active documentation plus historical/audit materials.
models/      Canonical trade and position-state schemas.
scripts/     Operational scripts for paper-trading workflow and support tools.
tests/       Temp-workspace and schema/bootstrap verification scripts.
utils/       JSON helpers and system health management.
workspace/   Runtime state, operator controls, logs, and generated artifacts.
```

## `workspace/` Structure

`workspace/` is created and maintained by `config/runtime.py`. By default it is local to this repository, but it can be relocated with `OPENCLAW_WORKSPACE`.

Typical contents:

```text
workspace/
├── data/                  Generated datasets and intermediate files
├── logs/                  JSON/JSONL state, reports, and audit outputs
├── operator_control.json  Human override switches
└── system_status.json     Latest computed health/recovery status
```

Canonical state files:

- `workspace/logs/phase1-signals.jsonl` — append-only scanner output
- `workspace/logs/phase1-paper-trades.jsonl` — append-only canonical paper trade log for all exchanges
- `workspace/logs/position-state.json` — authoritative open-position state only
- `workspace/logs/phase1-performance.json` — normalized closed-trade performance summary

## Runtime Modes

### `hyperliquid_only`
- default mode
- scans Hyperliquid only
- validates Hyperliquid only in data-integrity scope
- canonical baseline mode for reviewers

### `polymarket_only`
- optional mode
- scans Polymarket only
- paper-trading only
- experimental until more runtime evidence exists

### `mixed`
- optional evaluation mode
- scans both exchanges
- still paper-trading only
- intended for side-by-side research, not live capital allocation

## Truthfulness Boundaries

- Hyperliquid and Polymarket are supported for **paper trading only**.
- Polymarket support is **optional and experimental**.
- Real exchange execution is **not implemented**.
- Supporting reports/dashboards should not be read as proof of live readiness.
- Historical reports under `docs/archive/` remain for provenance, not current operational truth.

## Disclaimer

This repository is for research, auditing, and portfolio presentation. It is **not** a production trading system, does **not** provide live execution support, and does **not** constitute financial advice.
