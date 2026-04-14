"""Tests for the cross-exchange spread scanner and Kraken adapter."""

from __future__ import annotations

import math

import pytest

from src.collectors.exchange_adapters.kraken import KrakenAdapter
from src.collectors.spread_scanner import (
    CrossExchangeSpreadScanner,
    FEES,
    MIN_VOLUME_USD,
    _fee_cost_pct,
    hl_rate_to_8h,
    kraken_rate_to_8h,
)


# --------------------------- normalization --------------------------------


def test_kraken_normalize_4h_to_8h():
    assert kraken_rate_to_8h(0.0001) == pytest.approx(0.0002)
    assert KrakenAdapter.normalize_rate_to_8h(-0.0005) == pytest.approx(-0.0010)
    assert kraken_rate_to_8h(0.0) == 0.0


def test_hl_normalize_1h_to_8h_no_multiplier():
    # Default multiplier=1 (non-HIP-3 perp)
    assert hl_rate_to_8h(0.0001) == pytest.approx(0.0008)
    assert hl_rate_to_8h(0.00005, 1.0) == pytest.approx(0.0004)


def test_hl_normalize_with_hip3_multiplier():
    # HIP-3 with 5x multiplier: raw rate is 5x the "true" rate
    # raw=0.0005 with mult=5 → true=0.0001/h → 0.0008/8h
    assert hl_rate_to_8h(0.0005, 5.0) == pytest.approx(0.0008)
    # 10x multiplier edge case
    assert hl_rate_to_8h(0.001, 10.0) == pytest.approx(0.0008)


def test_hl_normalize_bad_multiplier_falls_back_to_1():
    # Zero/negative/None all fall back to 1.0
    assert hl_rate_to_8h(0.0001, 0.0) == pytest.approx(0.0008)
    assert hl_rate_to_8h(0.0001, -2.0) == pytest.approx(0.0008)


# --------------------------- fees ----------------------------------------


def test_fee_cost_optimistic_hl_kraken():
    # HL native maker+taker + Kraken maker+taker
    expected = (FEES["HL_native"]["maker"] + FEES["HL_native"]["taker"]
                + FEES["Kraken"]["maker"] + FEES["Kraken"]["taker"])
    assert _fee_cost_pct(False, "Kraken", "optimistic") == pytest.approx(expected)
    # = 0.0001 + 0.00035 + 0.0002 + 0.0005 = 0.00115 (0.115% round-trip)
    assert _fee_cost_pct(False, "Kraken", "optimistic") == pytest.approx(0.00115)


def test_fee_cost_optimistic_hl_binance():
    expected = 0.0001 + 0.00035 + 0.0002 + 0.0004
    assert _fee_cost_pct(False, "Binance", "optimistic") == pytest.approx(expected)


def test_fee_cost_optimistic_hl_bybit():
    expected = 0.0001 + 0.00035 + 0.0002 + 0.00055
    assert _fee_cost_pct(False, "Bybit", "optimistic") == pytest.approx(expected)


def test_fee_cost_pessimistic_taker_both():
    # Taker*2 on both legs
    expected = (FEES["HL_native"]["taker"] * 2) + (FEES["Kraken"]["taker"] * 2)
    assert _fee_cost_pct(False, "Kraken", "pessimistic") == pytest.approx(expected)


def test_fee_cost_hip3_uses_higher_fee_schedule():
    native = _fee_cost_pct(False, "Kraken", "optimistic")
    hip3 = _fee_cost_pct(True, "Kraken", "optimistic")
    assert hip3 > native
    # HIP-3: 0.0003 + 0.0009 + 0.0002 + 0.0005 = 0.0019
    assert hip3 == pytest.approx(0.0019)


# --------------------------- spread computation ---------------------------


def _make_rates(hl=None, kraken=None, binance=None, bybit=None):
    return {
        "HL": hl or {},
        "Kraken": kraken or {},
        "Binance": binance or {},
        "Bybit": bybit or {},
    }


def test_compute_spread_short_hl_direction():
    scanner = CrossExchangeSpreadScanner()
    # HL rate > Kraken rate → spread positive → short_HL
    rates = _make_rates(
        hl={"SOL": {"rate_8h": 0.01, "volume_24h": 50e6,
                    "is_hip3": False, "multiplier": 1.0}},
        kraken={"SOL": {"rate_8h": 0.002, "volume_24h": 40e6}},
    )
    out = scanner.compute_spreads(rates)
    assert len(out) == 1
    r = out[0]
    assert r["asset"] == "SOL"
    assert r["other_exchange"] == "Kraken"
    assert r["direction"] == "short_HL_long_Kraken"
    assert r["spread_8h"] == pytest.approx(0.008)
    assert r["executable"] is True


def test_compute_spread_long_hl_direction():
    scanner = CrossExchangeSpreadScanner()
    rates = _make_rates(
        hl={"BTC": {"rate_8h": -0.005, "volume_24h": 100e6,
                    "is_hip3": False, "multiplier": 1.0}},
        kraken={"BTC": {"rate_8h": 0.002, "volume_24h": 80e6}},
    )
    out = scanner.compute_spreads(rates)
    assert out[0]["direction"] == "long_HL_short_Kraken"


def test_compute_spread_filters_low_volume_hl():
    scanner = CrossExchangeSpreadScanner()
    rates = _make_rates(
        hl={"DOGE": {"rate_8h": 0.01, "volume_24h": 1e6,  # below threshold
                     "is_hip3": False, "multiplier": 1.0}},
        kraken={"DOGE": {"rate_8h": 0.0, "volume_24h": 50e6}},
    )
    assert scanner.compute_spreads(rates) == []


def test_compute_spread_filters_low_volume_other():
    scanner = CrossExchangeSpreadScanner()
    rates = _make_rates(
        hl={"DOGE": {"rate_8h": 0.01, "volume_24h": 50e6,
                     "is_hip3": False, "multiplier": 1.0}},
        kraken={"DOGE": {"rate_8h": 0.0, "volume_24h": 1e6}},  # below
    )
    assert scanner.compute_spreads(rates) == []


def test_compute_spread_filters_below_fee_threshold():
    scanner = CrossExchangeSpreadScanner()
    # 0.0005 spread < 0.00115 round-trip fees → filtered
    rates = _make_rates(
        hl={"SOL": {"rate_8h": 0.0005, "volume_24h": 50e6,
                    "is_hip3": False, "multiplier": 1.0}},
        kraken={"SOL": {"rate_8h": 0.0, "volume_24h": 40e6}},
    )
    assert scanner.compute_spreads(rates) == []


def test_executable_flag_kraken_vs_others():
    scanner = CrossExchangeSpreadScanner()
    rates = _make_rates(
        hl={"SOL": {"rate_8h": 0.01, "volume_24h": 50e6,
                    "is_hip3": False, "multiplier": 1.0}},
        kraken={"SOL": {"rate_8h": 0.0, "volume_24h": 40e6}},
        binance={"SOL": {"rate_8h": 0.0, "volume_24h": 100e6}},
        bybit={"SOL": {"rate_8h": 0.0, "volume_24h": 80e6}},
    )
    out = scanner.compute_spreads(rates)
    by_ex = {r["other_exchange"]: r for r in out}
    assert by_ex["Kraken"]["executable"] is True
    assert by_ex["Binance"]["executable"] is False
    assert by_ex["Bybit"]["executable"] is False


def test_missing_asset_on_other_exchange_handled():
    scanner = CrossExchangeSpreadScanner()
    # HL has TOKEN, nobody else does → no results (empty, no crash)
    rates = _make_rates(
        hl={"TOKEN": {"rate_8h": 0.01, "volume_24h": 50e6,
                      "is_hip3": False, "multiplier": 1.0}},
    )
    assert scanner.compute_spreads(rates) == []


def test_empty_rates_handled():
    scanner = CrossExchangeSpreadScanner()
    assert scanner.compute_spreads(_make_rates()) == []
    assert scanner.compute_spreads({}) == []


def test_net_apy_computation():
    scanner = CrossExchangeSpreadScanner()
    # spread = 0.01 - 0.0 = 0.01 (per 8h)
    # fee_opt (HL-Kraken) = 0.00115
    # net_spread_8h = 0.01 - 0.00115 = 0.00885
    # net_apy = 0.00885 * 3 * 365 * 100 = 969.075
    rates = _make_rates(
        hl={"SOL": {"rate_8h": 0.01, "volume_24h": 50e6,
                    "is_hip3": False, "multiplier": 1.0}},
        kraken={"SOL": {"rate_8h": 0.0, "volume_24h": 40e6}},
    )
    r = scanner.compute_spreads(rates)[0]
    assert r["net_spread_8h_optimistic"] == pytest.approx(0.00885)
    assert r["net_apy_optimistic"] == pytest.approx(0.00885 * 3 * 365 * 100)


def test_results_sorted_by_net_apy_desc():
    scanner = CrossExchangeSpreadScanner()
    rates = _make_rates(
        hl={
            "A": {"rate_8h": 0.005, "volume_24h": 50e6,
                  "is_hip3": False, "multiplier": 1.0},
            "B": {"rate_8h": 0.02, "volume_24h": 50e6,
                  "is_hip3": False, "multiplier": 1.0},
        },
        kraken={
            "A": {"rate_8h": 0.0, "volume_24h": 40e6},
            "B": {"rate_8h": 0.0, "volume_24h": 40e6},
        },
    )
    out = scanner.compute_spreads(rates)
    assert [r["asset"] for r in out] == ["B", "A"]


# --------------------------- Kraken adapter parsing -----------------------


def test_kraken_parse_base_asset():
    assert KrakenAdapter._parse_base_asset("PF_SOLUSD") == "SOL"
    assert KrakenAdapter._parse_base_asset("PF_ETHUSD") == "ETH"
    # XBT → BTC alias
    assert KrakenAdapter._parse_base_asset("PF_XBTUSD") == "BTC"
    # Non-PF and malformed
    assert KrakenAdapter._parse_base_asset("PI_XBTUSD") is None
    assert KrakenAdapter._parse_base_asset("SOLUSD") is None
    assert KrakenAdapter._parse_base_asset("") is None
    assert KrakenAdapter._parse_base_asset("PF_SOLEUR") is None
    assert KrakenAdapter._parse_base_asset("PF_USD") is None
