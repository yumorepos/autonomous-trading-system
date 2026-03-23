# Polymarket Execution Scope

## Current truth

Polymarket is currently integrated into the repository's **canonical paper-trading path**.

That means the repo does support all of the following for `polymarket_only` and limited mixed-mode participation:
- data-integrity gating
- signal generation
- safety validation
- paper-trade planning
- canonical trade persistence
- canonical open-position state
- timeout-monitor compatibility
- agency/offline proof coverage

## What is not implemented

The repository does **not** implement live Polymarket execution.

Missing pieces include:
- authenticated order placement
- wallet/signing flow
- fill reconciliation
- settlement handling
- live execution integration tests
- any live-readiness or production-readiness basis

## How to describe it truthfully

Use wording like this:

> Polymarket is integrated into the canonical paper-trading runtime, but remains experimental overall and is not live-ready.

Avoid wording like this:
- "Polymarket is fully integrated" without a paper-only qualifier
- "Polymarket is live-ready"
- "Polymarket is only helper/scaffold code"

## Mixed-mode caveat

Mixed mode does not make Polymarket a peer of Hyperliquid in the canonical agency loop.

Current mixed-mode policy is:
- scan both exchanges
- allow at most one new entry per cycle
- prioritize Hyperliquid for deterministic entry selection
- treat secondary-source health as advisory when Hyperliquid is available
