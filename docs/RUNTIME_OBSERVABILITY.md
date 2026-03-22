# Runtime Observability

## Goal

Phase 4 improves inspectability of the canonical runtime without redesigning the runtime itself.

## Canonical Summary Artifacts

Each agency cycle now writes:

- `workspace/logs/agency-cycle-summary.json`
- `workspace/AGENCY_CYCLE_SUMMARY.md`
- `workspace/logs/agency-phase1-report.json` with `runtime_summary`

## What the Cycle Summary Shows

The cycle summary is intentionally small and operator-focused:

- mode
- cycle result
- selected signal
- entry outcome (`executed`, `blocked`, `skipped`, or `not_attempted`)
- exit outcome (`executed`, `checked_none_triggered`, `no_open_positions`, etc.)
- rejection reason when applicable
- authoritative files written for that cycle
- stage-by-stage status snapshot

## Recommended Inspection Order

1. Open `workspace/AGENCY_CYCLE_SUMMARY.md` for a fast human-readable cycle verdict.
2. Open `workspace/logs/agency-cycle-summary.json` for exact structured values.
3. Open `workspace/logs/agency-phase1-report.json` for full stage reasons and monitor details.
4. Only then drop to JSONL files if you need event-level or trade-level detail.

## Why This Is Truthful

- The summary is derived from the same stage results used to produce `agency-phase1-report.json`.
- The summary does not claim live fills or real orders.
- The listed trade/state artifacts remain authoritative; the summary is a navigation and debugging layer.

## Related Proof

- `tests/destructive/trading-agency-hyperliquid-test.py`
- `tests/destructive/trading-agency-hyperliquid-repeat-cycle-test.py`
- `tests/destructive/trading-agency-negative-path-test.py`
