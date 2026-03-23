# Integration Gap Matrix

Audit date: 2026-03-23 UTC

This matrix lists the concrete gaps between the current repository and any truthful claim that **both Hyperliquid and Polymarket are fully integrated**.

| Claim area | Current evidence | Gap | Why it matters | Priority |
|---|---|---|---|---|
| Hyperliquid end-to-end paper path | Canonical orchestrator, scanner, safety, trader, state, monitor, and offline agency tests exist. | No live execution path. | “Fully integrated” is only truthful with a paper-only qualifier. | Critical |
| Polymarket end-to-end paper path | Canonical scanner/trader/state path exists and offline agency tests pass. | No authenticated execution path, fill handling, settlement, or live integration proof. | Blocks any stronger-than-paper integration claim. | Critical |
| Public API compatibility today | Optional connectivity script exists. | CI does not prove current live payload compatibility; audit connectivity checks failed in this environment due proxy tunnel 403. | Current runtime compatibility is not continuously proven. | High |
| Shared canonical contract | Scanner integrity now enforces the paper adapter's declared exchange-specific signal contract before persistence. | Contract definitions still live across integrity checks, exchange adapters, trade normalization, and state readers instead of one centralized source. | Canonical acceptance now guarantees paper executability, but schema/contract drift risk is not fully eliminated. | Medium |
| Mixed mode | Both exchanges can be scanned; state model can hold both over time. | Only one new entry per cycle; Hyperliquid is deterministic priority winner. | Mixed mode is not peer-symmetric full integration. | High |
| Docs truth surface | Main truth docs are mostly aligned. | Active docs root still contains stale/generated report files that read like current evidence. | Reviewers can misread repo maturity and current state. | High |
| Canonical vs support artifacts | Canonical path is sharply implemented in code. | Support/future-scope scripts still have names that imply broader scope. | Raises truthfulness and review ambiguity risk. | Medium |
| Current state model | Shared trade schema and position state work across both exchanges. | Contract is distributed across multiple modules and validations, not enforced from one source at all producer boundaries. | Schema drift risk grows as features expand. | Medium |
| Negative-path coverage parity | Hyperliquid negative paths are tested more thoroughly, and canonical signal rejection now has targeted regression coverage. | Polymarket negative-path coverage is still lighter, especially around broader runtime and exchange-specific failure cases. | Experimental path remains less proven even though the core signal-contract rejection path is covered. | Medium |
| Live-readiness framing | Main docs say paper-only. | Generated reports/support docs can still imply operator-grade maturity. | Weakens repo truthfulness even without explicit false claims. | Medium |

## Minimum truthful wording right now

Use wording like this:

> Hyperliquid is integrated into the canonical paper-trading runtime. Polymarket is integrated into the same paper runtime, but remains experimental overall and is not yet fully integrated beyond paper trading.

Avoid wording like this:

- “Both exchanges are fully integrated.”
- “Polymarket is complete end-to-end.”
- “Mixed mode runs both exchanges side by side as equal peers.”
- “CI proves live exchange compatibility.”

## Short priority order

1. Fix truth surface and stale docs.
2. Centralize canonical contract helpers across integrity, adapters, schema normalization, and readers.
3. Add optional live-shape contract checks.
4. Expand Polymarket negative-path tests.
5. Decide whether Polymarket remains paper-only or gets a real execution roadmap.
