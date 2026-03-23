# Execution Safety Layer

**Version:** 1.1  
**Scope:** active paper-trading entry-validation behavior  
**Status:** active canonical support documentation

## What is canonical now

The execution safety layer is part of the canonical paper-trading runtime.

It is called by `scripts/trading-agency-phase1.py` after signal scanning and before trade persistence.

Its job is to decide whether the **next candidate paper trade** is allowed to proceed into the paper trader.

## Canonical inputs

- the selected candidate signal
- canonical recent trade history from `workspace/logs/phase1-paper-trades.jsonl`
- canonical open-position state from `workspace/logs/position-state.json`
- runtime health/operator state from `utils/system_health.py`

## Canonical outputs

- `workspace/logs/execution-safety-state.json`
- `workspace/logs/blocked-actions.jsonl` when an entry is blocked
- `workspace/logs/incident-log.jsonl`
- runtime events in `workspace/logs/runtime-events.jsonl`

## Enforced blocking checks

These checks can block entry in the canonical path:

- kill switch
- signal freshness
- duplicate-order detection
- max position size
- circuit breakers
- exchange health when the API is down

## Advisory / warning checks

These checks run in the canonical path but do **not** necessarily block entry on their own:

- liquidity threshold checks
- spread checks
- supporting data-integrity warnings
- slow-but-responsive exchange-health state

## System status meaning

- `SAFE`
  - no blocking issues detected
- `CAUTION`
  - warning-level issues or recent critical incidents exist
- `HALT`
  - kill switch, breaker conditions, or exchange-down state prevents new entries

## Important limits

- This layer protects **paper-trading proposals**, not live orders.
- It uses public market-data lookups through the paper exchange adapters.
- It does not authenticate to exchanges.
- It does not perform real order placement, fill verification, or settlement reconciliation.

## Truthful short description

Use wording like this:

> The execution safety layer enforces blocking checks for the next candidate paper trade and persists the decision state before the paper trader writes canonical trade records.

Avoid wording like this:

- “The safety layer protects live execution in this repository.”
- “All checks are hard blockers.”
- “The layer makes the system production-ready.”
