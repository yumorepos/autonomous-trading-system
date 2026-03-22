# Integration Gap Matrix

Date: 2026-03-21 UTC

## Matrix legend

- **Present** = code path exists
- **Proven** = covered by CI/test evidence in the current repo
- **Canonical** = part of the real operator flow
- **Gap** = what still blocks a stronger claim

| Area | Hyperliquid | Polymarket | Mixed | Canonical? | Proven? | Gap |
|---|---|---|---|---|---|---|
| runtime mode config | Present | Present | Present | Yes | Implicitly | No direct config/unit test beyond mode-gate behavior. |
| pre-scan integrity gate | Present | Present | Present | Yes | Partially | Only mocked mode-aware behavior is tested. |
| signal scanner | Present | Present | Present | Yes | Partially | Schema generation tested with fakes; no orchestrator integration proof. |
| safety validation | Present | Present | Present | Yes | Weakly | No direct test proving scanner output survives safety in agency flow. |
| paper entry planning | Present | Present | Present | Yes | Yes (isolated) | Proven in trader tests, not in orchestrator. |
| paper exit planning | Present | Present | Present | Yes | Yes (isolated) | Proven in trader tests only. |
| append-only trade history | Present | Present | Present | Yes | Yes (isolated) | Repo-wide canonical claim weakened by non-canonical Polymarket files elsewhere. |
| authoritative open-position state | Present | Present | Present | Yes | Yes (isolated) | Schema mismatch remains between normalized trade model and stored position extras. |
| performance summary | Present | Present | Present | Yes | Yes (isolated) | Depends on closed trade normalization only. |
| timeout monitor | Present | Present | Present | Yes | Partially | Threshold support proven; actual orchestrated runtime monitoring not proven. |
| exit monitor | Present | Present | Present | No | No | Explicitly non-canonical proof generator. |
| non-canonical executor helper | N/A | Present | N/A | No | No | Creates alternate Polymarket state model and naming confusion. |
| full agency/orchestrator run | Present in code | Present in code | Present in code | Yes | No | No CI or destructive test executes `trading-agency-phase1.py`. |
| external connectivity proof | Weak | Weak | Weak | Optional | No | Current audit environment failed both read-only connectivity checks. |
| mode-specific truthfulness | Strongest | Experimental | Overstated | Mixed | Partial | Mixed mode is not dual-entry per cycle; Polymarket still has active non-canonical leftovers. |

## Specific gaps

### 1. Missing orchestrator proof
- File path: `scripts/trading-agency-phase1.py`
- Problem: no test invokes the real canonical runner.
- Impact: “end-to-end” is not fully proven for either exchange.

### 2. Mixed mode is accumulative, not truly parallel
- File paths: `scripts/phase1-paper-trader.py`, `tests/destructive/mixed-mode-integration-test.py`
- Problem: the trader selects one candidate entry per cycle.
- Impact: docs that imply side-by-side operation are stronger than the implementation.

### 3. Canonical schema does not fully encode exchange identity
- File paths: `models/trade_schema.py`, `scripts/performance-dashboard.py`, `models/position_state.py`
- Problem: readers rely on raw/extras instead of a single formal schema.
- Impact: state-model agreement is incomplete.

### 4. Polymarket still has alternate state files in active code
- File paths: `scripts/polymarket-executor.py`, `scripts/live-readiness-validator.py`, `scripts/stability-monitor.py`
- Problem: alternate Polymarket persistence exists outside the canonical path.
- Impact: repo cannot claim one fully unified Polymarket state model.

### 5. Optional-component reporting overstates active Polymarket execution
- File path: `scripts/trading-agency-phase1.py`
- Problem: `polymarket_execution` is reported as enabled when helper file exists + mode includes Polymarket.
- Impact: runtime status wording is misleading because canonical execution never calls that helper.

## Minimum truthful statements available today

### Safe statements
- Hyperliquid is the default canonical paper-trading path.
- Polymarket is available in the paper-trading path but remains experimental.
- The repository does not implement live trading.
- CI verifies isolated paper-trading behavior and schema expectations.

### Unsafe statements
- Hyperliquid is fully end-to-end proven.
- Polymarket is fully integrated end-to-end.
- Mixed mode is fully proven as a side-by-side dual-exchange runtime.
- CI proves the canonical orchestrator.
- The repository has one fully unified state model across every active script.
