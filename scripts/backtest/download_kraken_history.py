"""
Download historical funding rates from Kraken for assets that overlap
with our HL historical dataset.

Kraken endpoint:
    GET https://futures.kraken.com/derivatives/api/v3/historicalfundingrates?symbol=PF_{ASSET}USD

Response: {"rates": [{"timestamp": "<iso>", "fundingRate": x, "relativeFundingRate": y}, ...]}
We use relativeFundingRate (already notional-relative, 4h cadence).
Normalize to 8h-equivalent by multiplying by 2, then write:
    data/historical/kraken_funding_rates.csv
with columns: timestamp, asset, funding_rate_8h.

Rate limit: 200ms between requests.
"""
from __future__ import annotations

import csv
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

HL_CSV = Path("data/historical/funding_rates.csv")
OUT_CSV = Path("data/historical/kraken_funding_rates.csv")
ENDPOINT = "https://futures.kraken.com/derivatives/api/v4/historicalfundingrates"
REQUEST_DELAY_S = 0.2
REQUEST_TIMEOUT = 15

# HL-asset → Kraken symbol-base overrides.
# Kraken uses XBT for BTC, and drops the "k" prefix on scaled assets.
SYMBOL_OVERRIDES = {
    "BTC": "XBT",
    "kPEPE": "PEPE",
    "kBONK": "BONK",
    "kSHIB": "SHIB",
    "kFLOKI": "FLOKI",
}


def hl_asset_to_kraken_symbol(asset: str) -> str:
    base = SYMBOL_OVERRIDES.get(asset, asset)
    return f"PF_{base}USD"


def parse_iso_to_ms(ts: str) -> int:
    # Kraken returns e.g. "2024-07-18T12:00:00.000Z"
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def fetch_kraken(symbol: str) -> list[dict]:
    r = requests.get(ENDPOINT, params={"symbol": symbol}, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    return data.get("rates") or []


def main() -> int:
    if not HL_CSV.exists():
        print(f"ERROR: {HL_CSV} not found", file=sys.stderr)
        return 1

    hl = pd.read_csv(HL_CSV)
    hl_assets = sorted(hl["asset"].unique().tolist())
    hl_ts_min = int(hl["timestamp"].min())
    hl_ts_max = int(hl["timestamp"].max())
    print(f"HL has {len(hl_assets)} unique assets, ts range {hl_ts_min}..{hl_ts_max}")
    print(f"HL assets: {hl_assets}")

    rows: list[tuple[int, str, float]] = []
    downloaded = []
    empty = []
    missing = []
    errors = []

    for i, asset in enumerate(hl_assets, 1):
        symbol = hl_asset_to_kraken_symbol(asset)
        print(f"[{i}/{len(hl_assets)}] {asset} → {symbol} ... ", end="", flush=True)
        try:
            rates = fetch_kraken(symbol)
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else "?"
            if status == 404:
                print("not listed on Kraken")
                missing.append(asset)
            else:
                print(f"HTTP {status}")
                errors.append((asset, f"HTTP {status}"))
            time.sleep(REQUEST_DELAY_S)
            continue
        except Exception as e:
            print(f"ERROR {e}")
            errors.append((asset, str(e)))
            time.sleep(REQUEST_DELAY_S)
            continue

        if not rates:
            print("empty response")
            empty.append(asset)
            time.sleep(REQUEST_DELAY_S)
            continue

        count_in_range = 0
        for entry in rates:
            ts_raw = entry.get("timestamp")
            rel = entry.get("relativeFundingRate")
            if ts_raw is None or rel is None:
                continue
            try:
                ts_ms = parse_iso_to_ms(ts_raw)
                rel_f = float(rel)
            except (TypeError, ValueError):
                continue
            # Keep rows that overlap HL window (with a small pad).
            if ts_ms < hl_ts_min - 24 * 3600 * 1000 or ts_ms > hl_ts_max + 24 * 3600 * 1000:
                continue
            rate_8h = rel_f * 2.0  # Kraken 4h → 8h equivalent
            rows.append((ts_ms, asset, rate_8h))
            count_in_range += 1

        print(f"{len(rates)} rates ({count_in_range} in HL window)")
        downloaded.append((asset, count_in_range))
        time.sleep(REQUEST_DELAY_S)

    # Write out CSV
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "asset", "funding_rate_8h"])
        for r in sorted(rows):
            w.writerow(r)

    print()
    print("=" * 60)
    print(f"Wrote {len(rows)} rows to {OUT_CSV}")
    print(f"Downloaded assets: {len(downloaded)}")
    for a, n in downloaded:
        print(f"  {a}: {n}")
    if empty:
        print(f"Empty / insufficient history: {empty}")
    if missing:
        print(f"Not listed on Kraken (404): {missing}")
    if errors:
        print(f"Errors: {errors}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
