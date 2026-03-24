# Operator Quickstart

Copy-paste-friendly commands for running the canonical **paper-trading** system locally.

## 1) Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 2) Bootstrap check

Verifies local runtime dependencies without requiring API success.

```bash
python3 scripts/bootstrap-runtime-check.py
```

## 3) Optional connectivity check

Read-only API reachability check for the currently enabled mode. This is useful for local operator confidence, but it is **not** a blocking CI requirement.

```bash
python3 scripts/runtime-connectivity-check.py
```

## 4) Run the canonical paper-trading entrypoint

### Hyperliquid only

```bash
OPENCLAW_TRADING_MODE=hyperliquid_only python3 scripts/trading-agency-phase1.py
```

### Polymarket only

```bash
OPENCLAW_TRADING_MODE=polymarket_only python3 scripts/trading-agency-phase1.py
```

### Mixed evaluation mode

```bash
OPENCLAW_TRADING_MODE=mixed python3 scripts/trading-agency-phase1.py
```

Use mixed mode only as a limited deterministic evaluation mode. It is not a dual-entry proof path.

## 5) Optional support scripts

```bash
python3 scripts/timeout-monitor.py
python3 scripts/execution-safety-layer.py
python3 scripts/performance-dashboard.py
python3 scripts/supervisor-governance.py
```

The support scripts above are useful for review and reporting, but they are not the canonical operator entrypoint.

## 6) Run the same safe verification suite as CI

```bash
./scripts/ci-safe-verification.sh
```

## 7) Inspect logs and canonical state

```bash
find workspace -maxdepth 2 -type f | sort
cat workspace/system_status.json
cat workspace/operator_control.json
```

Canonical files to know:
- `workspace/logs/phase1-signals.jsonl`
- `workspace/logs/phase1-paper-trades.jsonl`
- `workspace/logs/position-state.json`
- `workspace/logs/phase1-performance.json`

## Notes

- Hyperliquid is the default and best-supported paper-trading path.
- Polymarket is a canonical paper-trading path, but remains experimental overall; live trading is not implemented and real-money execution is not supported.
- Live trading is not implemented anywhere in this repository.
