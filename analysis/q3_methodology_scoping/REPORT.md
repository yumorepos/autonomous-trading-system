# Q3 Methodology Scoping Pass — Data-Source Feasibility Inventory

**Date**: 2026-04-28
**Scope**: Read-only inventory + feasibility assessment of the data sources the post-D50 narrowed Q3 design depends on. No methodology choice. No code or threshold change. Discharges the "Q3 methodology scoping" item flagged in the n=11 cohort walk session report.
**Cutoff anchor**: 2026-04-22T23:06:03Z (D46 deploy timestamp; "post-cutoff" throughout this report means `timestamp >= 2026-04-22T23:06:03Z`).
**Validation-phase rule**: honored. This artifact is observability output; it produces no methodology choice and no logic change.

---

## Section 0 — Provenance

### 0.1 VPS state snapshot (mandatory checkpoint)

Run: `ssh root@62.238.14.19 'bash /opt/trading/scripts/state_snapshot.sh'` at 2026-04-28 ~18:30 UTC.

```
=== 1. systemd ats-paper-trader ===
active

=== 2. git HEAD (/opt/trading) ===
3445fb8 observability: add scripts/state_snapshot.sh for single-round-trip VPS state read 2026-04-27

=== 3. /paper/status (paper trader, :8081) ===
{"orchestrator":{"started_at":"2026-04-27T19:57:41.918434+00:00","uptime_seconds":82407.0,"events_processed":11,"signals_actionable":2,"positions_opened":1,"positions_closed":1},"paper_trading":{"total_trades":38,"open_positions":1,"closed_positions":37,"total_pnl_usd":215.253,"total_funding_collected_usd":123.9392,"total_fees_paid_usd":45.0,"win_rate":0.6216,"avg_holding_hours":8.92,"best_trade_pnl":168.7689,"worst_trade_pnl":-224.0711},"open_positions":[{"position_id":"7bb0c533","asset":"CHIP","exchange":"hyperliquid","notional_usd":1000.0,"entry_funding_apy":185.09,"accumulated_funding_usd":0.2566,"accumulated_fees_usd":0.6,"net_pnl_usd":-0.3434,"funding_payments":27,"holding_hours":0.82,"entry_time":"2026-04-28T18:01:57.189430+00:00"}],"execution":{"enabled":true,"dry_run":true,"attempted":2,"succeeded":0}}

=== 4. /health (engine, :8080) ===
{"healthy": true, "status": "running", "heartbeat_age_seconds": 0.1, "scan_count": 282147, "regime": "LOW_FUNDING", "open_positions": 0, "uptime_seconds": 388654}
```

VPS HEAD `3445fb8` matches local `main` HEAD; one open position (CHIP `7bb0c533`, entry 2026-04-28T18:01:57Z).

### 0.2 Working-directory verification

```
$ pwd
/Users/yumo/Projects/autonomous-trading-system
$ git rev-parse HEAD
3445fb8c83befc4422b24ec77f315d9fa456cc75
```

### 0.3 Data sources interrogated (read-only)

| Source | VPS path | Local copy | Mutation? |
|---|---|---|---|
| signal_filter.db | `/opt/trading/data/signal_filter.db` | (read in-place via `sqlite3 file:?mode=ro`) | none |
| signal_log.db | `/opt/trading/data/signal_log.db` | `/tmp/signal_log.db` (scp pull) | none |
| execution_log.jsonl | `/opt/trading/data/execution_log.jsonl` | `/tmp/execution_log.jsonl` (scp pull) | none |
| paper_trades.jsonl | `/opt/trading/data/paper_trades.jsonl` | `/tmp/paper_trades.jsonl` (scp pull) | none |

All sqlite reads used `?mode=ro` URI flag. JSONL files were `scp`-pulled to `/tmp/` for analysis. No writes to the VPS data directory occurred.

---

## Section 1 — `signal_filter.db` schema dump + row counts

### 1.1 `signal_filter.db` — TRIPWIRE (already documented in MEMORY)

```
ls -la /opt/trading/data/signal_filter.db
-rw-r--r--  1 root root  0 Apr 27 21:53 /opt/trading/data/signal_filter.db
```

`signal_filter.db` is **0 bytes** (zero tables, no schema). Created 2026-04-27 21:53; never populated.

```
$ python3 -c 'import sqlite3; c = sqlite3.connect("file:/opt/trading/data/signal_filter.db?mode=ro", uri=True); cur=c.execute("SELECT name FROM sqlite_master WHERE type=\"table\"")  ; print([r[0] for r in cur])'
[]
```

The D50 narrowing pre-supposed `signal_filter.db` carried the rejected/accepted candidate stream with `composite_score`. **It does not.** The MEMORY block notes this at line 30 ("signal_filter.db is 0 bytes — actual live stream is signal_log.db"). This scoping pass confirms it from primary data.

### 1.2 `signal_log.db` — actual live signal-event stream

Verbatim `.schema` for the only data table (the other table is `sqlite_sequence`, a SQLite internal):

```sql
CREATE TABLE signal_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_utc TEXT NOT NULL,
    asset TEXT NOT NULL,
    exchange TEXT NOT NULL,
    new_regime TEXT NOT NULL,
    previous_regime TEXT NOT NULL,
    max_apy_annualized REAL,
    composite_score REAL,
    duration_survival_prob REAL,
    expected_duration_min REAL,
    liquidity_score REAL,
    net_expected_apy REAL,
    cross_exchange_spread REAL,
    is_actionable INTEGER,
    rejection_reason TEXT
)
```

**Schema reading**: this is a **regime-transition log**, not a per-cycle scorer log. Each row is a regime-transition event for a single asset (`new_regime` ≠ `previous_regime`, presumably). Decision-style columns:
- `composite_score` (REAL, NOT NULL across all 259 rows) — present on every event, the Q3 dependency.
- `is_actionable` (INTEGER, 0/1) — whether the event would have been forwarded to the executor.
- `rejection_reason` (TEXT, NULL when `is_actionable=1`) — populated only when the upstream filter rejects.
- No `cycle_id` or `scan_id` field. No way to tell which events were evaluated in the same scoring iteration.

### 1.3 Row counts (signal_log.db)

| Cohort | Count |
|---|---|
| Total | 259 |
| Pre-cutoff (`timestamp_utc < 2026-04-22T23:06:03Z`) | 157 |
| Post-cutoff (`timestamp_utc >= 2026-04-22T23:06:03Z`) | **102** |
| `composite_score IS NULL` | 0 |
| `composite_score IS NOT NULL` | 259 |

Post-cutoff distribution by `is_actionable`:

```
is_actionable=0 → 178 (total) ; 73 (post-cutoff approx — see below for full reason breakdown)
is_actionable=1 → 81 (total)  ; 29 (post-cutoff approx)
```

Post-cutoff `rejection_reason` distribution (all `is_actionable=0` rows):

| `rejection_reason` | post-cutoff count |
|---|---|
| `Regime is LOW_FUNDING, not HIGH_FUNDING` | 30 |
| `Regime is MODERATE, not HIGH_FUNDING` | 36 |
| `Regime is MODERATE, not HIGH_FUNDING; Liquidity score 0.00 < 0.15` | 3 |
| `Regime is MODERATE, ...; Composite score 34.3 < 35.0` | 1 |
| `Regime is MODERATE, ...; Composite score 34.4 < 35.0` | 1 |
| `Regime is MODERATE, ...; Composite score 34.6 < 35.0` | 1 |
| `Regime is MODERATE, ...; Composite score 34.8 < 35.0` | 1 |
| `Regime is MODERATE, ...; Composite score 34.9 < 35.0` | 1 |
| `Regime is MODERATE, ...; Composite score 35.0 < 35.0` | 1 |

**Critical reading**: every post-cutoff `signal_log.db` rejection is an *upstream-of-the-0.70-gate* filter (regime, liquidity, or 35.0 minimum-actionability composite). The post-D43 0.70 composite threshold (`Score 0.X < threshold 0.7`) does **not** appear in this stream.

### 1.4 One verbatim row per distinct decision type (post-cutoff)

`is_actionable=0` (most-recent post-cutoff row, REZ regime-transition rejected upstream):

```python
{
  'id': 259,
  'timestamp_utc': '2026-04-28T18:28:28.485807+00:00',
  'asset': 'REZ',
  'exchange': 'hyperliquid',
  'new_regime': 'LOW_FUNDING',
  'previous_regime': 'MODERATE',
  'max_apy_annualized': 59.34,
  'composite_score': 60.62,
  'duration_survival_prob': 0.9914,
  'expected_duration_min': 179.2,
  'liquidity_score': 0.5861,
  'net_expected_apy': 59.29,
  'cross_exchange_spread': 322.89,
  'is_actionable': 0,
  'rejection_reason': 'Regime is LOW_FUNDING, not HIGH_FUNDING'
}
```

`is_actionable=1` (most-recent post-cutoff actionable row, CHIP regime-transition that triggered the currently-open paper trade):

```python
{
  'id': 257,
  'timestamp_utc': '2026-04-28T18:01:57.189430+00:00',
  'asset': 'CHIP',
  'exchange': 'hyperliquid',
  'new_regime': 'HIGH_FUNDING',
  'previous_regime': 'LOW_FUNDING',
  'max_apy_annualized': 185.14,
  'composite_score': 66.54,
  'duration_survival_prob': 0.9888,
  'expected_duration_min': 134.6,
  'liquidity_score': 0.7368,
  'net_expected_apy': 185.09,
  'cross_exchange_spread': 122.5,
  'is_actionable': 1,
  'rejection_reason': None
}
```

Note: the CHIP `is_actionable=1` row carries `composite_score=66.54`, which is **below** the post-D43 0.70 executor gate. The paper trader nevertheless opened a position on this signal (position `7bb0c533`, see §4 join). This is the parallel-pipeline split that drives the D50 Q3 narrowing in the first place.

---

## Section 2 — `execution_log.jsonl` candidate-cycle structure

### 2.1 File scale and action types

`execution_log.jsonl` total rows: **71** over 2026-04-15 to 2026-04-28.

| Action | Count |
|---|---|
| `rejected` | 65 |
| `dry_run` | 6 |
| (no `accepted` action observed — system is `EXECUTION_DRY_RUN=True`, so the executor's accept-path emits `dry_run` instead.) | |

Keys present in any row: `['action', 'asset', 'details', 'dry_run', 'reason', 'signal_score', 'timestamp']`.

### 2.2 Cycle delimitation — there is none

The JSONL has **no `cycle_id`, `scan_id`, or `scan_timestamp` field**. Each row is a single per-event record. The "cycle" demarcator that the Q3 D50 narrowing assumed (per-cycle scorer output across all candidates in a multi-candidate cycle) **does not exist** in this stream's schema.

To check whether cycles are *inferable* from timestamp clustering: the smallest gap between any two consecutive post-cutoff `execution_log.jsonl` records is **2822.1 seconds (47 minutes)**.

Distribution of inter-record gaps (post-cutoff, n=26 gaps across 27 records):

| bucket | count |
|---|---|
| `<5s` | 0 |
| `5-30s` | 0 |
| `30s-2min` | 0 |
| `2-10min` | 0 |
| `10min-1h` | 2 |
| `>1h` | 24 |

There is no clustering at any tolerance ≤2 min. The engine emits at most one `execution_log.jsonl` record per scoring outcome per asset per regime-event — no parallel candidates are recorded.

### 2.3 Verbatim sample — one full record per action type

`action=dry_run` (the rare "would-have-executed" path; one of 6 historically, only one post-cutoff: CHIP 94.62 on 2026-04-23 — concurrency-blocked per MEMORY):

```json
{
  "action": "dry_run",
  "asset": "YZY",
  "reason": "DRY_RUN mode — would have executed",
  "signal_score": 90.83,
  "dry_run": true,
  "details": {
    "asset": "YZY",
    "exchange": "hyperliquid",
    "regime": "HIGH_FUNDING",
    "composite_score": 90.83,
    "score_normalized": 0.9083,
    "net_apy": 15679.95,
    "is_actionable": true,
    "duration_survival_prob": 0.9952,
    "liquidity_score": 0.5485,
    "position_size_usd": 10.0,
    "account_balance": 95.056564
  },
  "timestamp": "2026-04-15T19:04:28.537471+00:00"
}
```

`action=rejected` (verbatim, the most-recent post-cutoff record — paired to the CHIP OPEN at 18:01:57Z):

```json
{
  "action": "rejected",
  "asset": "CHIP",
  "reason": "Score 0.665 < threshold 0.7",
  "signal_score": 66.54,
  "dry_run": true,
  "details": {
    "asset": "CHIP",
    "exchange": "hyperliquid",
    "regime": "HIGH_FUNDING",
    "composite_score": 66.54,
    "score_normalized": 0.6654,
    "net_apy": 185.09,
    "is_actionable": true,
    "duration_survival_prob": 0.9888,
    "liquidity_score": 0.7368
  },
  "timestamp": "2026-04-28T18:02:00.500021+00:00"
}
```

### 2.4 Multi-candidate cycle inventory at standard tolerances

The stated Q3-D50 design wants "10 multi-candidate cycles where ≥2 candidates were scored in the same cycle." Empirically:

| tolerance | post-cutoff multi-candidate count (≥2 records within window) |
|---|---|
| 5 s | 0 |
| 30 s | 0 |
| 60 s | 0 |
| 120 s | 0 |

No multi-candidate cycle exists in `execution_log.jsonl` post-cutoff at any tolerance ≤2 minutes, regardless of how "cycle" is defined timing-wise. **This is a tripwire surface.**

---

## Section 3 — Post-cutoff cycle counts and throughput

### 3.1 Per-source post-cutoff totals

| Source | post-cutoff rows | span (days) | events/day |
|---|---|---|---|
| `signal_filter.db` | 0 (file is empty) | n/a | n/a |
| `signal_log.db.signal_log` | 102 | 5.81 | 17.56 |
| `execution_log.jsonl` | 27 | 5.78 | 4.67 |
| `paper_trades.jsonl` OPEN | 13 | 5.79 | 2.24 |

(Span for each row-bearing source uses the post-cutoff span from CUTOFF to the latest row in that source.)

### 3.2 Multi-candidate cycle counts (scope: post-cutoff only, no pre-cutoff pooling)

In both row-bearing sources, "multi-candidate cycle" interpreted as ≥2 records within a tolerance window:

| Source | tol=5s | tol=60s | tol=120s |
|---|---|---|---|
| `signal_log.db` | 0 | 0 | 0 (smallest gap is 121.89 s) |
| `execution_log.jsonl` | 0 | 0 | 0 (smallest gap is 2822.1 s) |

Multi-candidate-cycles-per-day post-cutoff: **0.00 / day** at every tolerance ≤120 s.

### 3.3 Pre-cutoff comparison (for context only — no pooling, no claim)

Pre-cutoff `execution_log.jsonl` has 44 rows over ~7.2 days = ~6.1 events/day. Same per-event schema, same lack of `cycle_id`. Pre-cutoff multi-candidate-cycle count is also 0 at any tolerance ≤120 s. The post-cutoff finding is not an artifact of post-cutoff thresholds — it reflects the engine's logging architecture across the full ledger.

### 3.4 Projected reachability of D51 thresholds

D51 pre-registration: PF_gated ≥ 1.30 AND **n_gated ≥ 10**, evaluated by n_primary = 50.

Sub-question: at observed throughput, when does the data hit n_primary = 50?

- `paper_trades.jsonl` OPEN cohort (the n_primary stream): 2.24/day → n=50 reached at CUTOFF + 50/2.24 ≈ 22.3 days = **2026-05-15** (matches MEMORY's "n=30 ETA 2026-05-06" projection at 2.24/day for n=30).
- D52 expected rate (3.4/day) would shorten this to ~14.7 days from cutoff = 2026-05-08.

Sub-question: at observed throughput, when does the data hit n_gated = 10?

- Multi-candidate cycles per day = 0 / day post-cutoff. **n_gated reachability is undefined** under any reasonable extrapolation; n_gated = 0 will hold at n_primary = 50 with high confidence, falling cleanly into the D51 fallback retire branch.

---

## Section 4 — Candidate-level join-key map across the three sources

### 4.1 Empirical join test: `paper_trades.jsonl` OPEN ↔ `execution_log.jsonl` rejected (asset + timestamp ±60 s)

All 13 post-cutoff OPEN events have a same-asset `execution_log.jsonl` record within ~5 s. Match table (verbatim, post-cutoff):

| OPEN entry_time | asset | position_id | execution_log delta (s) | execution_log action | composite_score |
|---|---|---|---|---|---|
| 2026-04-23T10:00:40 | CHIP | 1857064e | 3.1 | rejected | 68.84 |
| 2026-04-23T23:44:46 | STABLE | 25a68e79 | 2.2 | rejected | 57.53 |
| 2026-04-24T17:13:43 | SKR | 7af0648a | 4.1 | rejected | 64.24 |
| 2026-04-24T23:39:46 | APE | 95979efd | 3.5 | rejected | 66.85 |
| 2026-04-25T01:24:21 | YZY | 853aa7ce | 2.9 | rejected | 62.84 |
| 2026-04-25T09:09:41 | AXS | 811d1908 | 3.1 | rejected | 65.45 |
| 2026-04-25T10:15:56 | AXS | a31a3ccf | 4.1 | rejected | 65.39 |
| 2026-04-25T14:14:09 | HYPER | e4e90fe6 | 4.7 | rejected | 64.19 |
| 2026-04-25T15:01:12 | HYPER | 9999428c | 3.8 | rejected | 66.19 |
| 2026-04-26T06:05:54 | MINA | b5c4dbe9 | 3.5 | rejected | 62.74 |
| 2026-04-26T10:00:56 | HYPER | bb4114e1 | 3.5 | rejected | 65.53 |
| 2026-04-27T04:00:07 | BLAST | 2afbe5b6 | 3.3 | rejected | 55.22 |
| 2026-04-28T18:01:57 | CHIP | 7bb0c533 | 3.3 | rejected | 66.54 |

**Hit rate: 13/13 (100%) within 5-second tolerance on `(asset, timestamp)`**. This reproduces and extends the MEMORY-recorded "100% join coverage on (asset, entry_time ±60s)" finding.

The empirical join key is `(asset, timestamp_within_~5s)`. There is no shared UUID. Each OPEN is paired to exactly one execution_log record because the engine emits one `rejected` (or `dry_run`) record per regime-transition signal event per asset.

### 4.2 Cross-source join feasibility table

| Join | Empirical coverage post-cutoff | Limitation |
|---|---|---|
| `paper_trades.jsonl` OPEN → `execution_log.jsonl` (same asset, ts±5s) | 13/13 (100%) | None for accepted-side score retrieval |
| `paper_trades.jsonl` OPEN → `signal_log.db` (same asset, ts±5s) | not tested numerically here, but `signal_log.db` and `execution_log.jsonl` rejected entries appear to share emission moments (e.g., signal_log id=257 CHIP at 18:01:57.189 vs execution_log CHIP rejected at 18:02:00.500 — 3.3s delta; same asset, same regime transition) | Likely 100% coverage by construction (see §4.3) |
| `execution_log.jsonl` rejected (rejected by 0.70) → `signal_log.db` (same asset, ts±5s) | Inferred 1:1 by emission semantics | No verified count; would need explicit `JOIN ON asset AND timestamp_utc BETWEEN ts-5s AND ts+5s` |
| `execution_log.jsonl` rejected → hypothetical outcome (no actual trade was opened) | **NOT JOINABLE** | Rejected candidates with `composite_score < 0.70` that are *also* rejected by paper trader (no OPEN) have no outcome-side record. The counterfactual outcome cannot be observed. |

### 4.3 Architecture inference — parallel decoupled pipelines

The 100% same-asset, ~3-5s-delta pairing between `paper_trades.jsonl` OPEN and `execution_log.jsonl` rejected suggests the system has **two independent signal evaluators** triggered by the same regime-transition event:

1. **Paper trader path**: regime-transition fires → `signal_log.db` row (`is_actionable=1`) → paper_trader OPEN if its (laxer) gate passes → `paper_trades.jsonl` OPEN record. This path's gate is *not* the 0.70 composite threshold.
2. **Executor (dry_run) path**: same regime-transition event → executor scores it → 0.70 composite gate → emits `execution_log.jsonl` `rejected` (if score < 0.70) or `dry_run` (if score ≥ 0.70 and not concurrency-blocked).

Both paths share the regime-transition trigger, so they share `(asset, timestamp_utc)` to within their respective emission-latency windows (~3-5 s observed). They do **not** share a UUID.

Implication for Q3: the `composite_score` recorded on the `execution_log.jsonl` rejected row IS the candidate's score under the post-D43 0.70 executor gate — and the paper_trades OPEN gives the (eventually-observed) outcome of trading that same candidate. So the **cohort-level composite-vs-outcome calibration question** is fully joinable end-to-end. What's not joinable is multi-candidate intra-cycle competition, because no such structure exists in the data.

### 4.4 Schema gaps that block specific Q3 framings

| Q3 framing | Blocking schema gap |
|---|---|
| "Of N candidates scored in the same cycle, does the top-scored win more often?" | No `cycle_id` or `scan_id` field in any source. No timestamp clustering ≤2 min in either signal_log.db or execution_log.jsonl. The engine does not log multi-candidate cycles. |
| "Does the score discriminate the order in which a single candidate is selected vs deferred?" | No record of *unselected* candidates within a scan. Only the candidate that crossed an emission threshold gets a row. |
| "Among rejected candidates with `composite_score < 0.70`, what is the hypothetical PF if they had been opened?" | Counterfactual — no outcome data exists for rejected-but-not-opened events. Would require running rejected-candidate prices through a backtest engine; not a property of the live data alone. |
| "Among accepted candidates (paper_trades OPEN), does composite_score predict outcome?" | **No blocking gap.** `(asset, ts±5s)` join works at 100% coverage; outcome stream is `paper_trades.jsonl` CLOSE. |

---

## Section 5 — Feasibility verdict

**DOES_NOT_SUPPORT** the D50-narrowed Q3 design as-specified.

Evidence (each claim cited):

1. The data source named in the D50 narrowing — `signal_filter.db` — is structurally absent: 0 bytes, 0 tables, no `composite_score` column to compare on either side of a decision (Section 1.1). The MEMORY block at line 30 already flagged this; this scoping pass confirms it from primary data.
2. The substitute live source — `signal_log.db.signal_log` — is a regime-transition event log, not a per-cycle scorer log: it has no `cycle_id`, and its rejection reasons are upstream-of-the-0.70-gate filters (regime, liquidity, 35.0 minimum), not the post-D43 0.70 composite threshold (Section 1.2-1.4).
3. `execution_log.jsonl` has no cycle delimiter (Section 2.2) and no multi-candidate cycle at any tolerance ≤120 s in either pre-cutoff or post-cutoff data (Section 2.4, 3.2). Smallest post-cutoff inter-record gap is 2822 s (47 min); 24/26 gaps exceed 1 hour.
4. At the observed multi-candidate-cycle rate of **0.00 / day post-cutoff**, n_gated = 10 is unreachable at n_primary = 50 — the design pre-determines the D51 fallback retire branch (Section 3.4).
5. Operator may consider acting on D51 fallback retirement *now* on the grounds that the data architecture (not just the sample size) blocks the framing — waiting until n_primary = 50 will not change the multi-candidate cycle count from 0. The "wait for more data" branch of D51 was scoped on the assumption that the data structure could in-principle answer the question; this scoping pass shows that assumption is false. (This is feasibility evidence, not a methodology recommendation.)

The data **does** support a related-but-different framing — "does composite_score on accepted candidates predict outcomes" — at 100% join coverage on n=13 post-cutoff OPEN events (Section 4.1). That framing is distinct from the D50-narrowed Q3 design and would require an operator-authored D-entry to reframe the research question. This pass enumerates that option in §6 but does not choose it.

---

## Section 6 — Open methodology questions for the eventual Q3 D-entry skeleton

The operator owns the methodology choice. This section enumerates options surfaced by the inventory; it does **not** recommend one.

### 6.1 Reframing-related questions

1. **Should Q3 be retired (per D51 fallback) on architectural grounds rather than n-grounds?** §5 evidence suggests the multi-candidate intra-cycle framing is unanswerable absent an engine-side logging change. Triggering D51 fallback now skips ~17 calendar days of further sampling that cannot change the verdict.
2. **Should Q3 be reformulated to a feasibility-supported framing?** Two candidates surface from the inventory:
   - **(2a) Accepted-cohort calibration**: among paper_trades OPENs, does composite_score (recovered via §4.1 join) predict outcome? Already partially measured in MEMORY's G1 quartile inversion result (UNINFORMATIVE at n=11).
   - **(2b) Cross-pipeline gate-disagreement audit**: every post-cutoff OPEN was below the 0.70 executor gate (composite range 55.22–68.84). Q3 could ask "do paper-trader-accepted-but-executor-rejected candidates outperform / underperform a hypothetical executor-only stream?" This requires running a counterfactual on rejected events, which is beyond live data alone.
3. **Should Q3 retire and an entirely separate D-entry track the calibration question under a new label?** Avoids retro-fitting Q3's pre-registration to a different framing.

### 6.2 Logging-architecture questions (if Q3 is to be preserved as multi-candidate)

4. **Would adding a `cycle_id` field to `execution_log.jsonl` enable the D50 framing?** The required engine change: emit one record per evaluated candidate (not just the one crossing an emission threshold) with a shared `scan_iteration_id`. This is a code change and falls outside the validation-phase rule; would require a D-entry.
5. **Does the engine internally score multiple candidates per cycle?** Inventory cannot answer this from logs alone (logs only show emitted records). Would need code-path inspection of `engine/scanner.py` (or wherever the scoring loop lives) to determine whether multi-candidate scoring exists at runtime and is silently dropped vs. genuinely single-candidate-per-cycle.
6. **If multi-candidate scoring does exist internally, what is the appropriate `cycle_id` granularity?** Per scan iteration? Per regime-transition event? Per asset-universe sweep? The choice affects how Q3 measures "discrimination."

### 6.3 D51 pre-registration consistency questions

7. **Does the D51 `n_gated ≥ 10` requirement need to be reframed if Q3 is reformulated?** D51's PF_gated definition assumes a multi-candidate gating decision; a reformulated Q3 would need its own pre-registration thresholds.
8. **Does retiring Q3 imply a clean-up of D51's secondary framework (A/B/C skeleton noted in MEMORY) before the n=30 verdict task brief?** Or is the secondary framework independent of Q3 status?
9. **What is the disposition of the n=11 G1 cohort backtest (UNINFORMATIVE per MEMORY) under a Q3 reformulation?** It maps cleanly onto framing (2a) above, but if Q3 retires and (2a) becomes a new D-entry, the G1 result needs a clear home.

### 6.4 Validation-phase boundary questions

10. **Is engine-side logging change (item 4) a "bug fix / observability" change permitted under the validation-phase rule, or does it count as a scope expansion?** Adding fields to the existing JSONL stream may be observability; emitting new records (multi-candidate per cycle) shifts the data architecture and may not be.
11. **Should the Q3 D-entry skeleton require an operator-approved engine logging change as a precondition?** If so, the D-entry has a hard prerequisite that delays even the methodology choice until the prerequisite lands.

---

## Backlog-advancement one-liner (verbatim per session brief)

Q3 advanced: methodology scoping pass complete; feasibility verdict logged per analysis/q3_methodology_scoping/REPORT.md; D-entry skeleton drafting unblocked.

## Tripwires fired this pass

- **Post-cutoff multi-candidate cycle count is zero** — confirmed in both `signal_log.db` and `execution_log.jsonl` at every tolerance ≤120 s. Reported (does not change session scope; is the central feasibility finding).
- **`signal_filter.db` is materially different from D50 narrowing assumption** — it does not exist as a populated source (0 bytes, 0 tables). Already documented in MEMORY; re-confirmed here.

No other tripwires fired. `composite_score` is present on every signal_log.db row and every execution_log.jsonl row, so the "rejected events lack composite_score" tripwire did NOT fire — what's missing is multi-candidate cycle structure, not the score column.

## Pre/post-cutoff disclosure (no-pooling tripwire)

Every count and rate in this report explicitly carries its post-cutoff scope. Pre-cutoff comparison appears only in §3.3 and is labeled "for context only — no pooling, no claim." The 27 post-cutoff `execution_log.jsonl` rows, 102 post-cutoff `signal_log.db` rows, and 13 post-cutoff `paper_trades.jsonl` OPEN events are reported separately from their pre-cutoff complements and never aggregated.
