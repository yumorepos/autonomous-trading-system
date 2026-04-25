# D41 Primary + Q3 Live-Gate Evaluation

**Session date:** 2026-04-25
**Cohort cutoff (SAMPLE_CUTOFF_TS):** 2026-04-22T23:06:03+00:00 (per D46)
**Snapshot taken:** session start (paper_trades.jsonl 82 rows, execution_log.jsonl 57 rows)

**Headline:** D41 PRIMARY = **INSUFFICIENT** (n_post_cutoff_clean=9 < 30). Q3 = **EXTEND** (n_gated=0 < 10). Phase 3 tripwire fires on n_clean<28 numerically; the tripwire's diagnosis ("ledger drift or admin-row interpretation bug") is **wrong** — see Section 4. STOP-flagged commit, not pushed, pending operator review.

---

## 1. Session-open verification (Phase 0)

```
$ pwd && git remote -v
/Users/yumo/Projects/autonomous-trading-system
origin  https://github.com/yumorepos/autonomous-trading-system.git (fetch)
origin  https://github.com/yumorepos/autonomous-trading-system.git (push)

$ ssh root@62.238.14.19 'systemctl is-active ats-paper-trader'
active

$ ssh root@62.238.14.19 'cd /opt/trading && git log -1 --format="%h %s %cd" --date=short'
e066ae1 docs: record pre-fix timestamp cutoff for post-fix sample separation 2026-04-22

$ curl -s http://62.238.14.19:8081/paper/status
{"orchestrator":{"started_at":"2026-04-24T06:45:41.777758+00:00","uptime_seconds":134188.0,"events_processed":25,"signals_actionable":9,"positions_opened":7,"positions_closed":7},"paper_trading":{"total_trades":34,"open_positions":0,"closed_positions":34,"total_pnl_usd":207.3097,"total_funding_collected_usd":111.3622,"total_fees_paid_usd":40.8,"win_rate":0.6176,"avg_holding_hours":8.53,"best_trade_pnl":168.7689,"worst_trade_pnl":-224.0711},"open_positions":[],"execution":{"enabled":true,"dry_run":true,"attempted":9,"succeeded":0}}

$ ssh root@62.238.14.19 'tail -n 5 /opt/trading/data/paper_trades.jsonl'
[CLOSE AXS a31a3ccf 2026-04-25T11:05:57Z TRAILING_STOP +$23.90]
[OPEN HYPER e4e90fe6 2026-04-25T14:14:13Z]
[CLOSE HYPER e4e90fe6 2026-04-25T14:34:44Z TRAILING_STOP -$0.77]
[OPEN HYPER 9999428c 2026-04-25T15:01:16Z]
[CLOSE HYPER 9999428c 2026-04-25T15:07:28Z TRAILING_STOP +$30.85]
```

VPS service active, HEAD = e066ae1 (matches D46 canonical), latest close timestamp 2026-04-25T15:07:28Z (within 2h of query time). composite_score field present on all execution_log entries verified. All checkpoints clear.

---

## 2. Scanner error triage (Phase 1)

**Paper-trader systemd unit (07:00-11:00 window):** only benign `duration_predictor` warnings ("Only 0 samples for (AXS, HIGH_FUNDING) — using pooled distribution"). No exceptions, no missed cycles, no scanner errors.

**Trading-engine container (07:30-08:30 window):** 167 lines of WARNING `protect_capital: skipping cycle (ServerError: 502/504)`. All confined to **07:33:25 – 07:35:35** (≈130s burst). Last error 2026-04-25T07:35:35.534Z. No errors after 07:35:35 in window. The `protect_capital` task in the engine container is distinct from the paper-trader entry path; paper opens during this window were unaffected (next paper close at 09:09:42 → 11:05:57 AXS executed cleanly).

**Result: clean recovery, no compromised window.** Proceed.

---

## 3. Pre-registration verbatim quotes (Phase 2)

### D41 primary criterion (decision_log.md:497-502)
```
### Primary criterion — paper, RAW, comparable to backtest
GO requires ALL of:
- n_raw ≥ 30 clean closed paper trades
- PF_raw ≥ 1.30
- WR_raw ≥ 55%
- PF_raw_excl_worst_trade ≥ 1.30 (robustness against single-outlier dominance)
```

### Q3 pre-registration (decision_log.md:997-1003)
```
**Q3 pre-registration (effective 2026-04-24, binding before any real-money capital-enable flip):**
- Evaluation sample: post-SAMPLE_CUTOFF_TS paper_trades.jsonl closes (n ≥ 30 clean, consistent with D41 primary).
- Gate: PF computed over the subset where the contemporaneous composite_score (from signal_filter.db or execution_log.jsonl matched by (asset, entry_time)) was ≥ 0.70.
- Pass criterion: PF_gated ≥ 1.30 AND n_gated ≥ 10.
- If n_gated < 10 at n_primary = 30, extend validation to n_primary ≥ 50 before re-evaluating Q3. Do not retune.
- If PF_gated ≥ 1.30 but n_gated < 10 at n_primary = 50, retire Q3 as well (gate too rarely exercised to provide evidence) and flag for D-entry.
- If PF_gated < 1.30, Q3 is FAIL regardless of primary verdict. No real-money switch.
```

Both match the prompt's restatement; no disagreement to flag.

---

## 4. Post-cutoff sample extraction (Phase 3) — TRIPWIRE FIRED

### Counts
- Raw CLOSE rows in paper_trades.jsonl: **41**
- Admin reclassifications dropped: **7**
- Pre-cutoff (entry_time ≤ 2026-04-22T23:06:03Z) dropped: **25**
- **Post-cutoff clean: n = 9**

### Tripwire diagnosis is wrong
The prompt's expected n ≈ 31 was derived as "Telegram running counter 34 minus 3 pre-cutoff tail." That arithmetic assumed only 3 trades had entry_time ≤ cutoff. **Actual count is 25.** The shortfall is fully explained by entry-time chronology, not by ledger drift or admin filtering.

Verification:
- 7 admin rows enumerated; all have timestamps **2026-04-13 through 2026-04-16** (legacy YZY/DOT reclassifications: `admin_legacy_regime_exit_pre_d29`, `admin_stale_cleanup`, `admin_direction_bug_correction`, `admin_legacy_wrong_direction`). **Zero post-cutoff admin reclassifications.**
- Total non-admin closes: 41 − 7 = 34 = `/paper/status.closed_positions`. **Reconciles exactly.**
- Pre-cutoff non-admin entries opened on 2026-04-15 through 2026-04-22, including all 3 IDs cited by the prompt as "pre-cutoff opens at D46 deploy time" (SUPER 5e3e6386, MET 9c2a4367, CHIP f07cb5a2 — all confirmed not present in the post-cutoff cohort). The other 22 are trades that opened earlier in the validation window and either closed pre-cutoff or shortly after.
- Paper-trader open rate is consistent: pre-cutoff ~3.6 trades/day (25 / ~7d), post-cutoff ~3.4 trades/day (9 / 2.66d). No throughput collapse.

**Disposition:** the tripwire's numeric condition (n_clean < 28) is true, but its diagnostic premise is false. This is a **prompt-baseline error**, not a data defect. STOP-flagged commit per Phase 8; D-entry skeleton in Section 8.

### Post-cutoff cohort (n=9)
| entry_time | asset | position_id | net_pnl_usd | exit_reason |
|---|---|---|---|---|
| 2026-04-23T10:00:40Z | CHIP | 1857064e | -$15.37 | TRAILING_STOP |
| 2026-04-23T23:44:46Z | STABLE | 25a68e79 | +$23.66 | TRAILING_STOP |
| 2026-04-24T17:13:43Z | SKR | 7af0648a | +$35.34 | TRAILING_STOP |
| 2026-04-24T23:39:46Z | APE | 95979efd | +$160.73 | TAKE_PROFIT |
| 2026-04-25T01:24:21Z | YZY | 853aa7ce | -$2.74 | TRAILING_STOP |
| 2026-04-25T09:09:41Z | AXS | 811d1908 | +$1.82 | TRAILING_STOP |
| 2026-04-25T10:15:56Z | AXS | a31a3ccf | +$23.90 | TRAILING_STOP |
| 2026-04-25T14:14:09Z | HYPER | e4e90fe6 | -$0.77 | TRAILING_STOP |
| 2026-04-25T15:01:12Z | HYPER | 9999428c | +$30.85 | TRAILING_STOP |

---

## 5. D41 primary metric table + verdict (Phase 4)

| Metric | Value | Threshold | Pass? |
|---|---|---|---|
| n_clean | **9** | ≥ 30 | **FAIL (INSUFFICIENT)** |
| PF_raw | 14.6342 | ≥ 1.30 | (would pass) |
| WR_raw | 0.6667 (66.67%) | ≥ 0.55 | (would pass) |
| PF_raw_excl_worst | 78.6565 | ≥ 1.30 | (would pass) |
| PF_raw_excl_best | 6.1213 | (diagnostic only) | n/a |
| sum_pnl_usd | +$257.43 | — | — |
| mean_holding_h | 1.14 | — | — |
| median_holding_h | 0.34 | — | — |

**Holding by exit_reason:**
- TRAILING_STOP: n=8, mean=1.10h, median=0.31h
- TAKE_PROFIT: n=1, mean=1.47h, median=1.47h

**D41 PRIMARY VERDICT: INSUFFICIENT** — n=9 < 30 violates the gating criterion regardless of any other metric outcome. PF/WR diagnostics are reported for transparency only; they do not change the verdict.

### Worst trade (full ledger row)
```json
{"action":"CLOSE","position_id":"1857064e","asset":"CHIP","exchange":"hyperliquid","notional_usd":1000.0,"entry_funding_apy":116.5,"entry_price":0.108175,"direction":"long","peak_roe":0.023156921654726208,"current_roe":-0.014328634157614938,"price_pnl_usd":-14.328634157614939,"accumulated_funding_usd":0.1603887007744067,"accumulated_fees_usd":1.2,"funding_payments":7,"net_pnl_usd":-15.368245456840533,"entry_time":"2026-04-23T10:00:40.344492+00:00","entry_regime":"HIGH_FUNDING","timestamp":"2026-04-23T10:11:09.325942+00:00","exit_reason":"TRAILING_STOP","exit_price":0.106625,"exit_time":"2026-04-23T10:11:09.325897+00:00"}
```
Cross-check: entry_time 2026-04-23T10:00:40Z is strictly > cutoff 2026-04-22T23:06:03Z. ✓ Not a pre-cutoff member.

### Best trade (full ledger row)
```json
{"action":"CLOSE","position_id":"95979efd","asset":"APE","exchange":"hyperliquid","notional_usd":1000.0,"entry_funding_apy":101.27,"entry_price":0.18164,"direction":"long","peak_roe":0.16086765029729133,"current_roe":0.16086765029729133,"price_pnl_usd":160.86765029729133,"accumulated_funding_usd":1.0664657045629318,"accumulated_fees_usd":1.2,"funding_payments":47,"net_pnl_usd":160.7341160018543,"entry_time":"2026-04-24T23:39:46.354256+00:00","entry_regime":"HIGH_FUNDING","timestamp":"2026-04-25T01:07:56.567136+00:00","exit_reason":"TAKE_PROFIT","exit_price":0.21086,"exit_time":"2026-04-25T01:07:56.567109+00:00"}
```

### Single-outlier-dependence flag (interpretive)
APE +$160.73 represents 58.2% of total post-cutoff PnL ($160.73 / $276.31 gross_win). Without it, PF drops from 14.63 to 6.12. The diagnostic still passes the 1.30 threshold by a wide margin, so this is informational rather than dispositive — but the small sample is heavily right-skewed by one TAKE_PROFIT, and the operator should weigh that when the sample matures.

---

## 6. Q3 metric table + verdict (Phase 5)

### Join methodology
- Source: `analysis/q3_live_gate/execution_log.snapshot.jsonl` (preferred over signal_filter.db; explicit composite_score and score_normalized fields).
- Match: (asset, entry_time) with ±60s tolerance; pick closest by |delta|.
- Threshold comparison: `score_normalized ≥ 0.70` (gate runs in normalized 0-1 space; raw composite_score is 0-100).

### Coverage
- n_paper_closes = 9
- n_joined = **9**
- n_unmatched = **0**
- **join_coverage = 1.0000 (100%)**

All 9 paper closes matched within 2.16-4.70 seconds of an execution_log entry on the same asset. No join lossiness. No structural defect at the join layer.

### Joined gate-decision table
| asset | pid | entry_time_paper | exec_score_norm | gate_decision | net_pnl_usd | exec_action |
|---|---|---|---|---|---|---|
| CHIP | 1857064e | 2026-04-23T10:00:40Z | 0.6884 | FAIL | -$15.37 | rejected |
| STABLE | 25a68e79 | 2026-04-23T23:44:46Z | 0.5753 | FAIL | +$23.66 | rejected |
| SKR | 7af0648a | 2026-04-24T17:13:43Z | 0.6424 | FAIL | +$35.34 | rejected |
| APE | 95979efd | 2026-04-24T23:39:46Z | 0.6685 | FAIL | +$160.73 | rejected |
| YZY | 853aa7ce | 2026-04-25T01:24:21Z | 0.6284 | FAIL | -$2.74 | rejected |
| AXS | 811d1908 | 2026-04-25T09:09:41Z | 0.6545 | FAIL | +$1.82 | rejected |
| AXS | a31a3ccf | 2026-04-25T10:15:56Z | 0.6539 | FAIL | +$23.90 | rejected |
| HYPER | e4e90fe6 | 2026-04-25T14:14:09Z | 0.6419 | FAIL | -$0.77 | rejected |
| HYPER | 9999428c | 2026-04-25T15:01:12Z | 0.6619 | FAIL | +$30.85 | rejected |

### Q3 metrics
- **n_gated = 0** (no post-cutoff paper trade had score_normalized ≥ 0.70)
- **PF_gated = undefined** (no qualifying trades to compute over)
- score_normalized range observed: 0.5753 — 0.6884 (all below 0.70)

### Q3 VERDICT: EXTEND
Per pre-reg criterion (b): n_gated < 10 → extend to n_primary ≥ 50. Currently n_primary=9, so we are not yet eligible to apply the n_primary=50 retire-or-loosen condition.

### Architectural confirmation (not a defect)
`src/pipeline/live_orchestrator.py:277` reads: `# Open a new paper position (always, regardless of execution).` This is the documented design — paper trader opens on every actionable signal regardless of the executor's composite_score gate. Q3 measures the divergence by design; the live executor independently scored these same signals at <0.70 and recorded `rejected`. The 0% gate-pass rate in this 9-trade sample is therefore the Q3 question producing data, not a ledger or wiring bug.

---

## 7. Adversarial pass on non-PASS verdicts (Phase 6)

D41 PRIMARY = INSUFFICIENT and Q3 = EXTEND both require this pass per the session-open contract.

### Silent-failure mode 1: Admin reclassification silently consumed post-cutoff trades
**Hypothesis:** the admin filter is dropping trades that genuinely opened post-cutoff but were retroactively reclassified, masking real n_clean.
**Evidence (analysis/post_cutoff_sample/extract_summary.txt + admin row enumeration):** all 7 admin rows have `timestamp` between 2026-04-13 and 2026-04-16, well before the cutoff. Their exit_reason values are legacy fixes (`admin_legacy_regime_exit_pre_d29`, `admin_stale_cleanup`, `admin_direction_bug_correction`, `admin_legacy_wrong_direction`) — none of these correspond to any post-cutoff event. **Falsified.**

### Silent-failure mode 2: Cutoff arithmetic / timezone bug excludes valid post-cutoff trades
**Hypothesis:** `entry_time` parsing or strict-greater-than comparison silently drops trades that should be in the cohort.
**Evidence (analysis/post_cutoff_sample/post_cutoff_closes.jsonl + ledger tail):** the 9 retained trades match the entry_time chronology in the ledger (CHIP 1857064e at 10:00:40Z is the first post-cutoff entry; all subsequent CLOSEs follow in order through HYPER 9999428c at 15:01:12Z). All 9 entry_times verified strictly > 2026-04-22T23:06:03Z by direct comparison. /paper/status.closed_positions=34 = 41 raw − 7 admin, exact reconciliation. **Falsified.**

### Silent-failure mode 3: Paper-trader open throughput collapsed since cutoff
**Hypothesis:** the paper trader stopped opening as many trades after D46 deploy, yielding an artificially small n.
**Evidence (extract_summary.txt + entry_time distribution):** pre-cutoff = 25 closed trades over ~7 days = 3.6 trades/day. Post-cutoff = 9 closed trades over 2.66 days = 3.4 trades/day. Throughput is statistically indistinguishable. The execution_log also shows continuous actionable signals through 2026-04-25T15:01Z (most recent HYPER reject). The paper trader is firing on schedule. **Falsified.** The n=9 reflects "post-cutoff window has been short," not stalling.

### Residual unverified risks
1. **Q3 may be unanswerable in pre-reg form.** The 9-trade sample shows 0% gate-pass rate. If this rate persists, the n_primary=50 EXTEND threshold cannot satisfy n_gated≥10 either (would need 50 actionable signals, 20% of which pass the 0.70 gate — 10x current observed rate). This pushes the question toward Q3 pre-reg's "retire as well (gate too rarely exercised)" branch, not a PASS. Operator decision when n_primary=50 lands.
2. **Single-outlier dependence (APE +$160.73 = 58% of gross_win) may dominate any future PF computation** until the sample broadens. Already flagged in Section 5 — interpretive caveat for the operator, not a gate retune.
3. **The prompt's "~31 expected" baseline.** Future sessions using the same baseline arithmetic will re-fire this tripwire. The D-entry skeleton in Section 8 addresses this.

### Named bottleneck
**Q3** (paper/execution gating divergence). D41 primary reaches its n=30 threshold purely through paper-trader throughput (~9 trades/day from this rate → ~6 more days of accumulation). Q3's n_gated≥10 requirement at the observed 0% pass rate is the binding constraint and may not converge under current market regime + threshold combination. Per pre-reg, no retune; wait for n_primary=50 then trigger retire-or-revisit D-entry.

---

## 8. Routing per matrix (Phase 7) + D-entry skeleton

Per the routing matrix in the task brief: **D41 primary INSUFFICIENT (post-cutoff n < 30) → ledger reconciliation D-entry, NOT a verdict.**

### D-entry skeleton — for operator review (DO NOT append to decision_log.md in this session)

```
## D52 — Reconcile post-cutoff sample baseline arithmetic; clarify Telegram counter semantics

### Context
- D41/Q3 evaluation session 2026-04-25 reported n_post_cutoff_clean = 9 against
  a prompt-stated expectation of ~31 ("Telegram counter 34 minus 3 pre-cutoff tail").
- Phase 3 tripwire fired on n<28 with diagnosis "ledger drift or admin-row
  interpretation bug."
- Investigation (analysis/post_cutoff_sample/REPORT_D41_Q3.md §4) confirmed
  the data is structurally correct: 41 raw CLOSE − 7 admin (all timestamped
  2026-04-13 to 2026-04-16, legacy reclassifications) = 34 stat-counted; of
  those, 25 had entry_time ≤ 2026-04-22T23:06:03Z (the D46 cutoff) and only
  9 had entry_time > cutoff.
- The "3 pre-cutoff tail" cited in the prompt referenced only the 3 positions
  that were OPEN at D46 deploy time (SUPER 5e3e6386, MET 9c2a4367,
  CHIP f07cb5a2). The other 22 pre-cutoff entries closed BEFORE the deploy
  and are still in the append-only ledger; they correctly do not contribute
  to the post-cutoff cohort but DO inflate the Telegram running counter.

### Decision
1. Update task-brief baseline arithmetic in any future D41/Q3 evaluation
   session: post-cutoff n_clean expectation should be derived from
   (date.today() − 2026-04-22T23:06) * observed open rate, NOT from
   (Telegram_counter − 3).
2. Lower the Phase 3 tripwire threshold to n_clean < expected_open_rate
   * elapsed_days * 0.5 (50% of nominal accumulation rate). At current
   ~3.4/day this would have evaluated to ~5 not 28, and would not have
   fired.
3. (No code change.) Add a one-line note to operational_runbook.md
   clarifying that /paper/status.closed_positions and the Telegram
   running counter both report cumulative stat-counted closes, not the
   post-cutoff cohort.

### Rationale
- The tripwire's specified diagnosis ("ledger drift or admin-row bug")
  is non-falsifiable when the actual cause is task-brief arithmetic.
  Future sessions inheriting the same baseline will re-fire the tripwire
  identically, producing a STOP-flagged commit on a structurally clean
  ledger.
- The reconciliation is purely a documentation/baseline fix; no system
  state change is implied.

### Acceptance criteria
- Future D41/Q3 evaluation prompts derive expected n_post_cutoff_clean
  from open-rate × elapsed-time arithmetic, not from Telegram-minus-three.
- operational_runbook.md notes the counter semantics.

### Supersedes
- The Phase 3 tripwire arithmetic in the 2026-04-25 D41/Q3 evaluation
  task brief (this session).

### Unaffected
- D41 primary criteria (unchanged).
- Q3 pre-registration (unchanged).
- D46 pinned cutoff timestamp (unchanged).
- Paper-trader, executor, scorer (no code path touched).
```

### Routing summary
- **D41 primary = INSUFFICIENT** → reconciliation D-entry (D52 skeleton above) for operator review. **No verdict.**
- **Q3 = EXTEND** → continue paper accumulation; re-evaluate at n_primary=30, then n_primary=50 per Q3 pre-reg.
- **No PASS+PASS** → no escalation to D44 Path A/B / Phase 1 capital ramp.
- **No FAIL** → no NO-GO.
- **No code path touched.** No threshold change. No retune. Architectural confirmation that paper-trader opens regardless of gate (live_orchestrator.py:277) is the by-design Q3 question, not a defect — escalation override does NOT apply.

### Recommendation
None beyond the verdicts above. Operator decides next step post-report.

---

## Appendix — artifacts produced

- `analysis/post_cutoff_sample/extract.py` — cohort extractor
- `analysis/post_cutoff_sample/paper_trades.snapshot.jsonl` — VPS ledger snapshot
- `analysis/post_cutoff_sample/post_cutoff_closes.jsonl` — n=9 cohort
- `analysis/post_cutoff_sample/extract_summary.txt` — counts
- `analysis/q3_live_gate/execution_log.snapshot.jsonl` — VPS exec-log snapshot
- `analysis/q3_live_gate/join.py` — (asset, entry_time) joiner
- `analysis/q3_live_gate/joined_trades.jsonl` — n=9 with composite_score, gate_decision
- `analysis/q3_live_gate/join_summary.txt` — coverage/gate-pass counts
