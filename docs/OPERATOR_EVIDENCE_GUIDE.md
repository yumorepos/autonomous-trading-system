# Operator Evidence Guide

## What an Operator Can Trust Today

### Offline proven
- Canonical operator entrypoint: `scripts/trading-agency-phase1.py`.
- Canonical default mode: `hyperliquid_only`.
- Canonical authoritative state: `workspace/logs/phase1-paper-trades.jsonl`, `workspace/logs/position-state.json`, and `workspace/logs/phase1-performance.json`.
- Cycle-level inspectability: `workspace/logs/agency-cycle-summary.json` and `workspace/AGENCY_CYCLE_SUMMARY.md`.

### Experimental or limited
- `polymarket_only` is offline-proven as a canonical paper path, but still experimental overall.
- `mixed` remains a limited evaluation mode, not the portfolio claim path.
- Live execution is not proven because it is not implemented.

## Fast Review Path

### 1) Run the CI-safe proof suite
```bash
./scripts/ci-safe-verification.sh
```

### 2) Run a longer operator soak if you want stronger offline confidence
```bash
python3 scripts/hyperliquid-offline-soak.py --cycles 12
```

### 3) Inspect the human-readable runtime artifacts
- `workspace/AGENCY_CYCLE_SUMMARY.md`
- `workspace/logs/agency-cycle-summary.json`
- `workspace/logs/agency-phase1-report.json`
- `workspace/TIMEOUT_MONITOR_REPORT.md`

## Artifact Meaning

| Artifact | Meaning | Truth boundary |
|---|---|---|
| `agency-cycle-summary.json` | Cycle-level structured summary of mode, result, selected signal, entry/exit outcome, rejection reason, and authoritative files written. | Canonical inspectability aid; not a replacement for underlying trade/state files. |
| `AGENCY_CYCLE_SUMMARY.md` | Human-readable version of the same cycle summary. | Readability layer only. |
| `agency-phase1-report.json` | Full cycle report with per-stage reasons plus `runtime_summary`. | Main machine-readable cycle report. |
| `phase1-paper-trades.jsonl` | Append-only canonical paper trade history. | Authoritative trade log. |
| `position-state.json` | Current open positions only. | Authoritative open-position state. |
| `phase1-performance.json` | Closed-trade performance summary. | Derived authoritative summary for closed paper trades. |

## Evidence Mapping

- End-to-end Hyperliquid proof: `tests/destructive/trading-agency-hyperliquid-test.py`
- Repeat-cycle deterministic stability: `tests/destructive/trading-agency-hyperliquid-repeat-cycle-test.py`
- Negative-path truthfulness: `tests/destructive/trading-agency-negative-path-test.py`
- Canonical Polymarket paper path (experimental overall): `tests/destructive/trading-agency-polymarket-test.py`
- Mixed-mode limited handling: `tests/destructive/trading-agency-mixed-test.py`

## What This Phase Does Not Claim

- No production-readiness claim.
- No live-trading claim.
- No claim that mixed mode is fully mature.
- No claim that Polymarket is anything more than a canonical paper path with experimental overall status.
