# Integration Gap Matrix

Date: 2026-03-23 UTC

## Scope

This matrix lists the concrete gaps between the current repository and any truthful claim that **both Hyperliquid and Polymarket are fully integrated**.

| Gap | Files / surface | Current state | Why it matters | Severity |
|---|---|---|---|---|
| No live execution implementation at all | `README.md`, `SYSTEM_STATUS.md`, `docs/POLYMARKET_EXECUTION_SCOPE.md` | Repo explicitly says paper-trading only. | Blocks any production/full-integration claim for either exchange. | Critical |
| Polymarket adapter is public-market-data + paper math only | `utils/paper_exchange_adapters.py` | Uses Gamma `GET /markets` for price/health/liquidity/spread; no signed orders or fills. | Confirms Polymarket is not live-integrated. | Critical |
| Hyperliquid is also paper-only | `utils/paper_exchange_adapters.py`, `README.md` | Hyperliquid path also stops at paper trade records. | “Integrated” is truthful only with a paper-trading qualifier. | Critical |
| Mixed mode is not peer/dual execution | `models/exchange_metadata.py`, `scripts/phase1-paper-trader.py`, `scripts/data-integrity-layer.py` | One new entry per cycle; Hyperliquid priority winner; secondary Polymarket health advisory. | Prevents any claim that mixed mode is a mature dual-exchange runtime. | High |
| CI does not prove live/network-backed end-to-end behavior | `.github/workflows/basic.yml`, `scripts/ci-safe-verification.sh` | CI intentionally excludes blocking network-dependent checks and uses offline fixtures for destructive tests. | The repo is well-tested offline, not live-integrated. | High |
| Non-canonical exit monitor duplicates exchange logic | `scripts/exit-monitor.py`, `utils/paper_exchange_adapters.py` | Extra proof/report surface exists outside canonical flow. | Extra maintenance surface and truth confusion. | Medium |
| Support scripts can be mistaken for active execution | `scripts/live-readiness-validator.py`, `scripts/exit-monitor.py`, `scripts/stability-monitor.py` | Present in active tree, not on canonical path. | Confuses reviewers about what is real. | Medium |
| Historical archive remains large and grep-visible | `docs/archive/`, `scripts/archive/` | Old conclusions and historical scaffolding remain in-tree. | Reviewers can still confuse historical material with current truth. | Medium |
| No live integration tests for Polymarket | `tests/`, `.github/workflows/basic.yml` | Strong offline paper tests only. | Paper proof does not imply live integration. | High |
| No authenticated-client abstraction split between paper and live | `utils/paper_exchange_adapters.py` | Paper adapters are the only exchange adapters. | Makes future live integration harder and keeps nomenclature ambiguous. | Medium |
| Top truth surfaces are honest, but docs truth guard is incomplete | `tests/repo-truth-guard-test.py` | Test protects a few docs, not all active docs. | Allows support-doc drift back into overclaim territory. | Low |

## Exchange-by-exchange summary

### Hyperliquid

| Layer | State |
|---|---|
| Scanner | implemented |
| Safety | implemented |
| Paper execution | implemented |
| Canonical persistence | implemented |
| Timeout monitor | implemented |
| Offline orchestrator proof | implemented |
| Live execution | not implemented |
| Live tests | not implemented |

### Polymarket

| Layer | State |
|---|---|
| Scanner | implemented |
| Safety | implemented |
| Paper execution | implemented |
| Canonical persistence | implemented |
| Timeout monitor | implemented |
| Offline orchestrator proof | implemented |
| Authenticated order placement | missing |
| Wallet/signing flow | missing |
| Fill reconciliation | missing |
| Settlement handling | missing |
| Live tests | missing |

## Immediate repair priority

1. Tighten docs to say exactly what is wired now.
2. Wire signal-level integrity validation into the scanner if the docs want to claim it.
3. Keep Polymarket described as canonical **paper** integration, not full integration.
4. Either archive non-canonical support surfaces or label them harder.
5. Only then decide whether live Polymarket integration is an actual goal.
