# Data Integrity Layer

**Version:** 1.1  
**Scope:** active paper-trading data-validation behavior  
**Status:** active canonical support documentation

## What is canonical now

The current canonical runtime uses the data-integrity layer in **two** places:

1. **Pre-scan gate** in `scripts/trading-agency-phase1.py`
   - Calls `DataIntegrityLayer.run_pre_scan_gate()` before scanner execution.
   - Validates source availability, snapshot freshness, and minimum completeness for the exchanges enabled by the current mode.

2. **Per-signal validation** in `scripts/phase1-signal-scanner.py`
   - Calls `DataIntegrityLayer.validate_signal()` on each generated signal **before** the scanner appends it to `workspace/logs/phase1-signals.jsonl`.
   - Rejected signals are written to `workspace/logs/rejected-signals.jsonl`.

This document describes only that behavior.

## What the canonical path writes

- `workspace/logs/data-integrity-state.json`
- `workspace/logs/source-reliability-metrics.json`
- `workspace/logs/rejected-signals.jsonl` when signal-level validation rejects a candidate
- `workspace/logs/runtime-events.jsonl`

## Pre-scan gate behavior

`run_pre_scan_gate()` checks:

- API availability for the active exchanges
- timestamp freshness for the fetched snapshot used by the gate
- minimum source completeness
  - Hyperliquid asset count threshold
  - Polymarket market count threshold
- minimum sample field completeness for fetched payloads

### Mode handling

- `hyperliquid_only`
  - Hyperliquid checks are required.
- `polymarket_only`
  - Polymarket checks are required.
- `mixed`
  - Hyperliquid remains the primary required source.
  - Polymarket source-health failures are downgraded to warning-level when Hyperliquid is also enabled.

That asymmetry is deliberate and should be described as a **limited mixed-mode policy**, not full dual-exchange parity.

## Signal-level validation behavior

`validate_signal()` checks generated signals for:

- required signal fields
- signal timestamp freshness
- duplicate detection against recently accepted signals tracked in `data-integrity-state.json`
- signal decay / expiry

### Important limits

- This is still a **paper-trading** signal path.
- The layer does **not** prove live market correctness or authenticated execution readiness.
- Duplicate detection is based on recently accepted canonical signals, not on live exchange orders.

## What this layer does not do

- It does not place trades.
- It does not authenticate to either exchange.
- It does not prove live exchange reachability in CI.
- It does not make mixed mode symmetric.

## Truthful short description

Use wording like this:

> The data-integrity layer blocks scanner execution when required sources fail the pre-scan gate, and it rejects invalid generated paper-trading signals before they are appended to canonical signal history.

Avoid wording like this:

- “All market data is fully validated end-to-end for live execution.”
- “Mixed mode treats both exchanges equally.”
- “The layer proves production readiness.”
