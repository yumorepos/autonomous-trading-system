# Autonomous Trading System

Version: 4.0  
Status: Research repository for paper-trading orchestration only

This repository documents and runs a **paper-trading-only** research system. The current canonical path is the **Hyperliquid Phase 1 flow**. **Polymarket is present only as disabled or incomplete exploratory work and is not part of the active execution path.**

## Current Truthful Status

- **Execution mode:** Paper trading only.
- **Canonical exchange path:** Hyperliquid only.
- **Polymarket:** Disabled/incomplete in the canonical flow.
- **Audience:** Portfolio/research review, not live deployment.
- **Production claim:** Removed intentionally; this repo should be treated as an experimental operating record.

## What the Active System Actually Does

The active orchestrator runs a fixed Phase 1 loop:

1. Data integrity gate validates source health.
2. Hyperliquid scanner collects funding-arbitrage signals.
3. Execution safety validates the next candidate entry.
4. The paper trader creates or closes **paper** positions.
5. Authoritative state is updated in `workspace/logs/`.
6. The orchestrator monitor stage runs the timeout monitor and records a truthful status snapshot.
7. The exit monitor remains a standalone script because it currently writes exit-proof artifacts without updating the authoritative close state.

The repository contains additional experimental scripts and historical reports, but they are **not** the source of truth unless explicitly referenced by the current canonical flow.

## Canonical Entry Point

Do **not** run `python main.py`; there is no active `main.py` orchestrator in this repository.

Use the actual Phase 1 orchestrator instead:

```bash
python3 scripts/trading-agency-phase1.py
```

Useful supporting commands:

```bash
python3 scripts/timeout-monitor.py
python3 scripts/exit-monitor.py
python3 scripts/supervisor-governance.py
python3 scripts/execution-safety-layer.py
```

Notes:
- `timeout-monitor.py` is the monitor script the orchestrator can safely invoke in the canonical loop.
- `exit-monitor.py` is still a standalone audit script; it is **not** run by the orchestrator because it can emit exit-proof artifacts without authoritative close persistence.

## Environment Setup

Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Repository Layout

```text
config/      Runtime path configuration.
docs/        Active documentation plus archived historical status reports.
models/      Canonical trade and position-state schemas.
scripts/     Operational scripts used by the paper-trading workflow.
tests/       Destructive/manual validation scripts.
utils/       JSON helpers and system health management.
workspace/   Runtime state, operator controls, logs, and generated artifacts.
```

## `workspace/` Structure

`workspace/` is the runtime area created and maintained by `config/runtime.py`. By default it is local to this repository, but it can be relocated with `OPENCLAW_WORKSPACE`.

Typical contents:

```text
workspace/
├── data/                  Generated datasets and intermediate files
├── logs/                  JSON/JSONL state, reports, and audit outputs
├── operator_control.json  Human override switches
└── system_status.json     Latest computed health/recovery status
```

Notes:

- `workspace/logs/position-state.json` is the authoritative open-position state file.
- `workspace/logs/phase1-paper-trades.jsonl` is the append-only paper trade log.
- Many reports are generated into `workspace/` during script execution.

## Reproducibility Notes

- Runtime directories are auto-created by `config/runtime.py`.
- Network access is required for live market data reads from Hyperliquid.
- Paper-trading behavior depends on current market conditions and the existing files in `workspace/logs/`.
- Historical “FINAL” or “VERIFIED” artifacts that overstated capability were moved to `docs/archive/`.
- Legacy alternate implementations and simulation-only scripts were moved to `scripts/archive/` so they are not confused with the active trading path.

## Documentation Map

- `docs/SYSTEM_ARCHITECTURE.md` — current operator-facing system summary.
- `SYSTEM_STATUS.md` — current scoped status summary.
- `docs/REPO_TRUTHFULNESS_AUDIT.md` — cleanup audit showing what was kept active vs archived.
- `docs/archive/` — historical documents retained for audit history but not authoritative status, including archived Polymarket integration claims and stale root-level reports.

## Disclaimer

This repository is for research, auditing, and portfolio presentation. It does **not** constitute financial advice, and it should not be described as a production trading system.
