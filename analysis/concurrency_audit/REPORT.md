# Concurrency Audit — MAX_CONCURRENT=1 Enforcement Gap

**Author:** Claude Code (main-chat)
**Date:** 2026-04-22 UTC
**Scope:** diagnose the live MAX_CONCURRENT=1 violation; enumerate every historical concurrent-open window in the paper ledger; quantify D41 PF 1.063 contamination.
**Disposition:** READ-ONLY diagnosis. No live-pipeline or risk-param edits.
**Fresh snapshot:** `analysis/snapshots/20260422T202943Z/paper_trades.jsonl`
sha256 `5a85d8216d94885b9dc91bf77407590b8f6e6eea77e97e44313887aa239aeab0`, 59 lines.

---

## 1. Fresh snapshot and drift

| Snapshot | Lines | sha256 (short) | Notes |
|:-|-:|:-|:-|
| `20260422T165151Z/paper_trades.jsonl` | 58 | `d2000d4…` | Prior pin (D45 volume-filter audit) |
| `20260422T202943Z/paper_trades.jsonl` | 59 | `5a85d82…` | Fresh pull at session start |

**Drift:** +1 event, a single new `OPEN` for CHIP position `2369fe29` at 2026-04-22 20:08:38 UTC (entry funding APY 115.6%, notional $1,000, long, dry_run).
This is the **third** concurrent open — not the 2 cited in the task brief.

---

## 2. Live overlap (as of 2026-04-22 20:29 UTC — snapshot time)

| # | Asset | pid[:8] | Opened (UTC) | Age (h) | Entry funding APY | Notional |
|-:|:-|:-|:-|-:|-:|-:|
| 1 | SUPER | `5e3e6386` | 2026-04-22 01:01:12 | **19.59** | 130.7% | $1,000 |
| 2 | MET   | `9c2a4367` | 2026-04-22 07:01:15 | **13.59** | 56.9% | $1,000 |
| 3 | CHIP  | `2369fe29` | 2026-04-22 20:08:38 | **0.47**  | 115.6% | $1,000 |

Entry gaps: SUPER→MET **6.00h**, MET→CHIP **13.12h**.
Three concurrent open positions — explicitly violates `config/risk_params.py:30`’s `MAX_CONCURRENT = 1`.

---

## 3. Historical overlap windows (all 31 positions)

Total positions: 31 OPEN, 28 CLOSE, **3 STILL_OPEN**.
Clean-close cohort (non-`admin_*`): **21** — matches memory’s D41 n=21.

### 3a. Pairwise overlap counts

| Kind | Count |
|:-|-:|
| All pairwise overlap windows | **39** |
| Clean × clean (D41 PF contamination domain) | **23** |
| Admin × * (excluded from D41 PF) | 16 |

The paper trader has **never enforced 1-at-a-time** in its operating history. Even in the early admin-closed segment (YZY cascade of 2026-04-14/15), up to 3 YZY OPENs coexisted (see §3b).

### 3b. All 23 clean × clean overlap pairs

| Pair | Overlap start (UTC) | Dur (h) | PnL A | PnL B |
|:-|:-|-:|-:|-:|
| YZY `27807f30` TIMEOUT || BLUR `20498ca7` TRAILING | 04-15 23:02 | 0.78 | −16.87 | +1.37 |
| YZY `27807f30` TIMEOUT || BLUR `d89f5b97` TRAILING | 04-16 01:08 | 0.87 | −16.87 | +17.44 |
| YZY `27807f30` TIMEOUT || BLUR `eaa613da` TIMEOUT | 04-16 03:39 | 18.37 | −16.87 | −44.86 |
| YZY `27807f30` TIMEOUT || ALT `c6dcaad7` TRAILING | 04-16 06:05 | 0.51 | −16.87 | +50.12 |
| BLUR `eaa613da` TIMEOUT || ALT `c6dcaad7` TRAILING | 04-16 06:05 | 0.51 | −44.86 | +50.12 |
| BLUR `eaa613da` TIMEOUT || SAGA `7b699cd5` TRAILING | 04-16 23:48 | 3.87 | −44.86 | +64.85 |
| BLUR `eaa613da` TIMEOUT || ZETA `5a9bce7e` TRAILING | 04-17 02:05 | 0.28 | −44.86 | +44.68 |
| SAGA `7b699cd5` TRAILING || ZETA `5a9bce7e` TRAILING | 04-17 02:05 | 0.28 | +64.85 | +44.68 |
| ZETA `6a9884c4` TIMEOUT || YZY `5139882d` TIMEOUT | 04-17 17:12 | 22.86 | −116.76 | +16.59 |
| ZETA `6a9884c4` TIMEOUT || STABLE `79582b07` TRAILING | 04-18 02:00 | 14.06 | −116.76 | +20.41 |
| ZETA `6a9884c4` TIMEOUT || BLAST `4a7325eb` TIMEOUT | 04-18 08:00 | 8.06 | −116.76 | −10.45 |
| YZY `5139882d` TIMEOUT || STABLE `79582b07` TRAILING | 04-18 02:00 | 15.21 | +16.59 | +20.41 |
| YZY `5139882d` TIMEOUT || BLAST `4a7325eb` TIMEOUT | 04-18 08:00 | 9.22 | +16.59 | −10.45 |
| STABLE `79582b07` TRAILING || BLAST `4a7325eb` TIMEOUT | 04-18 08:00 | 16.07 | +20.41 | −10.45 |
| STABLE `79582b07` TRAILING || YZY `7e776a5f` TRAILING | 04-18 19:01 | 5.05 | +20.41 | +48.09 |
| BLAST `4a7325eb` TIMEOUT || YZY `7e776a5f` TRAILING | 04-18 19:01 | 12.99 | −10.45 | +48.09 |
| BLAST `4a7325eb` TIMEOUT || BLUR `8868dc37` TAKE_PROFIT | 04-19 05:03 | 0.62 | −10.45 | +168.77 |
| YZY `7e776a5f` TRAILING || BLUR `8868dc37` TAKE_PROFIT | 04-19 05:03 | 0.62 | +48.09 | +168.77 |
| YZY `7e776a5f` TRAILING || MOVE `44dd7709` TRAILING | 04-19 13:24 | 0.31 | +48.09 | +9.07 |
| BLUR `f5800447` TIMEOUT || SUPER `0e490bc6` TRAILING | 04-20 05:51 | 0.44 | −18.33 | +11.10 |
| BLUR `f5800447` TIMEOUT || SUPER `a46950ac` TIMEOUT | 04-20 14:02 | 6.17 | −18.33 | −77.21 |
| SUPER `a46950ac` TIMEOUT || UMA `fcdda50b` TRAILING | 04-21 05:41 | 0.85 | −77.21 | −2.88 |
| SUPER `a46950ac` TIMEOUT || BIO `d77d734b` TRAILING | 04-21 07:02 | 0.72 | −77.21 | +36.29 |

**Every non-trivial clean close in the ledger shared wall-clock time with at least one other clean or admin position.** The n=21 cohort is pervasively contaminated — only the earliest few YZY admin-cascade trades were effectively sequential, and those are excluded from the clean subset anyway.

---

## 4. Enforcement-point inventory

| Layer | File:line | Threshold | Field compared | Action on violation | Reachable in paper path? |
|:-|:-|:-|:-|:-|:-:|
| L1 — tiered scanner | `scripts/tiered_scanner.py:48–113` | *none* | *none* | *none* (pure signal ranker) | ✅ (runs, no gate) |
| L2 — signal filter pipeline | `src/pipeline/signal_filter.py` | *none* | *none* | *none* | ✅ (runs, no gate) |
| L3 — live orchestrator pre-call | `src/pipeline/live_orchestrator.py:271` | duplicate-asset only | `has_open_position(asset, exchange)` | skip + log | ✅ (runs, per-asset only — not per-count) |
| **L4 — paper trader simulator** | **`src/simulator/paper_trader.py:309`** | **`self.max_open_positions` = 5** | **`len(self.open_positions)`** | **return None + log** | **✅ (the only count-based gate in the paper path)** |
| L5 — executor (real-trade) | `src/execution/executor.py:244` | `MAX_CONCURRENT = 1` | `len(open_positions)` on HL | return False | ⚠ only when `dry_run=False`. Runs AFTER paper opens already persisted. |
| — regime-default | `config/regime_thresholds.py:52–67` | CALM 3 / MOD 2 / HIGH 1 / EXT 1 | regime_detector output | *consumer must enforce* | ❌ (paper trader does not consume these) |
| — legacy CLI | `scripts/trading_engine.py:918` | `MAX_CONCURRENT = 1` | `state.data["open_positions"]` | skip + log | ❌ (not the live service — ATS uses paper_trader) |
| — HL-entry test script | `scripts/hl_entry.py:66,251` | `MAX_CONCURRENT = 2` | `perp["positions"]` | return False | ❌ (unrelated script) |

### 4a. The drift

- `config/risk_params.py:30` declares `MAX_CONCURRENT = 1` as the "single source of truth".
- `config/config.yaml:78` declares `max_open_positions: 5`.
- `scripts/run_paper_trading.py:71–73` reads `sim_cfg.get("max_open_positions", 5)` and passes it into `PaperTrader(max_open_positions=5, …)`.
- `src/simulator/paper_trader.py:40` default is `max_open_positions: int = 5`.
- `PaperTrader.open_position` uses `self.max_open_positions` — **never reads `config.risk_params.MAX_CONCURRENT`.**

**Two constants, same conceptual meaning, different values, and the paper trader is wired to the larger one.** The executor reads the smaller one but is (a) bypassed in `dry_run=True` for effective state changes and (b) executes *after* paper persistence.

---

## 5. Specific path for MET signal 9c2a4367 (2026-04-22 07:01 UTC)

At the moment MET was opened, SUPER `5e3e6386` (opened 06:00 earlier) was held.

| Step | Code | Observed behavior |
|:-|:-|:-|
| 1. Regime transition event for MET | `ATSConnector.watch()` → orchestrator | raised as `RegimeTransitionEvent` |
| 2. Pipeline scoring | `SignalFilterPipeline.process()` | `is_actionable=True` (no concurrency arg) |
| 3. Duplicate-asset check | `live_orchestrator.py:271` `has_open_position("MET", "hyperliquid")` | **False** (SUPER is a different asset) — passes |
| 4. Mid-price fetch | `_get_mid_prices()` | MET price resolved |
| 5. `paper_trader.open_position(...)` | `paper_trader.py:309` `len(self.open_positions) >= self.max_open_positions` → `1 >= 5` | **False** — gate lets MET through |
| 6. Persist OPEN event | `paper_trader.py:255–278` | MET 9c2a4367 written to `paper_trades.jsonl` |
| 7. Executor attempt | `executor.execute(signal)` | `dry_run=True` → no HL order; `_get_open_positions()` also shows 1 position on HL, but paper already committed |

Step 5 is the failing gate: `max_open_positions=5` is the effective cap, not `MAX_CONCURRENT=1`. Steps 3 and 7 are not count-based. An identical trace applies to CHIP 2369fe29 (3rd concurrent) an hour ago.

---

## 6. Root-cause hypothesis (ranked)

### Primary (high confidence, direct evidence)

**`PaperTrader` does not read `config.risk_params.MAX_CONCURRENT`.** It enforces a separate `max_open_positions` parameter populated from `config/config.yaml:78` (= **5**). The two constants have silently drifted, and the paper-trader path bypasses the `MAX_CONCURRENT=1` guard entirely.

Evidence:
- `src/simulator/paper_trader.py:40` default = `5`
- `config/config.yaml:78` = `5`
- `scripts/run_paper_trading.py:71` wires config → paper trader
- No `from config.risk_params import MAX_CONCURRENT` in `src/simulator/paper_trader.py`
- Observed: 3 concurrent opens today; historic max 4 (STABLE + BLAST + YZY + ZETA window 04-18 08:00) — consistent with a cap of 5.

### Secondary (unlikely, flagged for completeness)

- **Orchestrator race**: `handle_event` and `_check_paper_exits` run on different trigger paths (regime event vs tick). A new open could fire between a theoretically enforced gate and a position closure. Refuted by the data: entry gaps are 6h+ between the live three, and historic pairs overlap for hours — not microsecond races.
- **Log-reload duplicates**: `_reload_open_positions_from_log()` runs once at init. A misparse could cause `len(open_positions)` to read low. Refuted: open_positions count is queried on an in-memory list after each open, not re-read from disk.
- **Regime-threshold injection**: `regime_detector` exposes `max_concurrent` per regime (CALM=3, HIGH=1). If the paper trader ever adopted those, HIGH regime (current) would enforce 1. Refuted: `PaperTrader.__init__` has no regime parameter; never consumes `get_active_thresholds()`.

---

## 7. D41 PF contamination sensitivity

| Cohort | n | Wins | Losses | Gross W | Gross L | Net | PF | WR |
|:-|-:|-:|-:|-:|-:|-:|-:|-:|
| As-measured (all 21 clean) | **21** | 13 | 8 | 543.43 | 511.43 | +32.00 | **1.063** | 61.9% |
| Enforced `MAX_CONCURRENT=1` first-in-wins | **7** | 4 | 3 | 199.35 | 137.98 | +61.37 | **1.445** | 57.1% |
| **Δ** | −14 | −9 | −5 | −344.08 | −373.45 | +29.37 | **+0.382** | −4.8pp |

**Under a counterfactual 1-at-a-time policy, 14 of the 21 clean closes would never have been opened.** The surviving-cohort PF rises to **1.445** — but driven by dropping the MET −$224.07 STOP_LOSS (blocked by open SUPER). The **BLUR +$168.77 TAKE_PROFIT** is also dropped (blocked by open BLAST), so the lift is real but not a clean "we were removing losers" story. Worse, n shrinks from 21 to 7, which is below any D41 primary gate floor.

Allowed-through clean cohort (7):
ALT +50.12, SAGA +64.85, ZETA −116.76, YZY +48.09, BLUR −18.33, UMA −2.88, BIO +36.29 (net +$61.37).

**Interpretation:** D41 PF 1.063 at n=21 is a measurement of a *multi-position* strategy, not the intended single-position strategy. The pre-registered gate (PF ≥ 1.30 at n ≥ 30) was designed for single-position enforcement. Under true single-position enforcement the same underlying live conditions produced ~7 trades in the same window — the validation cadence is slower than assumed, and the primary gate n floor may be weeks further out than projected.

---

## 8. Recommended fix scope (diagnostic only — DO NOT EXECUTE)

Each option is one sentence. An operator decides which (or whether).

- **A — minimal (1-line yaml edit):** change `config/config.yaml:78` from `max_open_positions: 5` to `1`; restart `ats-paper-trader`; validates the hypothesis without touching Python.
- **B — canonical (source-of-truth alignment):** import `MAX_CONCURRENT` into `src/simulator/paper_trader.py`, default `max_open_positions` to that, and remove the YAML key so the two constants cannot drift again.
- **C — layered defense:** also gate on count inside `LiveOrchestrator.handle_event` before calling `open_position`, mirroring `Executor._get_open_positions()`, so the pre-persistence layer refuses even if the simulator cap is misconfigured.
- **D — archeology first:** before any fix, reconcile `D41 PF 1.063` vs the pre-registered gate — if the single-position gate applies, n=21 was never on-regime data and we are restarting the validation clock.

All four options are compatible. Order A → D is from narrowest to widest blast radius; B is the minimum durable fix.

---

## 9. Out of scope (explicit)

- Any `config.yaml`, `risk_params.py`, or `paper_trader.py` edit.
- Any restart / deploy of `ats-paper-trader`.
- Any admin close of SUPER 5e3e6386, MET 9c2a4367, or CHIP 2369fe29.
- Appending a D45/D46 row to `decision_log.md`.
- Any fix to the D43 HL funding-interval under-annualization.
- Revising D41 primary gate text.

---

## Appendix — artifacts

- Fresh snapshot: `analysis/snapshots/20260422T202943Z/paper_trades.jsonl` (sha256 `5a85d82…`, 59 lines)
- Prior snapshot: `analysis/snapshots/20260422T165151Z/paper_trades.jsonl` (sha256 `d2000d4…`, 58 lines)
- Enforcement constants:
  - `config/risk_params.py:30` → `MAX_CONCURRENT = 1`
  - `config/config.yaml:78` → `max_open_positions: 5`
  - `config/regime_thresholds.py:52/57/62/67` → `max_concurrent: 3/2/1/1`
- Paper trader instantiation: `scripts/run_paper_trading.py:71`
- Gate site: `src/simulator/paper_trader.py:309`
- Orchestrator entry: `src/pipeline/live_orchestrator.py:271,307`
