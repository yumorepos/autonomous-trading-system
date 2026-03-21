# System Architecture Summary

## Scope

This document describes the **current canonical Phase 1 paper-trading system** in this repository. It is intentionally scoped to what the code actively supports today:

- **Paper trading only**
- **Hyperliquid execution path only**
- **Polymarket disabled/incomplete in the active flow**

## Execution Flow

The canonical operator path starts with `scripts/trading-agency-phase1.py`.

1. **Optional component detection**
   - The orchestrator reports whether optional components exist, but does not promote them into the active path automatically.
2. **Data integrity gate**
   - `scripts/data-integrity-layer.py` validates source health before scanning.
3. **Signal scanning**
   - `scripts/phase1-signal-scanner.py` fetches market data and writes candidate signals.
   - In practice, the active trade path is the Hyperliquid funding-arbitrage branch.
4. **Pre-trade safety validation**
   - `scripts/execution-safety-layer.py` evaluates freshness, duplicate risk, exchange health, size limits, and circuit-breaker conditions.
5. **Paper trade planning**
   - `scripts/phase1-paper-trader.py` builds an execution plan for entries and exits.
6. **Authoritative state update**
   - Planned trade records are persisted to `workspace/logs/phase1-paper-trades.jsonl`.
   - Canonical open-position state is updated in `workspace/logs/position-state.json`.
7. **Monitor/report stage**
   - The orchestrator safely runs `scripts/timeout-monitor.py`, which reads authoritative state and writes timeout-tracking artifacts.
   - The orchestrator does **not** run `scripts/exit-monitor.py` in the canonical loop because that script currently writes exit-proof artifacts without performing the authoritative close-state update.

## Non-Canonical Artifacts

The repository still contains historical and exploratory material, but it should not be presented as active system behavior:

- `scripts/archive/` contains legacy alternate implementations and simulation-only scripts.
- `docs/archive/` contains historical reports, repair notes, and stale status documents retained only for audit provenance.
- `scripts/polymarket-executor.py` is exploratory scaffold code and is not part of the active Phase 1 execution path.

## State Model

The repository has two important state layers:

### 1. Append-only trade history
- File: `workspace/logs/phase1-paper-trades.jsonl`
- Purpose: durable event log of paper trade records
- Shape: normalized by `models/trade_schema.py`

### 2. Authoritative open-position state
- File: `workspace/logs/position-state.json`
- Purpose: current open positions only
- Shape: managed by `models/position_state.py`

### Supporting operator/system state
- `workspace/operator_control.json` stores human override inputs.
- `workspace/system_status.json` stores current health, recovery, and permissions decisions.
- `workspace/system_health.json` and incident logs preserve escalation/recovery history.

## Safety Layers

Safety is not a single script; it is a set of controls applied before and after planning:

### Data integrity layer
- Validates source availability and basic market-data reliability before scanning.
- Prevents the scanner from running under unacceptable data conditions.

### Execution safety layer
- Checks signal freshness.
- Blocks duplicate orders within a configured window.
- Enforces position-size and portfolio limits.
- Measures exchange/API health and latency.
- Maintains circuit-breaker state and kill-switch behavior.

### Schema and state guards
- `models/trade_schema.py` normalizes legacy records into one canonical shape.
- `models/position_state.py` rejects malformed open-position records and protects status transitions.

## Incident System

`utils/system_health.py` centralizes incident handling.

It tracks:
- incident severity (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`)
- escalation windows
- active vs resolved incidents
- affected systems/components
- operator actions
- anti-flapping and cooldown windows

The intent is operational truthfulness: failures are recorded, escalated, and reflected into system status rather than silently ignored.

## Recovery System

Recovery decisions are also managed through `SystemHealthManager`.

Key behaviors:
- `HEALTHY`, `DEGRADED`, and `CRITICAL` health states
- cooldown transitions from critical to degraded and degraded to healthy
- anti-flapping locks when status changes too often
- computed trading permissions such as:
  - allow new trades
  - allow monitoring
  - allow exits

This means the system can continue monitoring or exiting even when new entries are blocked.

## Operator Controls

Human controls live in `workspace/operator_control.json`.

Current control categories:
- `manual_mode`
- `trading_override`
- `recovery_override`
- operator notes and timestamps

These controls are normalized, validated, and audit-logged. They allow an operator to:
- keep the system in normal automatic mode
- restrict or halt new trade entry
- hold recovery status at a more conservative level
- document why an override was applied

## What Is Explicitly Out of Scope

To keep the repository truthful, the following should **not** be presented as active capabilities:

- live capital deployment
- production-ready exchange execution
- active Polymarket trading
- multi-exchange orchestration in the canonical path

Historical documents that made stronger claims were archived for reference only.
