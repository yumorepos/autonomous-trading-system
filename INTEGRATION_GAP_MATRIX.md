# Integration Gap Matrix

Audit date: 2026-03-23 UTC

This matrix lists the concrete gaps between the current repository and any truthful claim that **both Hyperliquid and Polymarket are fully integrated**.

| Claim area | Current evidence | Gap | Why it matters | Priority |
|---|---|---|---|---|
| Hyperliquid end-to-end paper path | Canonical orchestrator, scanner, safety, trader, state, monitor, and offline agency tests exist. | No live execution path. | “Fully integrated” is only truthful with a paper-only qualifier. | Critical |
| Polymarket end-to-end paper path | Canonical scanner/trader/state path exists and offline agency tests pass. | No authenticated execution path, fill handling, settlement, or live integration proof. | Blocks any stronger-than-paper integration claim. | Critical |
| Public API compatibility today | Optional connectivity script exists. | CI does not prove current live payload compatibility; audit connectivity checks failed in this environment due proxy tunnel 403. | Current runtime compatibility is not continuously proven. | High |
| Shared canonical contract | `models/paper_contracts.py` now centralizes exchange-specific signal requirements plus canonical open/closed trade requirements, and the canonical validators/readers consume those helpers. | Contract centralization is materially improved, but future live-order/fill work would still need to extend the shared contract instead of creating a second state model. | The current paper runtime has a shared source of truth; preserving that discipline matters as scope expands. | Low |
| Mixed mode | Both exchanges can be scanned; state model can hold both over time. | Only one new entry per cycle; Hyperliquid is deterministic priority winner. | Mixed mode is not peer-symmetric full integration. | High |
| Docs truth surface | Active truth docs now share one paper-only wording, and generated reports/support scripts are explicitly labeled non-canonical or support-only. | No major active wording contradiction remains; the remaining risk is drift if future edits bypass the truth guard. | Repo claims are currently aligned with code/tests, but that alignment needs to stay enforced. | Low |
| Canonical vs support artifacts | Canonical path is sharply implemented in code, and support/future-scope scripts now describe themselves as support-only. | Filenames still exist for historical continuity, but active descriptions no longer present them as canonical runtime components. | Reviewers should continue to follow `TRUTH_INDEX.md`/root audit artifacts rather than infer scope from legacy filenames alone. | Low |
| Current state model | Shared trade schema and position state work across both exchanges through the centralized paper contract helpers. | Live execution, fills, and settlement are still absent, so the shared paper-state model is not proof of broader exchange integration. | The paper runtime is coherent today, but it should not be over-interpreted as live-readiness. | Medium |
| Negative-path coverage parity | Polymarket now has offline negative-path coverage for stale signals, duplicate entries, missing token metadata, malformed payload blocking, and canonical signal-contract rejection. | Broader live/runtime failure parity is still unproven because all exchange failure cases are fixture-driven and offline. | Polymarket paper-path blocking behavior is much better covered now, but this is still not live-integration proof. | Medium |
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

1. Add optional live-shape contract checks.
2. Decide whether Polymarket remains paper-only or gets a real execution roadmap.
3. If live scope is chosen, add authenticated order/fill/settlement handling.
4. Preserve the centralized paper contract as new execution states are introduced.
