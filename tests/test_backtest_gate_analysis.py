"""Unit tests for D41 backtest-retroactive gate validation helpers."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from analysis.backtest_gate.score_backtest import (
    ComponentScores,
    D41_AMPLIFIES_RATIO,
    D41_HARMS_RATIO,
    D41_MIN_N_GATED,
    SCORE_GATE,
    classify_gate_effect,
    classify_regime,
    composite_score,
    lookup_rate_at,
    max_apy_pct_from_rate_8h,
    normalize_clip,
    partition_by_gate,
    sanity_check_pf_raw,
    stats_for,
    volume_24h_at,
    volume_to_liq_score,
)


# --------------------------------------------------------------------------- #
# Partition edge cases — the 0.70 gate is inclusive on the GATED side, matching
# the live executor's ``score_normalized >= 0.70`` check.
# --------------------------------------------------------------------------- #


def test_partition_score_0_71_is_gated():
    scored = [{"asset": "FOO", "score_normalized": 0.71, "net_pnl": 1.0}]
    gated, sub = partition_by_gate(scored, threshold=SCORE_GATE)
    assert len(gated) == 1
    assert len(sub) == 0
    assert gated[0]["asset"] == "FOO"


def test_partition_score_0_69_is_sub_gate():
    scored = [{"asset": "BAR", "score_normalized": 0.69, "net_pnl": -1.0}]
    gated, sub = partition_by_gate(scored, threshold=SCORE_GATE)
    assert len(gated) == 0
    assert len(sub) == 1
    assert sub[0]["asset"] == "BAR"


def test_partition_boundary_0_70_inclusive_gated():
    """Boundary: score == threshold goes into GATED (>= matches live executor)."""
    scored = [{"asset": "EDGE", "score_normalized": 0.70, "net_pnl": 0.5}]
    gated, sub = partition_by_gate(scored)
    assert len(gated) == 1
    assert len(sub) == 0


# --------------------------------------------------------------------------- #
# D41 verdict classification
# --------------------------------------------------------------------------- #


def test_classify_amplifies_when_ratio_above_1_30_and_enough_gated():
    stats_raw = {"n": 20, "profit_factor": 1.40}
    stats_gated = {"n": 8, "profit_factor": 2.10}
    result = classify_gate_effect(stats_raw, stats_gated)
    # ratio = 2.10 / 1.40 = 1.50 >= 1.30 AND n_gated=8 >= 5
    assert result["verdict"] == "AMPLIFIES"
    assert result["pf_ratio"] == 1.5


def test_classify_harms_when_ratio_below_0_85_and_enough_gated():
    stats_raw = {"n": 20, "profit_factor": 1.60}
    stats_gated = {"n": 6, "profit_factor": 1.20}
    result = classify_gate_effect(stats_raw, stats_gated)
    # ratio = 1.20 / 1.60 = 0.75 < 0.85
    assert result["verdict"] == "HARMS"
    assert result["pf_ratio"] == 0.75


def test_classify_neutral_between_thresholds():
    stats_raw = {"n": 20, "profit_factor": 1.60}
    stats_gated = {"n": 7, "profit_factor": 1.60}
    result = classify_gate_effect(stats_raw, stats_gated)
    # ratio = 1.00, falls in [0.85, 1.30) with n_gated >= 5
    assert result["verdict"] == "NEUTRAL"
    assert result["pf_ratio"] == 1.0


def test_classify_unknown_when_n_gated_too_small():
    stats_raw = {"n": 20, "profit_factor": 1.60}
    stats_gated = {"n": D41_MIN_N_GATED - 1, "profit_factor": 2.00}
    result = classify_gate_effect(stats_raw, stats_gated)
    assert result["verdict"] == "UNKNOWN"
    assert result["pf_ratio"] is None
    assert "< 5" in result["reason"]


def test_classify_unknown_when_pf_raw_undefined():
    stats_raw = {"n": 20, "profit_factor": None}
    stats_gated = {"n": 10, "profit_factor": 1.80}
    result = classify_gate_effect(stats_raw, stats_gated)
    assert result["verdict"] == "UNKNOWN"


def test_classify_amplifies_when_pf_gated_undefined():
    """Gated cohort has no losses → ratio is infinite → AMPLIFIES by definition."""
    stats_raw = {"n": 20, "profit_factor": 1.40}
    stats_gated = {"n": 7, "profit_factor": None}  # all winners
    result = classify_gate_effect(stats_raw, stats_gated)
    assert result["verdict"] == "AMPLIFIES"


# --------------------------------------------------------------------------- #
# Composite formula parity with live
# --------------------------------------------------------------------------- #


def test_composite_formula_matches_live_weights():
    """Spot-check composite() against a hand-computed example using the default
    weights from config.yaml: net_apy=0.35, duration=0.30, liq=0.20, cross=0.15.
    """
    weights = {
        "net_apy": 0.35,
        "duration_confidence": 0.30,
        "liquidity": 0.20,
        "cross_exchange_spread": 0.15,
    }
    components = ComponentScores(
        net_apy_pct=500.0,
        net_apy_norm=1.0,     # 500% APY → normalized to 1.0
        duration_survival=0.8,
        liq_score=0.5,
        cross_spread_norm=0.0,
    )
    # Expected: 100 * (0.35*1 + 0.30*0.8 + 0.20*0.5 + 0.15*0) = 100 * 0.69 = 69.0
    assert composite_score(components, weights) == 69.0


def test_composite_is_clipped_to_0_100():
    weights = {"net_apy": 10.0, "duration_confidence": 0.0,
               "liquidity": 0.0, "cross_exchange_spread": 0.0}
    components = ComponentScores(
        net_apy_pct=1000.0, net_apy_norm=1.0, duration_survival=0.0,
        liq_score=0.0, cross_spread_norm=0.0,
    )
    # Raw would be 100 * 10 = 1000 → clipped to 100
    assert composite_score(components, weights) == 100.0


# --------------------------------------------------------------------------- #
# Sanity check (canonical PF)
# --------------------------------------------------------------------------- #


def test_sanity_check_pf_raw_pass_on_exact_canonical():
    sanity_check_pf_raw(1.68)  # no raise


def test_sanity_check_pf_raw_pass_within_tolerance():
    sanity_check_pf_raw(1.76)  # |Δ| = 0.08 < 0.10


def test_sanity_check_pf_raw_fails_outside_tolerance():
    with pytest.raises(RuntimeError, match="off canonical"):
        sanity_check_pf_raw(2.00)


def test_sanity_check_pf_raw_fails_on_none():
    with pytest.raises(RuntimeError, match="undefined"):
        sanity_check_pf_raw(None)


# --------------------------------------------------------------------------- #
# Canonical trade-log reconstruction (end-to-end anchor)
# --------------------------------------------------------------------------- #


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_canonical_trade_log_reconstructs_pf_1_68():
    """Reconstruct PF from the pinned canonical trade log.

    Pins D36: sha256 2ee4f37... — if this test fails the trade log has been
    mutated or mis-parsed. The D41 gate validation report's sanity check
    depends on this exact reconstruction.
    """
    path = REPO_ROOT / "artifacts" / "backtest_trades_d31.jsonl"
    if not path.exists():
        pytest.skip(f"canonical trade log missing at {path}")
    trades = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    st = stats_for(trades)
    assert st["n"] == 23
    assert st["wins"] == 19
    assert st["losses"] == 4
    # PF 1.68 to 2 decimals per docs/audits/EDGE_VALIDATION_REPORT.md
    assert abs(st["profit_factor"] - 1.68) < 0.01


# --------------------------------------------------------------------------- #
# Liquidity proxy edge cases
# --------------------------------------------------------------------------- #


def test_volume_to_liq_zero_volume_yields_zero():
    assert volume_to_liq_score(0.0, 1_000_000.0) == 0.0


def test_volume_to_liq_at_max_yields_one():
    assert volume_to_liq_score(1_000_000.0, 1_000_000.0) == 1.0


def test_volume_to_liq_zero_max_yields_zero():
    assert volume_to_liq_score(1_000_000.0, 0.0) == 0.0


# --------------------------------------------------------------------------- #
# Supporting helpers
# --------------------------------------------------------------------------- #


def test_max_apy_pct_from_rate_8h_basic():
    # 0.0001 per-8h rate → annualized = 0.0001 * 3 * 365 = 0.1095 → × 100 = 10.95%
    assert abs(max_apy_pct_from_rate_8h(0.0001) - 10.95) < 1e-9


def test_max_apy_pct_takes_absolute_value():
    assert max_apy_pct_from_rate_8h(-0.0001) == max_apy_pct_from_rate_8h(0.0001)


def test_classify_regime_thresholds():
    thresholds = {"low_funding_max_apy": 20, "moderate_max_apy": 80}
    assert classify_regime(85.0, thresholds) == "HIGH_FUNDING"
    assert classify_regime(80.0, thresholds) == "HIGH_FUNDING"  # inclusive
    assert classify_regime(50.0, thresholds) == "MODERATE"
    assert classify_regime(20.0, thresholds) == "MODERATE"  # inclusive
    assert classify_regime(5.0, thresholds) == "LOW_FUNDING"


def test_normalize_clip_edges():
    assert normalize_clip(-10.0, 0.0, 100.0) == 0.0
    assert normalize_clip(50.0, 0.0, 100.0) == 0.5
    assert normalize_clip(150.0, 0.0, 100.0) == 1.0
    # Degenerate bounds → 0 (matches live ``_normalize``)
    assert normalize_clip(5.0, 10.0, 10.0) == 0.0


def test_lookup_rate_at_returns_most_recent_leq():
    index = [(100, 0.01), (200, 0.02), (300, 0.03)]
    assert lookup_rate_at(index, 150) == 0.01
    assert lookup_rate_at(index, 200) == 0.02
    assert lookup_rate_at(index, 500) == 0.03
    assert lookup_rate_at(index, 99) is None


def test_volume_24h_at_sums_up_to_24_last_candles():
    candles = [(i * 3_600_000, float(i)) for i in range(1, 50)]  # 49 candles
    # At candle 30: sum candles 7..30 inclusive = sum(range(7,31)) = 444
    assert volume_24h_at(candles, 30 * 3_600_000) == sum(range(7, 31))


def test_volume_24h_at_before_any_candle_yields_zero():
    candles = [(100_000, 5.0)]
    assert volume_24h_at(candles, 50_000) == 0.0


# --------------------------------------------------------------------------- #
# Stats aggregator
# --------------------------------------------------------------------------- #


def test_stats_for_empty_returns_nones():
    st = stats_for([])
    assert st["n"] == 0
    assert st["profit_factor"] is None
    assert st["win_rate"] is None


def test_stats_for_all_winners_pf_undefined():
    trades = [{"net_pnl": 1.0}, {"net_pnl": 2.0}]
    st = stats_for(trades)
    assert st["wins"] == 2
    assert st["losses"] == 0
    assert st["profit_factor"] is None  # no losses → undefined


def test_stats_for_mixed_computes_pf():
    trades = [{"net_pnl": 3.0}, {"net_pnl": -1.0}, {"net_pnl": 1.0}]
    st = stats_for(trades)
    # PF = (3+1) / 1 = 4.0
    assert st["profit_factor"] == 4.0
    assert st["wins"] == 2
    assert st["losses"] == 1
