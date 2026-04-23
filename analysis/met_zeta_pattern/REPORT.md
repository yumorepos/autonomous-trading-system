# Joint Pattern Analysis — Three ≥$100 Single-Trade Losses

**Scope:** D40 pre-registered pattern-analysis review, triggered by three single-trade losses exceeding $100 in the paper-trading ledger.
**Date:** 2026-04-23
**Data:** `/opt/trading/data/paper_trades.jsonl` (n=25 clean closes, md5 `3e0ac2c13bedf1e07546e4e652404dc0`), `/opt/trading/data/execution_log.jsonl` (46 entries last 14d), journalctl poll extractions.
**Mode:** Read-only. No config / strategy / code changes. Unstaged output for operator review.

---

## Verdict

**Question:** Is MET a statistical outlier asset that should be blacklisted post-gate, or is the 2/2 loss pattern within the noise envelope?

**Answer: UNKNOWN — data does not support a blacklist decision.**

The 2/2 MET loss pattern is within the noise envelope given n=2 per-asset trades and 60% aggregate win rate (P(2L|WR=60%) = 16%, expected 0.96 such assets among 6 multi-trade assets → observed 1). Entry-time features (composite_score 0.656/0.660, net_apy 101.75/110.35, liquidity_score 0.680/0.688, regime HIGH_FUNDING, duration_survival 0.989) are **indistinguishable** from winning trades on other assets (BLUR 5W/0L at liq 0.649, YZY 4W/5L at liq 0.535). No asset-specific feature in the log stream separates MET from winners. The pattern is statistically consistent with an unlucky draw of 2 trades on a 40%-loss-rate population.

**What is NOT unknown:** the loss *mechanisms* (cadence-cliff on dbccdc0b, pure drawdown on 9c2a4367) and the fact that ZETA 6a9884c4 has an **identical** pure-drawdown signature. This signature is not MET-specific.

**Recommendation:** Do NOT blacklist MET. Continue per D40 pre-reg to n≥25–30 (currently n=25). Re-evaluate if a 4th MET trade produces a 3rd ≥$100 loss (conditional probability would drop materially). If operator wishes to act on per-asset concentration flags pre-gate, a formal amendment is required — mid-sample blacklist is a parameter change under D40.

---

## Section 1 — Reconstruct Each Loss

Ledger records (from `/opt/trading/data/paper_trades.jsonl`):

| Trade | Asset | Open ts (UTC) | Close ts (UTC) | Hold | Exit | peak_roe | Net PnL |
|---|---|---|---|---|---|---|---|
| 6a9884c4 | ZETA | 2026-04-17T16:03:19 | 2026-04-18T16:04:12 | 24h 0m | TIMEOUT | 0.0000 | **−$116.76** |
| dbccdc0b | MET | 2026-04-22T02:32:10 | 2026-04-22T02:52:31 | 0h 20m | STOP_LOSS | 0.0069 | **−$224.07** |
| 9c2a4367 | MET | 2026-04-22T07:01:18 | 2026-04-23T07:03:17 | 24h 2m | TIMEOUT | 0.0000 | **−$129.88** |

(ZETA ID in original D38 report was "2a8f…" — ledger-canonical position_id is `6a9884c4`. Confirmed only one ZETA TIMEOUT loss at −$116.76 in the ledger.)

**Loss signatures:**

- **ZETA 6a9884c4**: pure-drawdown. peak_roe 0.0 means price never moved in our favor after entry. 24h hold, TIMEOUT at expiry. Journalctl poll data (729 samples): min −13.05%, max 0.00%, largest single-step gap 2.47pp over 123s. Envelope-consistent loss.
- **MET dbccdc0b**: cadence-cliff. 20-minute hold, SL triggered. Peak +0.69% briefly. Poll extractions show a gap from +0.04% to −22.30% in ~2 minutes, past the −15% SL threshold. Envelope-expanding.
- **MET 9c2a4367**: pure-drawdown, identical signature to ZETA 6a9884c4. peak_roe 0.0, 24h hold, TIMEOUT. Journalctl (726 samples): min −14.31% at 05:39:43 (never breached −15% SL), max +0.07%, largest real gap 3.17pp over 3s. Envelope-consistent.

**Control win on same asset, same day** (ZETA 5a9bce7e): opened 2026-04-17T02:05, closed T02:22 (17 min TRAILING_STOP), peak_roe 0.072, +$44.68. Same asset, ~14 hours earlier, opposite outcome with similar entry features.

---

## Section 2 — Execution-Log Join

All three losing trades matched cleanly in `/opt/trading/data/execution_log.jsonl` via `(asset, open_ts ±30s)` join.

| Trade | Asset | Action | composite_score | net_apy | liquidity_score | duration_survival | regime |
|---|---|---|---|---|---|---|---|
| 6a9884c4 | ZETA | rejected | **0.6444** | 104.38 | 0.6236 | 0.9888 | HIGH_FUNDING |
| dbccdc0b | MET  | rejected | **0.6598** | 110.35 | 0.6797 | 0.9888 | HIGH_FUNDING |
| 9c2a4367 | MET  | rejected | **0.6555** | 101.75 | 0.6882 | 0.9888 | HIGH_FUNDING |

**All three were below the executor's 0.70 composite_score gate** and would NOT have been opened in real-money execution. They entered the ledger because `scripts/run_paper_trading.py` opens every signal the engine emits regardless of score. The 0.70 cutoff is enforced only inside `Executor.execute_trade` (`min_score=0.70`), which was correctly suppressing all three (action="rejected", not "dry_run").

**Gate-consistency tripwire PASS:** no score ≥0.70 was rejected; no score <0.70 reached dry_run. The gate logic is behaving as designed.

**Retroactive gate partition (n=25 clean closes, via `/tmp/join_gate.py`):**
- GATED (score ≥0.70): n=2 — STABLE +$20.41 (score 0.7089), SUPER −$26.34 (score 0.8831). PF 0.78, WR 50%.
- UNGATED (score <0.70): n=23 — all three ≥$100 losses here, plus the +$168.77 BLUR winner and all other profitable trades.
- **The three flagged losses are all in the UNGATED bucket.** In a real-money world where only GATED trades execute, these losses would not exist in the sample.

---

## Section 3 — Asset-Level Base Rates (Last 14 Days, from execution_log)

`scan_found_signals` events in `trading_engine.jsonl` contain only `{event, count, timestamp}` — no per-asset detail. Base rates computed from `execution_log.jsonl` as explicitly authorized in the brief (proxy for signals that reached executor evaluation).

| Asset | exec entries | ≥0.70 | Ledger opens | Conv rate | Score mean | Score max | liq mean | liq min |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| YZY   | 19 | 3 | 9 | 47.4% | 0.6529 | 0.9083 | 0.5354 | 0.4948 |
| BLUR  | 6  | 0 | 5 | 83.3% | 0.6413 | 0.6657 | 0.6493 | 0.6126 |
| SUPER | 4  | 1 | 3 | 75.0% | 0.7025 | 0.8831 | 0.5974 | 0.5760 |
| CHIP  | 4  | 1 | 3 | 75.0% | 0.7358 | 0.9462 | 0.7772 | 0.7559 |
| **ZETA**  | **2**  | **0** | **2** | **100.0%** | **0.6420** | **0.6444** | **0.5957** | **0.5677** |
| **MET**   | **2**  | **0** | **2** | **100.0%** | **0.6577** | **0.6598** | **0.6840** | **0.6797** |

**Findings:**
- MET is NOT over-represented in the scanner stream — 2/46 entries = 4.3% (vs YZY 41%, BLUR 13%, SUPER 9%, CHIP 9%).
- MET has the **highest liquidity_score in the multi-trade focus group** (0.684 mean). "Low liquidity" does NOT explain the MET losses.
- MET's max composite_score (0.660) never reached the executor gate. Same for ZETA (0.644) and BLUR (0.666). All three are "borderline" signal populations.
- BLUR is 5W/0L on the same score / same liquidity range as MET (0W/2L). **Same feature profile, opposite outcome** — direct evidence that entry-time features in this log stream do not discriminate winners from losers for borderline-score assets.

**Multi-trade asset win/loss distribution (n≥2 trades):**

| Asset | W | L | PnL | Note |
|---|---:|---:|---:|---|
| BLUR  | 5 | 0 | +$124.38 | All TRAILING_STOP or TP |
| CHIP  | 3 | 0 | +$128.76 | All TRAILING_STOP |
| YZY   | 1 | 2 | +$47.80 | 1 funding-win (+$16.59) covers net |
| SUPER | 0 | 3 | −$92.44 | All small losses |
| ZETA  | 1 | 1 | −$72.08 | Split outcome |
| **MET** | **0** | **2** | **−$353.95** | **Both ≥$100 losses — unique** |

MET's uniqueness is **loss magnitude**, not loss frequency. SUPER is 0/3 too, but dollar-loss is 4× smaller. What makes MET distinctive is that both losses exceeded $100 — not that it lost twice.

---

## Section 4 — Intra-Hold Price Trajectories

Poll-data extractions from `journalctl` for the paper-trader process. ROE values quoted are the paper-trader's realized-price basis (entry funding-adjusted, not leveraged notional).

### ZETA 6a9884c4 (TIMEOUT −$116.76)
- 729 samples over 24h, polled every ~2 min.
- Open ROE 0.00%, close ROE −13.05% (TIMEOUT at expiry, not SL).
- Peak ROE 0.00% — price never moved favorably.
- Largest single-interval gap: **2.47pp over 123s**. No cadence-cliff. Smooth negative drift.
- **Classification: envelope-consistent.** Normal adverse-price-path loss.

### MET dbccdc0b (STOP_LOSS −$224.07)
- Short hold: 20 minutes, 10 samples.
- Peak ROE +0.69% at T02:38:16 (6 min after entry).
- Sequence to SL: +0.04% → jumped to **−22.30% in ~2 minutes** → SL triggered at T02:52:31.
- Gap size **22.34pp between consecutive polls**, far beyond the −15% SL threshold.
- **Classification: cadence-cliff / envelope-expanding.** The poll interval was unable to observe intermediate prices; the SL was applied at the next-polled price which had already moved past threshold. Documented as D40 "cadence-driven SL overrun."
- **This is the only cadence-cliff in the 3-loss set.**

### MET 9c2a4367 (TIMEOUT −$129.88)
- 726 samples over 24h.
- Open ROE 0.00%, close ROE −13.00%. Peak +0.07%, min **−14.31%** at T05:39:43 (~22h into the hold — never breached −15% SL).
- Largest real gap: 3.17pp over 3s (near entry). Otherwise smooth.
- **Classification: envelope-consistent.** Identical signature to ZETA 6a9884c4: 24h pure-drawdown, peak_roe 0.0, no cadence issue.

**Pattern:** 2 of 3 losses are envelope-consistent pure-drawdown paths (ZETA 6a9884c4 + MET 9c2a4367). 1 of 3 is cadence-cliff (MET dbccdc0b). The pure-drawdown pattern is NOT MET-specific — ZETA shares it exactly.

---

## Section 5 — MET Liquidity Cross-Reference

Feature profile at entry for the two MET trades:

| Metric | MET dbccdc0b | MET 9c2a4367 | Sample mean (all focus) |
|---|---:|---:|---:|
| composite_score | 0.6598 | 0.6555 | ~0.66 |
| net_apy | 110.35 | 101.75 | 108.93 (ZETA), 106.05 (MET), 15679 / 104.84 (YZY) |
| liquidity_score | 0.6797 | 0.6882 | 0.5957 (ZETA), 0.6493 (BLUR), 0.5974 (SUPER) |
| duration_survival_prob | 0.9888 | 0.9888 | 0.9888 (HF regime default) |
| regime | HIGH_FUNDING | HIGH_FUNDING | HIGH_FUNDING |

**MET liquidity_score (0.68) is ABOVE the median** of last-14-day focus-group entries (0.60). Liquidity is not the defect.

**Temporal clustering:** Both MET entries occurred on 2026-04-22, within 4h 29m of each other:
- dbccdc0b at 02:32 UTC (funding window ~02:00 UTC)
- 9c2a4367 at 07:01 UTC (funding window ~06:00 UTC)

Both entries were triggered by consecutive adverse-funding windows on the same asset, on the same calendar day, separated by a single 4-hour interval. Under the D44 MAX_CONCURRENT=1 enforcement (deployed 2026-04-22T23:21:11Z, **after** both MET entries), the second entry would have been blocked **if the first were still open** — but dbccdc0b closed at 02:52, four hours before 9c2a4367 opened, so concurrency control would not have prevented the second entry even retroactively.

**Regime-correlation hypothesis (not tested here):** both MET losses fell on the same day during a period where the HIGH_FUNDING regime for MET was repricing. This is a single macro-event observation, not an asset-defect signal. Testing would require same-asset multi-day samples which we do not have.

---

## Summary Table

| Dimension | ZETA 6a9884c4 | MET dbccdc0b | MET 9c2a4367 |
|---|---|---|---|
| Entry ts | 2026-04-17T16:03 | 2026-04-22T02:32 | 2026-04-22T07:01 |
| Hold | 24h (TIMEOUT) | 20 min (STOP_LOSS) | 24h (TIMEOUT) |
| Net PnL | −$116.76 | −$224.07 | −$129.88 |
| peak_roe | 0.0% | +0.69% | 0.0% |
| composite_score | 0.6444 | 0.6598 | 0.6555 |
| Exec action | rejected (<0.70) | rejected (<0.70) | rejected (<0.70) |
| net_apy at entry | 104.38 | 110.35 | 101.75 |
| liquidity_score | 0.6236 | 0.6797 | 0.6882 |
| Loss mechanism | envelope-consistent drawdown | cadence-cliff | envelope-consistent drawdown |
| Matching control | ZETA 5a9bce7e +$44.68 same day | — | — |
| Under real-money gate? | Would NOT have been opened | Would NOT have been opened | Would NOT have been opened |

---

## Tripwires — all scanned

1. **Ledger monotonicity**: ✓ PASS. All OPEN/CLOSE timestamps strictly non-decreasing; no rewrites, no retroactive edits.
2. **composite_score gate consistency**: ✓ PASS. No score ≥0.70 rejected; no score <0.70 executed as dry_run. The 3 losses all correctly rejected by executor.
3. **MET trade count**: ✓ PASS. Exactly 2 MET trades in the ledger (dbccdc0b, 9c2a4367). No third phantom position.
4. **Post-cutoff concurrency**: ✓ PASS (reload-exemption). One post-cutoff interval had 2 open positions from a paper-trader restart-reload, not from a new-open violation. D44 MAX_CONCURRENT=1 is enforcing correctly on new opens.
5. **Half-landed D43 state**: ✓ NOTED (separate D44 memo). Engine container still on pre-D43 code (× 3 × 365 annualization, threshold 1.00); host paper trader on post-D43 (× 24 × 365, threshold 8.00). Selection invariant `|r| ≥ 1/1095` preserved algebraically. Affects readability of `entry_funding_apy` in the ledger (8× understated in absolute terms) but not sample semantics.

No tripwire failed.

---

## What this analysis does NOT establish

- Whether MET has an underlying market-microstructure defect (repeated SL-targeting liquidation waterfalls, MM withdrawals during funding windows, etc.) — would require order-book-level data beyond the current log stream.
- Whether other un-opened MET scan emissions exist — `scan_found_signals` lacks per-asset detail; we can only see MET entries that reached executor evaluation (n=2, both opened).
- Whether the 4h 29m temporal clustering reflects a cross-exchange basis squeeze or a coincidence. A single 2026-04-22 MET event-window cannot be distinguished from asset-defect with the current sample.

These gaps are noted, not filled. No parameter, threshold, or blacklist action recommended at this time.

---

## Links / Provenance

- Ledger: `/opt/trading/data/paper_trades.jsonl` md5 `3e0ac2c13bedf1e07546e4e652404dc0` (64 lines, 25 clean closes)
- Exec log: `/opt/trading/data/execution_log.jsonl` (46 entries, last 14d)
- Retroactive gate join script: `/tmp/join_gate.py`
- Base-rates script: `/tmp/base_rates.py`
- Liquidity-stats script: `/tmp/liquidity_stats.py`
- Paper trader service: systemd `ats-paper-trader` ACTIVE since 2026-04-22T23:21:11Z
- Deployed commit (host): `e066ae1`
- Pre-reg authority: D40 (n=20 gate cleared NO-GO → WAIT/extend) + D41 primary/secondary framework
