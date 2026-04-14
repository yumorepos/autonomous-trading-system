"""
Cross-Exchange Funding Rate Spread Scanner.

Focus: Hyperliquid ↔ Kraken arbitrage (user's tradeable pair).
Binance / Bybit are included as DATA-ONLY comparison sources
(user cannot execute there — Canada restrictions).

All rates are normalized to 8h-equivalent before spread comparison:
  HL:      hourly      → * 8  (HIP-3: raw / multiplier, then * 8)
  Kraken:  4-hourly    → * 2
  Binance: 8-hourly    → * 1
  Bybit:   8-hourly    → * 1

Entry threshold: |spread| must exceed round-trip fees on BOTH legs.
Volume filter:   $5M 24h on BOTH legs.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional

import requests

from src.collectors.exchange_adapters.kraken import KrakenAdapter

logger = logging.getLogger(__name__)

# ---------- Constants ------------------------------------------------------

MIN_VOLUME_USD = 5_000_000  # $5M / 24h on each leg
FUNDING_CYCLES_PER_YEAR = 3 * 365  # 8h cycles

# Fees in percent of notional (one-way). Format: {"maker": x, "taker": y}.
FEES = {
    "HL_native": {"maker": 0.0001, "taker": 0.00035},
    "HL_HIP3":   {"maker": 0.0003, "taker": 0.0009},
    "Kraken":    {"maker": 0.0002, "taker": 0.0005},
    "Binance":   {"maker": 0.0002, "taker": 0.0004},
    "Bybit":     {"maker": 0.0002, "taker": 0.00055},
}

EXECUTABLE_EXCHANGES = {"Kraken"}

REQUEST_TIMEOUT = 10


# ---------- Sync fetchers for HL / Binance / Bybit ------------------------
# We intentionally keep these self-contained (sync / requests) rather than
# wiring into the async live-trading adapters. The scanner is a read-only
# side tool and must not touch the trading plumbing.


def _fetch_hl() -> tuple[dict[str, dict], None]:
    """
    Returns {asset: {"rate_1h": float, "volume_24h": float,
                     "is_hip3": bool, "multiplier": float}}.
    """
    info_url = "https://api.hyperliquid.xyz/info"
    out: dict[str, dict] = {}

    # 1) meta + asset ctxs (rates, volumes, mark price)
    try:
        r = requests.post(info_url, json={"type": "metaAndAssetCtxs"}, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except (requests.RequestException, ValueError) as e:
        logger.error("HL metaAndAssetCtxs failed: %s", e)
        return out, None

    if not isinstance(data, list) or len(data) < 2:
        logger.error("HL metaAndAssetCtxs malformed")
        return out, None

    meta, ctxs = data[0], data[1]
    universe = meta.get("universe", [])

    # 2) meta (for HIP-3 multipliers, which live under universe[i].extra)
    multipliers: dict[str, float] = {}
    hip3_flags: dict[str, bool] = {}
    try:
        r2 = requests.post(info_url, json={"type": "meta"}, timeout=REQUEST_TIMEOUT)
        r2.raise_for_status()
        meta2 = r2.json()
        for entry in meta2.get("universe", []):
            name = entry.get("name")
            if not name:
                continue
            extra = entry.get("extra") or {}
            mult = extra.get("fundingMultiplier")
            if mult is not None:
                try:
                    mult_f = float(mult)
                    if mult_f > 0:
                        multipliers[name] = mult_f
                        hip3_flags[name] = mult_f != 1.0
                except (TypeError, ValueError):
                    pass
    except (requests.RequestException, ValueError) as e:
        logger.warning("HL meta (HIP-3 multipliers) failed, assuming mult=1: %s", e)

    for uni, ctx in zip(universe, ctxs):
        name = uni.get("name")
        if not name:
            continue
        try:
            rate = float(ctx.get("funding", 0) or 0)
            mark = float(ctx.get("markPx", 0) or 0)
            day_vlm = float(ctx.get("dayNtlVlm", 0) or 0)
        except (TypeError, ValueError):
            continue
        mult = multipliers.get(name, 1.0)
        is_hip3 = hip3_flags.get(name, False)
        out[name] = {
            "rate_1h": rate,
            "volume_24h": day_vlm,
            "mark_price": mark,
            "is_hip3": is_hip3,
            "multiplier": mult,
        }
    return out, None


def _fetch_binance() -> dict[str, dict]:
    """Returns {asset: {"rate_8h": float, "volume_24h": float}}."""
    out: dict[str, dict] = {}
    try:
        # Funding rates
        pm = requests.get(
            "https://fapi.binance.com/fapi/v1/premiumIndex",
            timeout=REQUEST_TIMEOUT,
        )
        pm.raise_for_status()
        premium = pm.json()

        # 24h volume (quote volume is USD-ish)
        tk = requests.get(
            "https://fapi.binance.com/fapi/v1/ticker/24hr",
            timeout=REQUEST_TIMEOUT,
        )
        tk.raise_for_status()
        tickers = tk.json()
    except (requests.RequestException, ValueError) as e:
        logger.error("Binance fetch failed: %s", e)
        return out

    quote_vol: dict[str, float] = {}
    for t in tickers:
        sym = t.get("symbol", "")
        if not sym.endswith("USDT"):
            continue
        try:
            quote_vol[sym] = float(t.get("quoteVolume") or 0)
        except (TypeError, ValueError):
            pass

    for p in premium:
        sym = p.get("symbol", "")
        if not sym.endswith("USDT"):
            continue
        base = sym[:-4]
        try:
            rate = float(p.get("lastFundingRate") or 0)
        except (TypeError, ValueError):
            continue
        out[base] = {
            "rate_8h": rate,
            "volume_24h": quote_vol.get(sym, 0.0),
        }
    return out


def _fetch_bybit() -> dict[str, dict]:
    """Returns {asset: {"rate_8h": float, "volume_24h": float}}."""
    out: dict[str, dict] = {}
    try:
        r = requests.get(
            "https://api.bybit.com/v5/market/tickers",
            params={"category": "linear"},
            timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        payload = r.json()
    except (requests.RequestException, ValueError) as e:
        logger.error("Bybit fetch failed: %s", e)
        return out

    result = payload.get("result") or {}
    for t in result.get("list", []):
        sym = t.get("symbol", "")
        if not sym.endswith("USDT"):
            continue
        base = sym[:-4]
        try:
            rate = float(t.get("fundingRate") or 0)
            turnover = float(t.get("turnover24h") or 0)
        except (TypeError, ValueError):
            continue
        out[base] = {"rate_8h": rate, "volume_24h": turnover}
    return out


# ---------- Normalization helpers -----------------------------------------


def hl_rate_to_8h(rate_1h: float, multiplier: float = 1.0) -> float:
    """HL pays hourly; HIP-3 has a funding multiplier — divide it out first."""
    mult = multiplier if multiplier and multiplier > 0 else 1.0
    true_rate_1h = rate_1h / mult
    return true_rate_1h * 8


def kraken_rate_to_8h(rate_4h: float) -> float:
    return rate_4h * 2


def _fee_cost_pct(
    hl_is_hip3: bool,
    other_exchange: str,
    mode: str,  # "optimistic" or "pessimistic"
) -> float:
    """
    Round-trip fee cost (as fraction of notional, not percent).
    Optimistic: MAKER entry, TAKER exit on both legs.
    Pessimistic: TAKER entry, TAKER exit on both legs.
    """
    hl_key = "HL_HIP3" if hl_is_hip3 else "HL_native"
    hl_fees = FEES[hl_key]
    other_fees = FEES[other_exchange]

    if mode == "optimistic":
        hl_cost = hl_fees["maker"] + hl_fees["taker"]
        other_cost = other_fees["maker"] + other_fees["taker"]
    else:  # pessimistic
        hl_cost = hl_fees["taker"] * 2
        other_cost = other_fees["taker"] * 2
    return hl_cost + other_cost


# ---------- Scanner -------------------------------------------------------


class CrossExchangeSpreadScanner:
    """Scans funding spreads across HL, Kraken, Binance, Bybit."""

    def __init__(self):
        self.kraken = KrakenAdapter()

    def fetch_all_funding_rates(self) -> dict:
        hl_raw, _ = _fetch_hl()
        kraken_rates = self.kraken.get_funding_rates()
        kraken_vols = self.kraken.get_volumes()
        binance = _fetch_binance()
        bybit = _fetch_bybit()

        hl_norm: dict[str, dict] = {}
        for asset, d in hl_raw.items():
            hl_norm[asset] = {
                "rate_8h": hl_rate_to_8h(d["rate_1h"], d.get("multiplier", 1.0)),
                "volume_24h": d["volume_24h"],
                "is_hip3": d["is_hip3"],
                "multiplier": d["multiplier"],
            }

        kraken_norm: dict[str, dict] = {}
        for asset, rate_4h in kraken_rates.items():
            kraken_norm[asset] = {
                "rate_8h": kraken_rate_to_8h(rate_4h),
                "volume_24h": kraken_vols.get(asset, 0.0),
            }

        binance_norm: dict[str, dict] = {
            a: {"rate_8h": d["rate_8h"], "volume_24h": d["volume_24h"]}
            for a, d in binance.items()
        }
        bybit_norm: dict[str, dict] = {
            a: {"rate_8h": d["rate_8h"], "volume_24h": d["volume_24h"]}
            for a, d in bybit.items()
        }

        return {
            "HL": hl_norm,
            "Kraken": kraken_norm,
            "Binance": binance_norm,
            "Bybit": bybit_norm,
        }

    def compute_spreads(self, rates: dict) -> list[dict]:
        hl = rates.get("HL", {})
        results: list[dict] = []

        for asset, hl_data in hl.items():
            hl_rate = hl_data["rate_8h"]
            hl_vol = hl_data["volume_24h"]
            hl_is_hip3 = hl_data.get("is_hip3", False)

            if hl_vol < MIN_VOLUME_USD:
                continue

            for other_name in ("Kraken", "Binance", "Bybit"):
                other_data = rates.get(other_name, {}).get(asset)
                if other_data is None:
                    continue
                other_rate = other_data["rate_8h"]
                other_vol = other_data["volume_24h"]
                if other_vol < MIN_VOLUME_USD:
                    continue

                spread = hl_rate - other_rate
                abs_spread = abs(spread)
                direction = (
                    f"short_HL_long_{other_name}"
                    if spread > 0
                    else f"long_HL_short_{other_name}"
                )

                fee_opt = _fee_cost_pct(hl_is_hip3, other_name, "optimistic")
                fee_pes = _fee_cost_pct(hl_is_hip3, other_name, "pessimistic")

                net_spread_8h_opt = abs_spread - fee_opt
                net_spread_8h_pes = abs_spread - fee_pes
                net_apy_opt = net_spread_8h_opt * FUNDING_CYCLES_PER_YEAR * 100
                net_apy_pes = net_spread_8h_pes * FUNDING_CYCLES_PER_YEAR * 100

                if net_apy_opt <= 0:
                    continue

                results.append({
                    "asset": asset,
                    "other_exchange": other_name,
                    "hl_rate_8h": hl_rate,
                    "other_rate_8h": other_rate,
                    "spread_8h": spread,
                    "abs_spread_8h": abs_spread,
                    "direction": direction,
                    "fee_cost_optimistic": fee_opt,
                    "fee_cost_pessimistic": fee_pes,
                    "net_spread_8h_optimistic": net_spread_8h_opt,
                    "net_spread_8h_pessimistic": net_spread_8h_pes,
                    "net_apy_optimistic": net_apy_opt,
                    "net_apy_pessimistic": net_apy_pes,
                    "net_apy": net_apy_opt,  # sort key
                    "hl_volume_24h": hl_vol,
                    "other_volume_24h": other_vol,
                    "hl_is_hip3": hl_is_hip3,
                    "hl_multiplier": hl_data.get("multiplier", 1.0),
                    "executable": other_name in EXECUTABLE_EXCHANGES,
                })

        results.sort(key=lambda r: r["net_apy"], reverse=True)
        return results

    def scan_once(self) -> dict:
        t0 = time.monotonic()
        rates = self.fetch_all_funding_rates()
        spreads = self.compute_spreads(rates)
        return {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "scan_duration_s": round(time.monotonic() - t0, 3),
            "rates": rates,
            "spreads": spreads,
        }
