#!/usr/bin/env python3
"""D41 backtest-retroactive gate validation.

Applies the live ``CompositeSignalScorer`` formula (with documented proxies
for features unavailable in historical data) to the canonical 180-day
backtest trade log, classifies each trade against the 0.70 execution gate,
and emits a D41 verdict: AMPLIFIES / NEUTRAL / HARMS / UNKNOWN.

Read-only with respect to the canonical artifact
(``artifacts/backtest_trades_d31.jsonl``).

Design notes:

* No re-running of the backtest engine. We join the canonical trade log to
  historical funding + candle data at each trade's ``entry_time``.
* ``DurationPredictor`` is reused as-is — it falls back to the pooled
  HIGH_FUNDING distribution for unknown assets, which mirrors live behavior.
* ``LiquidityScorer`` is replaced with a volume-only proxy
  (``_volume_to_liq_score``) because historical open-interest is not stored.
  Documented as a DOWNWARD bias.
* ``cross_exchange_spread`` is set to ``None`` (contributes 0) — the live
  scorer's ``<2 adapters`` branch produces the same result, so this only
  matters when multi-exchange adapters are live.

Usage::

    python analysis/backtest_gate/score_backtest.py \
        [--trade-log artifacts/backtest_trades_d31.jsonl] \
        [--out-dir analysis/backtest_gate/]
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.config import get_config
from src.collectors.regime_history import RegimeHistoryCollector
from src.scoring.duration_predictor import DurationPredictor


# --------------------------------------------------------------------------- #
# D41 CLASSIFICATION THRESHOLDS
# --------------------------------------------------------------------------- #
# These constants define the operator-facing verdict and must stay in sync
# with the D41 memo in decision_log.md. If the memo is revised, update here.
# --------------------------------------------------------------------------- #
D41_AMPLIFIES_RATIO = 1.30  # PF_gated / PF_raw >= this  → gate AMPLIFIES edge
D41_HARMS_RATIO = 0.85      # PF_gated / PF_raw <  this  → gate HARMS edge
D41_MIN_N_GATED = 5         # n_gated < this            → verdict UNKNOWN

SCORE_GATE = 0.70           # live executor gate (score_normalized scale)

# Canonical sanity-check bounds (D31 headline: PF=1.68, 23 trades, $95 / 180d)
CANONICAL_PF = 1.68
CANONICAL_PF_TOLERANCE = 0.10

DEFAULT_TRADE_LOG = REPO_ROOT / "artifacts" / "backtest_trades_d31.jsonl"
DEFAULT_FUNDING_CSV = REPO_ROOT / "data" / "historical" / "funding_rates.csv"
DEFAULT_CANDLE_DIR = REPO_ROOT / "data" / "historical" / "candles"
DEFAULT_REGIME_DB = REPO_ROOT / "data" / "regime_history.db"
DEFAULT_OUT_DIR = REPO_ROOT / "analysis" / "backtest_gate"


# --------------------------------------------------------------------------- #
# Pure helpers (testable without I/O)
# --------------------------------------------------------------------------- #


def max_apy_pct_from_rate_8h(rate_8h: float) -> float:
    """Annualized funding APY as percentage from an 8h funding rate.

    Matches ``scripts/backtest/strategies/funding_arb.py:60`` which computes
    ``abs(rate_8h) * 3 * 365``. We multiply by 100 to produce the percentage
    scale expected by ``RegimeTransitionEvent.max_apy_annualized``
    (``src/models.py:60``).
    """
    return abs(rate_8h) * 3 * 365 * 100.0


def classify_regime(max_apy_pct: float, thresholds: dict) -> str:
    """Return 'HIGH_FUNDING' / 'MODERATE' / 'LOW_FUNDING' for a max APY pct.

    Mirrors ``src/collectors/regime_history.py:_classify_regime`` but returns
    the string value (avoids importing the enum into pure-helper scope).
    """
    if max_apy_pct >= thresholds["moderate_max_apy"]:
        return "HIGH_FUNDING"
    if max_apy_pct >= thresholds["low_funding_max_apy"]:
        return "MODERATE"
    return "LOW_FUNDING"


def normalize_clip(value: float, lo: float, hi: float) -> float:
    """Clamped min-max normalization to [0,1]. Matches ``_normalize`` in
    ``src/scoring/composite_scorer.py``.
    """
    if hi <= lo:
        return 0.0
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


def volume_to_liq_score(volume: float, max_volume: float) -> float:
    """Volume-only liquidity proxy (log-normalized).

    The live ``LiquidityScorer`` uses
    ``0.6 * log_norm(volume) + 0.4 * log_norm(open_interest)``. Historical OI
    is not available per-tick, so we collapse to volume-only at weight 1.0.
    This biases composite DOWNWARD vs live for OI-heavy assets.
    """
    if max_volume <= 0 or volume <= 0:
        return 0.0
    score = math.log10(volume + 1) / math.log10(max_volume + 1)
    return round(max(0.0, min(1.0, score)), 4)


@dataclass
class ComponentScores:
    net_apy_pct: float
    net_apy_norm: float
    duration_survival: float
    liq_score: float
    cross_spread_norm: float  # always 0.0 in backtest


def composite_score(
    components: ComponentScores,
    weights: dict,
) -> float:
    """Live ``CompositeSignalScorer`` formula (``src/scoring/composite_scorer.py:84``).

    Returns composite on 0-100 scale. ``score_normalized`` is
    ``composite / 100`` — that is the number the live executor compares
    against the 0.70 gate.
    """
    raw = (
        weights["net_apy"] * components.net_apy_norm
        + weights["duration_confidence"] * components.duration_survival
        + weights["liquidity"] * components.liq_score
        + weights["cross_exchange_spread"] * components.cross_spread_norm
    ) * 100.0
    return round(max(0.0, min(100.0, raw)), 4)


def partition_by_gate(
    scored: Iterable[dict],
    threshold: float = SCORE_GATE,
) -> tuple[list[dict], list[dict]]:
    """Split scored trades into (GATED, SUB_GATE) by ``score_normalized``.

    GATED := ``score_normalized >= threshold``. The live executor uses ``>=``
    (see ``src/pipeline/live_orchestrator.py`` gating check); we match.
    """
    gated, sub = [], []
    for t in scored:
        if t["score_normalized"] >= threshold:
            gated.append(t)
        else:
            sub.append(t)
    return gated, sub


def stats_for(trades: list[dict]) -> dict:
    """PF/WR/expectancy/n for a cohort of trades (net_pnl key).

    Mirrors the same conventions as ``scripts/evaluate_gate.py`` so the two
    verdicts can be cross-read.
    """
    n = len(trades)
    if n == 0:
        return {
            "n": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": None,
            "gross_wins": 0.0,
            "gross_losses": 0.0,
            "profit_factor": None,
            "net_pnl": 0.0,
            "expectancy": None,
        }
    wins = [t for t in trades if t["net_pnl"] > 0]
    losses = [t for t in trades if t["net_pnl"] <= 0]
    gw = sum(t["net_pnl"] for t in wins)
    gl = abs(sum(t["net_pnl"] for t in losses))
    pf = (gw / gl) if gl > 0 else None  # None = undefined (no losses)
    net = sum(t["net_pnl"] for t in trades)
    return {
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / n, 4),
        "gross_wins": round(gw, 4),
        "gross_losses": round(gl, 4),
        "profit_factor": round(pf, 4) if pf is not None else None,
        "net_pnl": round(net, 4),
        "expectancy": round(net / n, 4),
    }


def classify_gate_effect(
    stats_raw: dict,
    stats_gated: dict,
    min_n_gated: int = D41_MIN_N_GATED,
    amplifies_ratio: float = D41_AMPLIFIES_RATIO,
    harms_ratio: float = D41_HARMS_RATIO,
) -> dict:
    """Apply D41 thresholds to the (raw, gated) partition stats.

    Returns a dict with fields ``verdict``, ``pf_ratio``, and ``reason``.
    Verdict is one of AMPLIFIES / NEUTRAL / HARMS / UNKNOWN.
    """
    n_gated = stats_gated["n"]
    pf_raw = stats_raw["profit_factor"]
    pf_gated = stats_gated["profit_factor"]

    if n_gated < min_n_gated:
        return {
            "verdict": "UNKNOWN",
            "pf_ratio": None,
            "reason": f"n_gated={n_gated} < {min_n_gated} required for classification",
        }
    if pf_raw is None or pf_raw == 0:
        return {
            "verdict": "UNKNOWN",
            "pf_ratio": None,
            "reason": "PF_raw is undefined (no losses) — ratio not computable",
        }
    if pf_gated is None:
        # All gated trades were winners: ratio is infinite → AMPLIFIES by definition
        return {
            "verdict": "AMPLIFIES",
            "pf_ratio": float("inf"),
            "reason": "PF_gated is undefined (no losses in gated cohort) → ratio → ∞",
        }

    ratio = pf_gated / pf_raw
    if ratio >= amplifies_ratio:
        verdict = "AMPLIFIES"
    elif ratio < harms_ratio:
        verdict = "HARMS"
    else:
        verdict = "NEUTRAL"
    return {
        "verdict": verdict,
        "pf_ratio": round(ratio, 4),
        "reason": (
            f"PF_gated/PF_raw={ratio:.4f} (thresholds: AMPLIFIES≥{amplifies_ratio}, "
            f"HARMS<{harms_ratio}); n_gated={n_gated}"
        ),
    }


def sanity_check_pf_raw(pf_raw: float, canonical: float = CANONICAL_PF,
                        tol: float = CANONICAL_PF_TOLERANCE) -> None:
    """Raise ``RuntimeError`` if PF_raw reconstruction is off canonical by > tol.

    Reproducing the canonical PF is a precondition. If this fails, something
    is wrong with the trade log or how we aggregate.
    """
    if pf_raw is None:
        raise RuntimeError("PF_raw is undefined — cannot validate against canonical 1.68")
    if abs(pf_raw - canonical) > tol:
        raise RuntimeError(
            f"PF_raw reconstruction {pf_raw:.4f} off canonical {canonical} "
            f"by > {tol}. Trade log parsing or aggregation is wrong — STOP."
        )


# --------------------------------------------------------------------------- #
# Data loading (thin I/O — deliberately not tested here)
# --------------------------------------------------------------------------- #


def load_trade_log(path: Path) -> list[dict]:
    trades = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                trades.append(json.loads(line))
    return trades


def load_funding_index(path: Path) -> dict[str, list[tuple[int, float]]]:
    """Load funding CSV. Returns {asset: sorted [(ts_ms, rate_8h), ...]}."""
    by_asset: dict[str, list[tuple[int, float]]] = {}
    with open(path) as f:
        r = csv.DictReader(f)
        for row in r:
            a = row["asset"]
            by_asset.setdefault(a, []).append((int(row["timestamp"]), float(row["funding_rate_8h"])))
    for a in by_asset:
        by_asset[a].sort()
    return by_asset


def load_candles(candle_dir: Path, assets: set[str]) -> dict[str, list[tuple[int, float]]]:
    """Load 1h candles per asset. Returns {asset: sorted [(ts_ms, volume), ...]}."""
    by_asset: dict[str, list[tuple[int, float]]] = {}
    for asset in assets:
        p = candle_dir / f"{asset}_1h.csv"
        if not p.exists():
            continue
        rows: list[tuple[int, float]] = []
        with open(p) as f:
            r = csv.DictReader(f)
            for row in r:
                rows.append((int(row["timestamp"]), float(row["volume"])))
        rows.sort()
        by_asset[asset] = rows
    return by_asset


def lookup_rate_at(index: list[tuple[int, float]], ts_ms: int) -> float | None:
    """Most recent funding rate at or before ``ts_ms``. Binary search."""
    if not index:
        return None
    lo, hi = 0, len(index) - 1
    best = None
    while lo <= hi:
        mid = (lo + hi) // 2
        mts, mrate = index[mid]
        if mts <= ts_ms:
            best = mrate
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def volume_24h_at(candles: list[tuple[int, float]], ts_ms: int) -> float:
    """Sum volume of last 24 hourly candles at or before ``ts_ms``.

    Returns 0.0 if no candles available.
    """
    if not candles:
        return 0.0
    # Find index of last candle <= ts_ms
    lo, hi = 0, len(candles) - 1
    idx = -1
    while lo <= hi:
        mid = (lo + hi) // 2
        mts, _ = candles[mid]
        if mts <= ts_ms:
            idx = mid
            lo = mid + 1
        else:
            hi = mid - 1
    if idx < 0:
        return 0.0
    start = max(0, idx - 23)
    return sum(v for _, v in candles[start: idx + 1])


# --------------------------------------------------------------------------- #
# Main pipeline
# --------------------------------------------------------------------------- #


def score_trades(
    trades: list[dict],
    funding_index: dict[str, list[tuple[int, float]]],
    candles: dict[str, list[tuple[int, float]]],
    duration_predictor: DurationPredictor,
    cfg: dict,
    min_duration_minutes: float,
    exchange: str = "hyperliquid",
) -> tuple[list[dict], list[str]]:
    """Attach ``score_normalized`` to each trade.

    Returns (scored_trades, warnings). Trades missing any required data get
    ``score_normalized = None`` and are reported as warnings (then excluded
    from gated-partition decisions — matching the live executor which cannot
    gate what it cannot score).
    """
    weights = cfg["scoring_weights"]
    regime_thresholds = cfg["regime_thresholds"]
    exchange_cfg = cfg["exchanges"].get(exchange, {})
    fee_rate = exchange_cfg.get("fee_rate_round_trip", 0.0008)

    # Global max volume across the backtest window → log-normalize denominator
    max_volume = 0.0
    for asset, rows in candles.items():
        for _, v in rows:
            if v > max_volume:
                max_volume = v

    scored: list[dict] = []
    warnings: list[str] = []
    for t in trades:
        asset = t["asset"]
        et = t["entry_time"]
        rate = lookup_rate_at(funding_index.get(asset, []), et)
        vol = volume_24h_at(candles.get(asset, []), et)

        record = dict(t)  # preserve original fields
        if rate is None:
            record["score_normalized"] = None
            record["score_components"] = None
            record["rejection"] = "no_funding_at_entry_time"
            warnings.append(f"{asset} @ {et}: no funding rate at or before entry")
            scored.append(record)
            continue

        max_apy_pct = max_apy_pct_from_rate_8h(rate)
        regime = classify_regime(max_apy_pct, regime_thresholds)

        # Live scorer: net_apy = max_apy - fee_rate*100
        net_apy_pct = max_apy_pct - (fee_rate * 100.0)
        net_apy_norm = normalize_clip(net_apy_pct, 0.0, 500.0)

        duration_est = duration_predictor.predict(
            asset=asset,
            regime=regime,
            min_duration_minutes=min_duration_minutes,
        )
        liq_score = volume_to_liq_score(vol, max_volume)

        components = ComponentScores(
            net_apy_pct=round(net_apy_pct, 4),
            net_apy_norm=round(net_apy_norm, 4),
            duration_survival=round(duration_est.survival_probability, 4),
            liq_score=liq_score,
            cross_spread_norm=0.0,  # <2 adapters branch; matches live single-ex mode
        )
        composite = composite_score(components, weights)
        score_normalized = round(composite / 100.0, 4)

        record["score_normalized"] = score_normalized
        record["composite_score"] = composite
        record["regime_at_entry"] = regime
        record["max_apy_pct"] = round(max_apy_pct, 2)
        record["score_components"] = {
            "net_apy_pct": components.net_apy_pct,
            "net_apy_norm": components.net_apy_norm,
            "duration_survival": components.duration_survival,
            "duration_sample_count": duration_est.sample_count,
            "duration_used_fallback": duration_est.used_fallback,
            "liq_score": components.liq_score,
            "volume_24h_proxy": round(vol, 2),
            "cross_spread_norm": components.cross_spread_norm,
        }
        record["rejection"] = None
        scored.append(record)
    return scored, warnings


def build_report(scored: list[dict], warnings: list[str],
                 threshold: float = SCORE_GATE) -> dict:
    """Produce the full analysis dict: raw / gated / sub-gate stats + verdict."""
    scorable = [t for t in scored if t.get("score_normalized") is not None]
    unscorable = [t for t in scored if t.get("score_normalized") is None]

    raw_stats = stats_for(scorable)

    # Sanity: PF_raw must reproduce the canonical 1.68 ±0.1 before we claim anything
    sanity_check_pf_raw(raw_stats["profit_factor"])

    gated, sub = partition_by_gate(scorable, threshold)
    gated_stats = stats_for(gated)
    sub_stats = stats_for(sub)

    classification = classify_gate_effect(raw_stats, gated_stats)

    # Distribution breakdown for the report body
    score_hist_bins = [0.0, 0.50, 0.60, 0.65, 0.70, 0.75, 0.80, 1.01]
    hist: list[dict] = []
    for lo, hi in zip(score_hist_bins[:-1], score_hist_bins[1:]):
        cnt = sum(1 for t in scorable if lo <= t["score_normalized"] < hi)
        hist.append({"lo": lo, "hi": hi, "count": cnt})

    return {
        "threshold": threshold,
        "d41_thresholds": {
            "amplifies_ratio_ge": D41_AMPLIFIES_RATIO,
            "harms_ratio_lt": D41_HARMS_RATIO,
            "min_n_gated": D41_MIN_N_GATED,
        },
        "canonical": {"pf": CANONICAL_PF, "tolerance": CANONICAL_PF_TOLERANCE},
        "n_trades_input": len(scored),
        "n_trades_scorable": len(scorable),
        "n_trades_unscorable": len(unscorable),
        "raw": raw_stats,
        "gated": gated_stats,
        "sub_gate": sub_stats,
        "classification": classification,
        "score_distribution": hist,
        "warnings": warnings,
    }


def render_markdown(report: dict, trade_log_path: Path) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    c = report["classification"]
    r, g, s = report["raw"], report["gated"], report["sub_gate"]
    verdict = c["verdict"]

    def fmt_pf(x):
        return "n/a" if x is None else f"{x:.4f}"

    def fmt_wr(x):
        return "n/a" if x is None else f"{x*100:.2f}%"

    lines = [
        "# D41 Backtest Gate Validation — Report",
        "",
        f"Generated: {ts}",
        f"Trade log: `{trade_log_path}`",
        "",
        f"**Verdict: {verdict}**",
        "",
        "## D41 Classification Thresholds",
        "",
        f"- AMPLIFIES: PF_gated / PF_raw ≥ **{D41_AMPLIFIES_RATIO}**",
        f"- HARMS:    PF_gated / PF_raw < **{D41_HARMS_RATIO}**",
        f"- NEUTRAL:  between the two, with n_gated ≥ {D41_MIN_N_GATED}",
        f"- UNKNOWN:  n_gated < {D41_MIN_N_GATED} OR PF_raw undefined",
        "",
        "## Canonical Sanity Check",
        "",
        f"- Canonical PF (D31 headline): **{CANONICAL_PF}**, tolerance ±{CANONICAL_PF_TOLERANCE}",
        f"- Reconstructed PF_raw: **{fmt_pf(r['profit_factor'])}** — "
        f"{'PASS' if r['profit_factor'] is not None and abs(r['profit_factor'] - CANONICAL_PF) <= CANONICAL_PF_TOLERANCE else 'FAIL'}",
        "",
        "## Partition Stats (threshold score_normalized ≥ {:.2f})".format(report["threshold"]),
        "",
        "| Cohort   | n  | Win rate | Profit factor | Net PnL ($) | Expectancy ($) |",
        "|----------|----|----------|---------------|-------------|----------------|",
        f"| RAW      | {r['n']} | {fmt_wr(r['win_rate'])} | {fmt_pf(r['profit_factor'])} | {r['net_pnl']:.4f} | {r['expectancy']:.4f} |",
        f"| GATED    | {g['n']} | {fmt_wr(g['win_rate'])} | {fmt_pf(g['profit_factor'])} | {g['net_pnl']:.4f} | "
        f"{g['expectancy'] if g['expectancy'] is not None else float('nan'):.4f} |",
        f"| SUB_GATE | {s['n']} | {fmt_wr(s['win_rate'])} | {fmt_pf(s['profit_factor'])} | {s['net_pnl']:.4f} | "
        f"{s['expectancy'] if s['expectancy'] is not None else float('nan'):.4f} |",
        "",
        f"- PF_gated / PF_raw ratio: **{c['pf_ratio']}**",
        f"- Classification reason: {c['reason']}",
        "",
        "## Score Distribution",
        "",
        "| Range              | Count |",
        "|--------------------|-------|",
    ]
    for b in report["score_distribution"]:
        lines.append(f"| [{b['lo']:.2f}, {b['hi']:.2f}) | {b['count']} |")
    lines.append("")
    lines.append("## Warnings")
    if report["warnings"]:
        for w in report["warnings"]:
            lines.append(f"- {w}")
    else:
        lines.append("- (none)")
    lines += [
        "",
        "## Known Biases (Proxy → Live)",
        "",
        "All three proxies bias composite_score DOWNWARD relative to live:",
        "",
        "- **Cross-exchange spread** forced to `None` → contributes 0 (up to −15 pts).",
        "- **Liquidity** uses volume-only log-normalization; live blends 40% OI. Assets",
        "  with high OI-to-volume ratio score lower than live would (up to −8 pts).",
        "- **Duration survival** uses the pooled HIGH_FUNDING distribution when the",
        "  specific asset is unknown. This is the same fallback the live predictor",
        "  takes, so no extra bias beyond the live runtime.",
        "",
        "**Interpretive rule:** if the gated cohort shows AMPLIFIES under these",
        "proxies, live would be at least as strong. If HARMS, the result could be a",
        "proxy artifact and should be treated as at most NEUTRAL until proxies",
        "improve.",
    ]
    return "\n".join(lines)


def run(
    trade_log: Path = DEFAULT_TRADE_LOG,
    funding_csv: Path = DEFAULT_FUNDING_CSV,
    candle_dir: Path = DEFAULT_CANDLE_DIR,
    regime_db: Path = DEFAULT_REGIME_DB,
    out_dir: Path = DEFAULT_OUT_DIR,
) -> dict:
    cfg = get_config()
    trades = load_trade_log(trade_log)
    assets = {t["asset"] for t in trades}
    funding_index = load_funding_index(funding_csv)
    candle_index = load_candles(candle_dir, assets)

    # Reuse the live DurationPredictor with the canonical regime DB.
    history = RegimeHistoryCollector(adapters=[], db_path=regime_db)
    duration_predictor = DurationPredictor(history_collector=history)

    min_duration_minutes = cfg["duration_filter"]["min_duration_minutes"]

    scored, warnings = score_trades(
        trades,
        funding_index=funding_index,
        candles=candle_index,
        duration_predictor=duration_predictor,
        cfg=cfg,
        min_duration_minutes=min_duration_minutes,
    )
    report = build_report(scored, warnings)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "gate_validation_report.json").write_text(
        json.dumps({"report": report, "scored_trades": scored}, indent=2, default=str)
    )
    (out_dir / "gate_validation_report.md").write_text(
        render_markdown(report, trade_log)
    )
    return report


def main() -> None:
    p = argparse.ArgumentParser(description="D41 backtest gate validation")
    p.add_argument("--trade-log", type=Path, default=DEFAULT_TRADE_LOG)
    p.add_argument("--funding-csv", type=Path, default=DEFAULT_FUNDING_CSV)
    p.add_argument("--candle-dir", type=Path, default=DEFAULT_CANDLE_DIR)
    p.add_argument("--regime-db", type=Path, default=DEFAULT_REGIME_DB)
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = p.parse_args()

    report = run(
        trade_log=args.trade_log,
        funding_csv=args.funding_csv,
        candle_dir=args.candle_dir,
        regime_db=args.regime_db,
        out_dir=args.out_dir,
    )
    c = report["classification"]
    r, g, s = report["raw"], report["gated"], report["sub_gate"]
    print(f"n_trades_input   = {report['n_trades_input']}")
    print(f"scorable/unscorable = {report['n_trades_scorable']}/{report['n_trades_unscorable']}")
    print(f"RAW      n={r['n']:3d}  PF={r['profit_factor']}  WR={r['win_rate']}  net={r['net_pnl']}")
    print(f"GATED    n={g['n']:3d}  PF={g['profit_factor']}  WR={g['win_rate']}  net={g['net_pnl']}")
    print(f"SUB_GATE n={s['n']:3d}  PF={s['profit_factor']}  WR={s['win_rate']}  net={s['net_pnl']}")
    print(f"ratio PF_gated/PF_raw = {c['pf_ratio']}")
    print(f"VERDICT = {c['verdict']}  ({c['reason']})")


if __name__ == "__main__":
    main()
