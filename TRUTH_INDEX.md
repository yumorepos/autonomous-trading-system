# Truth Index

This is the shortest authoritative review path for the current repository state.

## Read these first

1. `README.md` — top-level scoped description of the repo.
2. `SYSTEM_STATUS.md` — current bounded status and limitations.
3. `docs/SYSTEM_ARCHITECTURE.md` — canonical execution path and state model.
4. `PROOF_MATRIX.md` — claim-to-test mapping.
5. `docs/POLYMARKET_EXECUTION_SCOPE.md` — exact current Polymarket boundary.

## Canonical runtime code

- `scripts/trading-agency-phase1.py`
- `scripts/bootstrap-runtime-check.py`
- `scripts/data-integrity-layer.py`
- `scripts/phase1-signal-scanner.py`
- `scripts/execution-safety-layer.py`
- `scripts/phase1-paper-trader.py`
- `scripts/timeout-monitor.py`

## Authoritative state files

- `workspace/logs/phase1-signals.jsonl`
- `workspace/logs/phase1-paper-trades.jsonl`
- `workspace/logs/position-state.json`
- `workspace/logs/phase1-performance.json`

## Current scope in one paragraph

The repository currently implements a canonical **paper-trading** runtime. Hyperliquid = canonical paper-trading path. Polymarket = canonical paper path, experimental overall, not live-integrated. Mixed mode = limited, asymmetric (one entry per cycle, Hyperliquid priority). CI = offline proof only, not live exchange validation.

## Non-canonical / historical surfaces

Do not treat the following as current capability statements:

- `docs/archive/`
- `scripts/archive/`
- `scripts/exit-monitor.py`
- `scripts/live-readiness-validator.py`
- support-only monitor/report scripts outside the canonical runtime path
