# System Status

**Last Updated:** 2026-03-21 UTC  
**Verdict:** Canonical paper-trading architecture supports Hyperliquid by default plus optional experimental Polymarket paper mode

---

## Canonical Active Architecture

The active architecture in this repository is the orchestrated Phase 1 paper-trading path:

1. `scripts/bootstrap-runtime-check.py`
2. `scripts/trading-agency-phase1.py`
3. `scripts/data-integrity-layer.py`
4. `scripts/phase1-signal-scanner.py`
5. `scripts/execution-safety-layer.py`
6. `scripts/phase1-paper-trader.py`
7. `scripts/timeout-monitor.py`

This architecture is authoritative for paper trading only.

---

## Runtime Modes

- `hyperliquid_only` — **default canonical mode**
- `polymarket_only` — optional experimental paper mode
- `mixed` — optional paper-evaluation mode for both exchanges

The orchestrator, scanner, and data-integrity scope are controlled by the selected runtime mode.

---

## Scope Limits

- **Execution mode:** paper trading only
- **Default exchange:** Hyperliquid
- **Optional exchange:** Polymarket
- **Live deployment claim:** not supported
- **Real exchange execution:** not implemented

---

## Explicitly Non-Canonical or Limited

- **`scripts/exit-monitor.py`:** standalone proof/audit script only; not authoritative close-state persistence
- **`scripts/polymarket-executor.py`:** non-canonical helper/scaffold; not the authoritative Polymarket execution path
- **`docs/archive/`:** historical only
- **Supporting analytics/readiness scripts:** useful for review, but not proof of live readiness

---

## What Reviewers Should Trust

Use these files for current repository truth:

- `README.md`
- `SYSTEM_STATUS.md`
- `docs/SYSTEM_ARCHITECTURE.md`
- `docs/REPO_TRUTHFULNESS_AUDIT.md`

---

## Summary

The repository now supports **truthful end-to-end paper trading** for Hyperliquid and optional Polymarket through one canonical architecture. Hyperliquid remains the default and best-supported path. Polymarket is integrated for paper trading but should still be described as optional and experimental until broader runtime evidence exists.
