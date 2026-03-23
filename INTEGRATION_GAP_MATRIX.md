# INTEGRATION_GAP_MATRIX

Date: 2026-03-23 UTC

## Matrix legend

- **Present**: code path exists in canonical runtime
- **Offline-proven**: covered by deterministic isolated tests/CI
- **Live-proven**: exercised against real exchange/runtime dependencies in a reliable way
- **Canonical**: actually on the top-level execution path

## Exchange integration matrix

| Capability | Hyperliquid | Polymarket | Notes |
|---|---|---|---|
| Mode selection in runtime config | Present | Present | `config/runtime.py` supports `hyperliquid_only`, `polymarket_only`, `mixed`. |
| Data-integrity pre-scan gate | Present | Present | Mixed mode is asymmetric: Hyperliquid failure is critical; Polymarket failure is warning-only. |
| Scanner emits canonical signals | Present | Present | Shared scanner writes both into the same signal log. |
| Safety validation via canonical path | Present | Present | Same safety layer, exchange-specific adapter logic. |
| Paper-trade entry planning | Present | Present | Same paper trader, different adapters. |
| Paper-trade exit planning | Present | Present | Same paper trader checks exits for open positions across exchanges. |
| Canonical trade persistence | Present | Present | Shared `phase1-paper-trades.jsonl`. |
| Canonical open-position state | Present | Present | Shared `position-state.json`. |
| Performance accounting | Present | Present | Shared `phase1-performance.json`. |
| Timeout monitoring | Present | Present | Shared monitor reads canonical state. |
| Agency/offline end-to-end proof | Offline-proven | Offline-proven | Hyperliquid has broader proof depth. |
| Mixed-mode agency entry in same cycle | Preferred / primary | Limited / secondary | Canonical mixed mode takes at most one new entry per cycle. |
| Mixed-mode state coexistence | Present | Present | Trader-level tests show both can coexist in canonical state across cycles. |
| Live connectivity proof in CI | No | No | CI intentionally avoids blocking network checks. |
| Authenticated order placement | No | No | Not implemented. |
| Wallet/signing/execution path | No | No | Not implemented. |
| Live-ready claim supported | No | No | False for both exchanges. |

## Specific gaps that keep Polymarket from being "fully integrated" in the broad sense

| Gap | Exact files | Why it matters | Severity |
|---|---|---|---|
| No authenticated execution/order path | `utils/paper_exchange_adapters.py`, `utils/api_connectivity.py`, entire repo | Integration stops at public market data plus paper persistence. No real execution exists. | Critical |
| No live integration test | `.github/workflows/basic.yml`, `scripts/ci-safe-verification.sh`, `tests/support/offline_requests_sitecustomize.py` | All end-to-end proof is fixture-driven/offline. | Critical |
| Mixed mode is not symmetric | `scripts/data-integrity-layer.py`, `models/exchange_metadata.py`, `scripts/phase1-paper-trader.py`, `scripts/trading-agency-phase1.py` | Mixed mode is limited evaluation, not a fully integrated dual-exchange runtime. | High |
| Hyperliquid is hard-primary in mixed mode | `models/exchange_metadata.py`, `scripts/phase1-paper-trader.py` | Polymarket can be present, but canonical selection is biased toward Hyperliquid. | Medium |
| Repo-wide truth surface still contains stale contradictory history | `docs/archive/`, `scripts/archive/` | Reviewers can find obsolete conflicting conclusions and old claims. | Medium |
| Safety layer reads raw recent trades | `scripts/execution-safety-layer.py` | Schema drift risk if runtime producers change field shape. | Medium |
| Non-canonical exit monitor duplicates exchange logic | `scripts/exit-monitor.py`, `utils/paper_exchange_adapters.py` | Extra maintenance surface and truth confusion. | Low |

## Specific gaps that keep Hyperliquid from being "production integrated"

| Gap | Exact files | Why it matters | Severity |
|---|---|---|---|
| No real order placement | repo-wide | Hyperliquid path ends at paper-trade records. | Critical |
| No live integration proof in CI | `.github/workflows/basic.yml`, `scripts/ci-safe-verification.sh` | Runtime connectivity is optional and non-blocking. | Critical |
| No credential/bootstrap enforcement beyond Python deps | `scripts/bootstrap-runtime-check.py` | Bootstrap does not verify any exchange auth prerequisites because none exist. | High |
| Support scripts can be mistaken for active execution | `scripts/live-readiness-validator.py`, `scripts/exit-monitor.py`, `scripts/stability-monitor.py` | Confuses reviewers about what is real. | Medium |

## Truthful classification matrix

| Claim | Truthful? | Why |
|---|---|---|
| "Hyperliquid is integrated." | Yes, if explicitly scoped to canonical paper trading. |
| "Polymarket is helper/scaffold only." | No. It is wired into the canonical paper flow. |
| "Polymarket is fully integrated." | No, unless narrowly scoped to the canonical paper-only flow and even then it should still be labeled experimental overall. |
| "Both exchanges are live-ready." | No. |
| "Mixed mode is a fully integrated dual-exchange runtime." | No. |
| "The system is paper-trading only." | Yes. |
