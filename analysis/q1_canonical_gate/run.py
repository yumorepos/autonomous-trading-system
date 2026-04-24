"""
Q1 retroactive-gate analysis — reads a pinned trade log and an optional
companion signal log and computes PF_raw vs PF_gated side-by-side.

History:
- First pass (2026-04-24) against the D31 trade log alone returned STOP
  ("Scorer requires inputs the trade log does not carry") because the D31
  engine did not emit scorer inputs. See REPORT.md for the input-gap
  analysis.
- Second pass (D50) runs against the D50 pair produced by the instrumented
  backtest engine. See REPORT_D50.md for the three-outcome verdict.

CLI
---
    python3 analysis/q1_canonical_gate/run.py \
        --trade-log artifacts/backtest_trades_d50.jsonl \
        --signal-log artifacts/backtest_signals_d50.jsonl \
        --gate 0.70

If `--signal-log` is omitted, the script runs the original D31 hash check
+ input-gap enumeration (legacy STOP behavior, for regression).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCORER_PATH = REPO_ROOT / "src" / "scoring" / "composite_scorer.py"

# D31 pinned hash — used for regression verification when the default trade
# log is passed.
D31_EXPECTED_SHA = "2ee4f3725b5ec9cccae1bec499a969ecdc3b702f4de17f334c6548692afe31f4"
D31_TRADE_LOG = REPO_ROOT / "artifacts" / "backtest_trades_d31.jsonl"

# Per composite_scorer.py:42-89. None of these are emitted by the pre-D50
# funding_arb strategy; they are captured in the D50 companion log.
REQUIRED_SCORER_INPUTS = {
    "max_apy_annualized": (
        "RegimeTransitionEvent field — entry-time funding APY. "
        "Backtest strategy computes funding_annual internally but did "
        "not persist it to the trade log pre-D50."
    ),
    "new_regime": (
        "RegimeTransitionEvent field — HIGH_FUNDING tier label. Required "
        "for the regime gate at composite_scorer.py:96."
    ),
    "duration_survival_prob": (
        "DurationPredictor.predict() output at entry timestamp. Stateful; "
        "requires replaying the full duration model."
    ),
    "liquidity_score": (
        "LiquidityScorer.score() output — historically requires orderbook "
        "depth snapshot at entry time. D50 synthesis: volume-only "
        "log-norm against per-bar max."
    ),
    "cross_exchange_spread": (
        "_compute_cross_exchange_spread() output — requires live cross-"
        "exchange funding rates at entry time. Single-venue backtest "
        "returns None (scorer's own <2-adapter handling)."
    ),
}


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_jsonl(path: Path) -> list[dict]:
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def profit_factor(trades: list[dict]) -> tuple[int, float, float, float, float]:
    wins = [t for t in trades if t["net_pnl"] > 0]
    losses = [t for t in trades if t["net_pnl"] <= 0]
    gross_win = sum(t["net_pnl"] for t in wins)
    gross_loss = -sum(t["net_pnl"] for t in losses)
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
    wr = len(wins) / len(trades) if trades else 0.0
    return len(trades), pf, wr, gross_win, gross_loss


def git_last_commit(path: Path) -> str:
    return subprocess.check_output(
        ["git", "log", "-1", "--format=%h %ci", str(path)],
        cwd=REPO_ROOT,
    ).decode().strip()


def file_mtime(path: Path) -> str:
    return subprocess.check_output(
        ["stat", "-f", "%Sm", "-t", "%Y-%m-%d %H:%M:%S", str(path)]
    ).decode().strip()


def _legacy_d31_stop(trade_log: Path) -> None:
    """Legacy STOP path — runs the original D31 input-gap analysis."""
    print("=" * 72)
    print("Q1 retroactive-gate analysis on D31 canonical trade log (legacy)")
    print("=" * 72)

    actual_sha = sha256_of(trade_log)
    hash_match = actual_sha == D31_EXPECTED_SHA
    print(f"\n[1] Artifact hash check")
    print(f"    path:     {trade_log.relative_to(REPO_ROOT)}")
    print(f"    expected: {D31_EXPECTED_SHA}")
    print(f"    actual:   {actual_sha}")
    print(f"    match:    {hash_match}")
    if not hash_match:
        raise SystemExit("STOP: pinned artifact hash mismatch")

    scorer_commit = git_last_commit(SCORER_PATH)
    artifact_mtime = file_mtime(trade_log)
    print(f"\n[2] Scorer drift check")
    print(f"    scorer HEAD commit:  {scorer_commit}")
    print(f"    artifact mtime:      {artifact_mtime}")

    trades = load_jsonl(trade_log)
    n, pf, wr, gw, gl = profit_factor(trades)
    print(f"\n[3] PF_raw reproduction (ground truth)")
    print(f"    n_raw:        {n}")
    print(f"    PF_raw:       {pf:.3f}   (target 1.68 ± rounding)")
    print(f"    WR_raw:       {wr:.1%}")
    if abs(pf - 1.68) >= 0.01:
        raise SystemExit("STOP: PF_raw does not reproduce")

    log_fields = sorted({k for t in trades for k in t.keys()})
    print(f"\n[4] Scorer input gap")
    print(f"    trade log fields ({len(log_fields)}): {log_fields}")
    missing = [k for k in REQUIRED_SCORER_INPUTS if k not in log_fields]
    print(f"    missing scorer inputs ({len(missing)}/5):")
    for k, desc in REQUIRED_SCORER_INPUTS.items():
        mark = "PRESENT" if k in log_fields else "MISSING"
        print(f"      [{mark}] {k}: {desc}")

    print(f"\n[5] Verdict: STOP — 'Scorer requires inputs the trade log does not carry'")
    print("    PF_gated not computed. See REPORT.md for the input-gap breakdown.")


def _d50_gated_analysis(trade_log: Path, signal_log: Path, gate: float) -> None:
    """D50 path — applies composite gate using the companion signal log."""
    print("=" * 72)
    print(f"Q1 retroactive-gate analysis on {trade_log.name} × {signal_log.name}")
    print(f"Gate: composite_score_normalized >= {gate:.2f}  (=" \
          f" composite_score >= {gate * 100:.1f} on 0-100 scale)")
    print("=" * 72)

    trades = load_jsonl(trade_log)
    signals = load_jsonl(signal_log)
    if len(trades) != len(signals):
        raise SystemExit(
            f"STOP: trade/signal count mismatch — trades={len(trades)} signals={len(signals)}"
        )

    # Key both by (asset, entry_time)
    sig_by_key = {(s["asset"], s["entry_time"]): s for s in signals}
    for t in trades:
        key = (t["asset"], t["entry_time"])
        if key not in sig_by_key:
            raise SystemExit(
                f"STOP: signal record missing for trade {key}. "
                f"Companion 1:1 invariant violated."
            )

    # Hash both artifacts
    trade_sha = sha256_of(trade_log)
    signal_sha = sha256_of(signal_log)
    print(f"\n[1] Artifact hashes")
    print(f"    trades:  {trade_sha}")
    print(f"    signals: {signal_sha}")
    if trade_sha == D31_EXPECTED_SHA:
        print(f"    note:    D50 trade log matches D31 byte-for-byte (D46 invariance)")

    # PF_raw
    n_raw, pf_raw, wr_raw, gw_raw, gl_raw = profit_factor(trades)
    print(f"\n[2] PF_raw (ground truth)")
    print(f"    n_raw={n_raw}  PF_raw={pf_raw:.3f}  WR_raw={wr_raw:.1%}  " \
          f"gross_win=${gw_raw:.2f} gross_loss=${gl_raw:.2f}")

    # Score distribution
    scores = [s["composite_score"] for s in signals]
    print(f"\n[3] Composite score distribution")
    print(f"    n={len(scores)}  min={min(scores):.2f}  max={max(scores):.2f}  " \
          f"mean={sum(scores)/len(scores):.2f}")
    unique = sorted(set(round(s, 2) for s in scores))
    if len(unique) <= 5:
        print(f"    unique scores: {unique}")
    else:
        print(f"    unique scores: {len(unique)} distinct values")

    # Synthesis audit
    synthesis_seen: set[str] = set()
    for s in signals:
        for f in s.get("synthesized_fields", []):
            synthesis_seen.add(f)
    print(f"\n[4] Synthesis audit (per-record)")
    print(f"    distinct synthesized_fields flags: {len(synthesis_seen)}")
    for f in sorted(synthesis_seen):
        print(f"      - {f}")

    # Apply gate
    gate_100 = gate * 100
    gated_keys = {(s["asset"], s["entry_time"]) for s in signals
                  if s["composite_score"] >= gate_100}
    gated_trades = [t for t in trades
                    if (t["asset"], t["entry_time"]) in gated_keys]
    n_gated, pf_gated, wr_gated, gw_gated, gl_gated = profit_factor(gated_trades)
    print(f"\n[5] PF_gated (composite_score >= {gate_100:.0f})")
    print(f"    n_gated={n_gated}  PF_gated=" \
          f"{'inf' if pf_gated == float('inf') else f'{pf_gated:.3f}'}  " \
          f"WR_gated={wr_gated:.1%}")
    if n_gated > 0:
        print(f"    gross_win=${gw_gated:.2f}  gross_loss=${gl_gated:.2f}")

    # Worst-trade sensitivity (if n_gated >= 2)
    if n_gated >= 2 and pf_gated != float("inf"):
        worst = min(gated_trades, key=lambda t: t["net_pnl"])
        remaining_wins = sum(t["net_pnl"] for t in gated_trades if t["net_pnl"] > 0)
        remaining_losses = -sum(
            t["net_pnl"] for t in gated_trades
            if t["net_pnl"] <= 0 and t is not worst
        )
        if worst["net_pnl"] > 0:
            # removing a winner
            pf_excl = (remaining_wins - worst["net_pnl"]) / remaining_losses \
                if remaining_losses > 0 else float("inf")
        else:
            pf_excl = remaining_wins / remaining_losses \
                if remaining_losses > 0 else float("inf")
        print(f"\n[6] Worst gated trade: {worst['asset']} net=${worst['net_pnl']:.4f}")
        print(f"    PF_gated excl worst: " \
              f"{'inf' if pf_excl == float('inf') else f'{pf_excl:.3f}'}")

    # Verdict
    print(f"\n[7] Verdict (three-outcome)")
    if n_gated >= 10 and pf_gated >= 1.30:
        verdict = "AMPLIFIES"
    elif n_gated > 0 and 1.00 <= pf_gated < 1.30:
        verdict = "NEUTRAL"
    elif n_gated > 0 and pf_gated < 1.00:
        verdict = "CONTRADICTS"
    elif n_gated == 0:
        verdict = "NEUTRAL (n_gated=0)"
    elif n_gated < 10:
        verdict = "NEUTRAL (n_gated<10)"
    else:
        verdict = "UNCLASSIFIED"
    print(f"    Q1 = {verdict}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Q1 retroactive-gate analysis")
    parser.add_argument(
        "--trade-log",
        type=Path,
        default=D31_TRADE_LOG,
        help="Path to backtest trades JSONL (default: D31 pinned artifact)",
    )
    parser.add_argument(
        "--signal-log",
        type=Path,
        default=None,
        help="Path to companion signal JSONL. If omitted, runs the legacy D31 STOP analysis.",
    )
    parser.add_argument(
        "--gate",
        type=float,
        default=0.70,
        help="Composite score gate in 0-1 scale (default: 0.70 = 70 on 0-100 scale)",
    )
    args = parser.parse_args()

    if args.signal_log is None:
        _legacy_d31_stop(args.trade_log)
    else:
        _d50_gated_analysis(args.trade_log, args.signal_log, args.gate)


if __name__ == "__main__":
    main()
