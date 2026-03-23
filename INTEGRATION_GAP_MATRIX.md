# Integration Gap Matrix

Date: 2026-03-22

## Current integration summary

| Area | Hyperliquid | Polymarket | Mixed mode |
|---|---|---|---|
| Runtime mode support | Yes | Yes | Yes |
| Scanner path | Yes | Yes | Both scanned |
| Safety gate path | Yes | Yes | Yes |
| Trader entry path | Yes | Yes | One entry only |
| Trader exit path | Yes | Yes | Yes |
| Shared canonical trade history | Yes | Yes | Yes |
| Shared authoritative position state | Yes | Yes | Yes |
| Timeout monitor support | Yes | Yes | Reads shared state |
| Agency-level offline proof | Yes | Yes | Limited proof only |
| Live order execution | No | No | No |
| Authenticated exchange integration | No | No | No |
| Fill reconciliation | No | No | No |
| Settlement lifecycle | No | No | No |

---

## Blocking gaps for a “both fully integrated” claim

| Gap | Affects | Severity | Why it blocks the claim |
|---|---|---|---|
| No live execution path | Both exchanges | Critical | The runtime never places or confirms a real order. |
| No authentication / signing / wallet flow | Both exchanges, especially Polymarket | Critical | Real end-to-end exchange integration requires authenticated execution, not just read-only market data. |
| No fill/order-status reconciliation | Both exchanges | Critical | The system cannot prove that an intended trade became an executed trade on an exchange. |
| No settlement handling | Polymarket | Critical | Binary-market lifecycle is not complete without outcome resolution/settlement semantics. |
| Offline fixtures are the main proof | Both exchanges | High | Tests prove local canonical wiring, not live exchange interoperability. |
| Mixed mode is one-entry deterministic priority mode | Mixed runtime | High | This is not full concurrent dual-exchange integration. |
| Experimental-status metadata is inconsistent | Polymarket | Medium | Docs, runtime events, and persisted signals/trades disagree about whether Polymarket is experimental. |
| Docs still contain stale contradictions | Truth surface | Medium | Some active docs understate proof or retain stale audit language. |

---

## State-model agreement matrix

| Subsystem | Uses canonical shared trade schema? | Uses shared open-position state? | Notes |
|---|---|---|---|
| orchestrator (`scripts/trading-agency-phase1.py`) | Yes | Yes | Calls trader helpers and `models.position_state.get_open_positions`. |
| scanner (`scripts/phase1-signal-scanner.py`) | N/A for trade records | Indirect | Emits normalized signals used by trader/safety. |
| safety (`scripts/execution-safety-layer.py`) | Yes | Reads trade history, not position state | Breakers derive from canonical trade history. |
| trader (`scripts/phase1-paper-trader.py`) | Yes | Yes | Persists canonical trades and updates canonical open-position state. |
| trade schema (`models/trade_schema.py`) | Yes | Yes | Single normalizer/validator for Hyperliquid and Polymarket. |
| position state (`models/position_state.py`) | Yes | Yes | One authoritative open-position model. |
| timeout monitor (`scripts/timeout-monitor.py`) | Validates records | Yes | Reads canonical open positions only. |
| exit monitor (`scripts/exit-monitor.py`) | Reads canonical positions | Yes | Non-canonical; writes proof only. |
| performance dashboard (`scripts/performance-dashboard.py`) | Yes | Yes | Reads canonical trade history and shared position state. |

### Main agreement issue

The structural state model is mostly unified. The notable mismatch is **metadata semantics**, not storage shape:
- Polymarket docs are described as experimental.
- `models/exchange_metadata.py` says `paper_status=canonical`.
- Polymarket scanner/trader outputs set `experimental: False`.
- runtime events set `experimental: True` for Polymarket.

That is a truth/observability consistency problem with schema drift risk.

---

## Canonical vs non-canonical path matrix

| Path / file | Classification | Reason |
|---|---|---|
| `scripts/trading-agency-phase1.py` | Canonical | Real operator entrypoint. |
| `scripts/bootstrap-runtime-check.py` | Canonical stage | First enforced stage. |
| `scripts/data-integrity-layer.py` | Canonical stage | Enforced pre-scan gate. |
| `scripts/phase1-signal-scanner.py` | Canonical stage | Emits runtime signals. |
| `scripts/execution-safety-layer.py` | Canonical stage | Enforced critical gating. |
| `scripts/phase1-paper-trader.py` | Canonical stage | Builds and persists trade records. |
| `scripts/timeout-monitor.py` | Canonical monitor stage | Only monitor run by orchestrator. |
| `scripts/exit-monitor.py` | Non-canonical | Writes proof artifacts only; no authoritative close persistence. |
| `scripts/live-readiness-validator.py` | Non-canonical future-scope | Research validator, not runtime truth. |
| `scripts/stability-monitor.py` | Non-canonical support | Separate observability helper. |
| `scripts/archive/*` | Historical | Not part of current runtime. |
| `docs/archive/*` | Historical | Not part of active truth surface. |

---

## Truthful statements you can make today

### Safe to say
- Hyperliquid is the canonical integrated **paper-trading** path.
- Polymarket is integrated into the canonical **paper-trading** path as a first-class exchange.
- Mixed mode exists, but is limited and deterministic.
- CI proves offline canonical runtime behavior.
- The repo is paper trading only.

### Not safe to say
- Both exchanges are fully integrated end-to-end.
- Polymarket is production-ready.
- Mixed mode is a true dual-exchange execution runtime.
- The repo is live-ready.
- CI proves real exchange integration.
