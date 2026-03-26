# Interview Preparation — Autonomous Trading System

## Resume Bullet (copy-paste ready)

> Built an autonomous paper-trading system in Python that scans 100+ cryptocurrency markets, evaluates signals through a 10-gate safety layer with circuit breakers and schema-validated persistence, and executes trades unattended via scheduled cycles — achieving end-to-end pipeline reliability across 25 test suites with zero data corruption in append-only trade logging.

---

## 10 Likely Interview Questions + Strong Answers

### 1. "Walk me through the system architecture."

**Answer:** The system runs on a scheduler (launchd, every 4 hours). Each cycle flows through 7 stages: signal scanning → data integrity validation → execution safety checks → paper trade entry/exit → canonical persistence → performance analytics. Every stage produces structured output — if any stage fails, the cycle halts safely and logs the failure. All trade data is append-only JSONL, and position state is derived from trade history, never stored as authoritative truth. This makes crash recovery trivial: replay the log, rebuild state.

### 2. "Why append-only logs instead of a database?"

**Answer:** Three reasons. First, auditability — every state change is preserved chronologically, nothing is ever mutated or deleted. Second, crash recovery — if the position state file corrupts, I rebuild it from the trade log in under a second. Third, simplicity — JSONL is human-readable, needs no server, and works with standard Unix tools (grep, jq, wc). The trade-off is no indexed queries, but with sub-1000 records that's irrelevant. If the system scaled to millions of trades, I'd add a SQLite index layer on top while keeping the JSONL as the source of truth.

### 3. "How do your safety systems work?"

**Answer:** The execution safety layer runs 10 independent checks before every trade entry: signal age (<5 min), position size limits, concurrent position cap, circuit breaker (3 consecutive losses halts everything), daily/hourly loss limits, drawdown protection (20% from peak = full stop), cooldown between trades, duplicate entry prevention, exchange connectivity, and capital adequacy. Each check returns pass/fail with a reason string. All 10 must pass. The key design choice: checks are stateless — they read from the canonical trade log every time, so there's no stale in-memory state that could drift from reality.

### 4. "What happens when the system crashes mid-trade?"

**Answer:** The append-only log is the single source of truth. On restart, the data integrity layer reads the JSONL, identifies open positions (entries without matching exits), and rebuilds `position-state.json`. Duplicate entry prevention ensures we don't re-enter a position we already hold. The worst case is a missed exit — the timeout monitor catches positions held beyond their timeout threshold and closes them on the next cycle. I tested this explicitly with a destructive test that corrupts the state file and verifies recovery.

### 5. "How did you validate the schema contract?"

**Answer:** I defined `CANONICAL_CLOSED_TRADE_FIELDS` (14 required fields) and `CANONICAL_OPEN_POSITION_FIELDS` (9 required fields) in a contracts module. The `normalize_trade_record()` function maps legacy field names (e.g., `entry_time` → `entry_timestamp`, `pnl` → `realized_pnl_usd`) to canonical names. `validate_trade_record()` checks all required fields are non-null for the given status and exchange. Every code path that writes or reads trades goes through this normalization. The test suite includes a contract test that reads a real production JSONL line and verifies it passes validation — so there's zero drift between what runtime produces and what the schema expects.

### 6. "Why Python? Would you use something else?"

**Answer:** Python was the right choice for prototyping speed and library availability — `eth_account` for key derivation, `py_clob_client` for Polymarket, direct HTTP for Hyperliquid. The bottleneck isn't compute (we make ~3-5 API calls per cycle), it's correctness. If I needed microsecond latency for HFT, I'd use Rust or C++. If I needed to serve a dashboard to users, I'd add a FastAPI layer. But for a research-phase paper trading system, Python's readability and test tooling (pytest, unittest) are the highest-leverage choice.

### 7. "How would you scale this to handle 10x more markets or strategies?"

**Answer:** Three changes. First, parallelize scanning — currently sequential HTTP calls, easy to convert to `asyncio` with `aiohttp` for concurrent market queries. Second, strategy registry — each strategy would register its signal contract and safety parameters, so the safety layer is strategy-agnostic. I already have the contract pattern (`SignalContract` dataclass per exchange). Third, separate the scheduler from the executor — run scanning and execution as independent processes communicating through the JSONL log, so a slow scan doesn't block exits. The append-only architecture already supports this naturally.

### 8. "What was the hardest bug you found?"

**Answer:** A test/production state leak. The execution safety layer computed file paths (`PAPER_TRADES_FILE`) at module import time from the production config. When tests overrode `runtime.LOGS_DIR` to a temporary directory, the safety layer still read from production JSONL. The test would see a production trade timestamp from 4:43 PM instead of the test fixture's 7:04 AM — a 35,000-second delta that failed the assertion. The fix was two helper functions that resolve paths at call time instead of import time. Small change, big lesson: module-level constants that depend on mutable config are a source of invisible coupling.

### 9. "What's your testing strategy?"

**Answer:** Three tiers. Unit tests validate individual components — schema normalization, safety checks, signal scoring. Integration tests run full cycles in isolated temp directories with fixture data and no network access. Destructive tests intentionally corrupt state files, inject bad signals, and trigger circuit breakers to verify recovery paths. I have 25 test files totaling ~77 test cases. The CI script (`ci-safe-verification.sh`) runs the full suite offline in under 10 seconds. Every test reads real production JSONL as fixtures, so there's no synthetic test data that could diverge from reality.

### 10. "If the system lost money consistently, how would you diagnose it?"

**Answer:** Start with the data. Pull all closed trades from the JSONL, compute win rate and expectancy per exit reason. If timeout trades are net negative, the signal quality is poor — tighten entry criteria or reduce timeout. If stop-loss trades dominate, the volatility model is wrong — widen stops or reduce position size. Check if losses cluster by time of day or market condition. Compare actual fill prices against signal prices to measure slippage. The performance report generator I built does this automatically — it breaks down PnL by exit reason, strategy, and duration. The key principle: never adjust the system based on a handful of trades. I set a minimum of 20+ trades before any parameter changes.

---

## Key Talking Points (keep in pocket)

1. **"I built systems that assume they will fail"** — circuit breakers, state recovery, append-only logs
2. **"I prioritize correctness over cleverness"** — schema contracts, validation at every boundary
3. **"I test at the boundary of real data"** — fixtures from production JSONL, not synthetic mocks
4. **"I know the limitations"** — 7 trades isn't proof of edge, paper trading isn't real trading
5. **"I optimize for debuggability"** — every action logged with timestamp, reason, and context
