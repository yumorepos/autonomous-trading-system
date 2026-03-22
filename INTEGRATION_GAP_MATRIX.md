# Integration Gap Matrix

Date: 2026-03-22 UTC

Legend:
- **present** = code path exists
- **canonical** = part of the real operator flow
- **offline-proven** = covered by current CI-safe tests
- **live-proven** = not available anywhere in this repo

| Area | Hyperliquid | Polymarket | Mixed | Canonical | Offline-proven | Gap / note |
|---|---|---|---|---|---|---|
| runtime mode config | present | present | present | yes | yes | Mixed semantics are limited to one new entry per cycle. |
| bootstrap/runtime check | present | present | present | yes | yes | Only import/dependency proof, not exchange reachability. |
| data-integrity gate | present | present | present | yes | yes | Real runs still depend on live read-only APIs unless fixtures are injected. |
| signal scanner | present | present | present | yes | yes | Polymarket scanner is paper-only and uses read-only Gamma market data. |
| safety validation | present | present | present | yes | yes | Polymarket safety is still market-data-based, not execution-grade. |
| paper entry planning | present | present | present | yes | yes | Planner creates at most one new entry per cycle. |
| paper exit planning | present | present | present | yes | yes | Exit pricing for Polymarket is still heuristic/read-only lookup. |
| canonical trade history | present | present | present | yes | yes | Clean shared paper-trading flow across both exchanges. |
| authoritative open-position state | present | present | present | yes | yes | Canonical state is shared across both exchanges. |
| performance summary | present | present | present | yes | yes | Derived from canonical closed trades only. |
| timeout monitor | present | present | present | yes | yes | Monitoring only; not authoritative close persistence. |
| agency/orchestrator runtime | present | present | present | yes | yes | Offline-only proof. No live API proof in CI. |
| live execution | absent | absent | absent | no | no | Repo is paper-trading only. |
| external connectivity proof | weak | weak | weak | optional | no | Connectivity checks failed in this audit environment due proxy/tunnel errors. |
| truthfulness consistency across docs | strong | partial | partial | mixed | no | Some docs remain stale relative to code/tests. |

## Blocking gaps for a “both fully integrated” claim

1. Polymarket now executes through the same canonical trader/orchestrator path as Hyperliquid.
2. Real Polymarket execution is explicitly not implemented.
3. Mixed mode is single-entry-per-cycle, not dual-entry-per-cycle.
4. Live API reachability is not part of CI proof and was not successful from this audit environment.
5. Some docs still describe an older proof/model story.

## Minimum truthful statements available now

### Safe
- Hyperliquid is the canonical integrated paper-trading path.
- Polymarket is integrated into the canonical paper-trading path as a first-class exchange.
- Mixed mode is a limited evaluation mode.
- The repository is paper-trading only.

### Unsafe
- Both exchanges are fully integrated end-to-end.
- Mixed mode is a full side-by-side dual-exchange runtime.
- The repo is live-ready.
- CI proves live connectivity or live execution.
