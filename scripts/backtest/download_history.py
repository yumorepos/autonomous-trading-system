#!/usr/bin/env python3
"""
Download historical data from Hyperliquid public API for backtesting.

Fetches for top 30 perp markets by volume:
- Funding rate history (8h intervals)
- Candlestick/price data (1h candles)

Stores data as parquet files in data/historical/.

Idempotent: re-running only downloads missing/new data.

Usage:
    python scripts/backtest/download_history.py            # 90 days (default)
    python scripts/backtest/download_history.py --days 30  # 30 days
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:
    print("pyarrow required: pip install pyarrow")
    sys.exit(1)

try:
    from tqdm import tqdm
except ImportError:
    # Fallback: no progress bar
    tqdm = None  # type: ignore[assignment]

REPO_ROOT = Path(__file__).resolve().parents[2]
API_URL = "https://api.hyperliquid.xyz/info"
RATE_LIMIT_SEC = 0.25
MAX_RETRIES = 4
DATA_DIR = REPO_ROOT / "data" / "historical"


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def api_post(body: dict, timeout: float = 30.0) -> dict | list:
    """POST to Hyperliquid info API with retry on 429 / transient errors."""
    for attempt in range(MAX_RETRIES):
        req = urllib.request.Request(
            API_URL,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
            return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < MAX_RETRIES - 1:
                wait = 2 ** (attempt + 1)
                print(f"    Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            raise
        except (urllib.error.URLError, OSError) as e:
            if attempt < MAX_RETRIES - 1:
                wait = 2 ** attempt
                print(f"    Network error ({e}), retrying in {wait}s...")
                time.sleep(wait)
                continue
            raise
    return []


def get_top_assets(n: int = 30) -> list[str]:
    """Get top N assets by 24h volume from Hyperliquid meta endpoint."""
    print("Fetching asset universe...")
    resp = api_post({"type": "metaAndAssetCtxs"})
    universe = resp[0]["universe"]
    contexts = resp[1]

    assets_with_volume = []
    for u, ctx in zip(universe, contexts):
        name = u["name"]
        volume = float(ctx.get("dayNtlVlm", 0) or 0)
        assets_with_volume.append((name, volume))

    assets_with_volume.sort(key=lambda x: x[1], reverse=True)
    top = [a[0] for a in assets_with_volume[:n]]
    print(f"Top {n} assets by volume: {', '.join(top[:10])}{'...' if n > 10 else ''}")
    return top


# ---------------------------------------------------------------------------
# Idempotent loading helpers
# ---------------------------------------------------------------------------

def _load_existing_funding(path: Path) -> dict[str, int]:
    """Load existing funding parquet and return {asset: max_timestamp_ms}."""
    if not path.exists():
        return {}
    table = pq.read_table(path)
    df_dict = table.to_pydict()
    result: dict[str, int] = {}
    for asset, ts in zip(df_dict["asset"], df_dict["timestamp"]):
        if asset not in result or ts > result[asset]:
            result[asset] = ts
    return result


def _load_existing_candles(path: Path) -> int | None:
    """Load existing candle parquet and return max timestamp_ms, or None."""
    if not path.exists():
        return None
    table = pq.read_table(path, columns=["timestamp"])
    ts_list = table.column("timestamp").to_pylist()
    return max(ts_list) if ts_list else None


# ---------------------------------------------------------------------------
# Downloaders
# ---------------------------------------------------------------------------

def download_funding_rates(assets: list[str], days: int) -> None:
    """Download 8-hourly funding rates for all assets into a single parquet."""
    out_path = DATA_DIR / "funding_rates.parquet"
    existing_max = _load_existing_funding(out_path)

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    default_start_ms = now_ms - (days * 24 * 3600 * 1000)

    all_timestamps: list[int] = []
    all_assets: list[str] = []
    all_rates: list[float] = []

    # Load existing data first
    if out_path.exists():
        table = pq.read_table(out_path)
        d = table.to_pydict()
        all_timestamps.extend(d["timestamp"])
        all_assets.extend(d["asset"])
        all_rates.extend(d["funding_rate_8h"])

    iterator = tqdm(assets, desc="Funding rates", unit="asset") if tqdm else assets
    for asset in iterator:
        # Start from after the last known timestamp for this asset
        start_ms = existing_max.get(asset, default_start_ms - 1) + 1
        if start_ms >= now_ms:
            continue  # Already up to date

        cursor = start_ms
        asset_count = 0

        while cursor < now_ms:
            time.sleep(RATE_LIMIT_SEC)
            try:
                data = api_post({
                    "type": "fundingHistory",
                    "coin": asset,
                    "startTime": cursor,
                })
            except Exception as e:
                print(f"\n  Error fetching funding for {asset}: {e}")
                break

            if not data:
                break

            for entry in data:
                ts = int(entry["time"])
                rate = float(entry["fundingRate"])
                all_timestamps.append(ts)
                all_assets.append(asset)
                all_rates.append(rate)
                asset_count += 1
                cursor = max(cursor, ts + 1)

            if len(data) < 500:
                break

        if tqdm and hasattr(iterator, 'set_postfix'):
            iterator.set_postfix(new=asset_count)

    # Deduplicate by (timestamp, asset)
    seen: set[tuple[int, str]] = set()
    deduped_ts, deduped_asset, deduped_rate = [], [], []
    for ts, asset, rate in zip(all_timestamps, all_assets, all_rates):
        key = (ts, asset)
        if key not in seen:
            seen.add(key)
            deduped_ts.append(ts)
            deduped_asset.append(asset)
            deduped_rate.append(rate)

    # Sort by timestamp, asset
    combined = sorted(zip(deduped_ts, deduped_asset, deduped_rate))
    if not combined:
        print("No funding data collected.")
        return

    ts_sorted, asset_sorted, rate_sorted = zip(*combined)

    table = pa.table({
        "timestamp": pa.array(ts_sorted, type=pa.int64()),
        "asset": pa.array(asset_sorted, type=pa.string()),
        "funding_rate_8h": pa.array(rate_sorted, type=pa.float64()),
    })

    out_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, out_path)
    print(f"Wrote {len(combined)} funding records to {out_path}")


def download_candles(assets: list[str], days: int) -> None:
    """Download hourly OHLCV candles per asset as individual parquet files."""
    candle_dir = DATA_DIR / "candles"
    candle_dir.mkdir(parents=True, exist_ok=True)

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    default_start_ms = now_ms - (days * 24 * 3600 * 1000)

    iterator = tqdm(assets, desc="Candles", unit="asset") if tqdm else assets
    for asset in iterator:
        candle_path = candle_dir / f"{asset}_1h.parquet"

        # Idempotent: start from after last known candle
        existing_max = _load_existing_candles(candle_path)
        start_ms = (existing_max + 1) if existing_max else default_start_ms

        if start_ms >= now_ms:
            continue  # Already up to date

        # Load existing data
        existing_data: dict[int, dict] = {}
        if candle_path.exists():
            table = pq.read_table(candle_path)
            d = table.to_pydict()
            for i in range(len(d["timestamp"])):
                existing_data[d["timestamp"][i]] = {
                    "open": d["open"][i],
                    "high": d["high"][i],
                    "low": d["low"][i],
                    "close": d["close"][i],
                    "volume": d["volume"][i],
                }

        cursor = start_ms
        new_count = 0

        while cursor < now_ms:
            time.sleep(RATE_LIMIT_SEC)
            chunk_end = min(cursor + 30 * 24 * 3600 * 1000, now_ms)
            try:
                data = api_post({
                    "type": "candleSnapshot",
                    "req": {
                        "coin": asset,
                        "interval": "1h",
                        "startTime": cursor,
                        "endTime": chunk_end,
                    },
                })
            except Exception as e:
                print(f"\n  Error fetching candles for {asset}: {e}")
                break

            if not data:
                break

            for c in data:
                ts = int(c["t"])
                if ts not in existing_data:
                    existing_data[ts] = {
                        "open": float(c["o"]),
                        "high": float(c["h"]),
                        "low": float(c["l"]),
                        "close": float(c["c"]),
                        "volume": float(c["v"]),
                    }
                    new_count += 1
                cursor = max(cursor, ts + 1)

            if len(data) < 500:
                break

        if tqdm and hasattr(iterator, 'set_postfix'):
            iterator.set_postfix(new=new_count)

        # Write combined data
        if existing_data:
            sorted_ts = sorted(existing_data.keys())
            table = pa.table({
                "timestamp": pa.array(sorted_ts, type=pa.int64()),
                "open": pa.array([existing_data[t]["open"] for t in sorted_ts], type=pa.float64()),
                "high": pa.array([existing_data[t]["high"] for t in sorted_ts], type=pa.float64()),
                "low": pa.array([existing_data[t]["low"] for t in sorted_ts], type=pa.float64()),
                "close": pa.array([existing_data[t]["close"] for t in sorted_ts], type=pa.float64()),
                "volume": pa.array([existing_data[t]["volume"] for t in sorted_ts], type=pa.float64()),
            })
            pq.write_table(table, candle_path)

    total_candle_files = len(list(candle_dir.glob("*_1h.parquet")))
    print(f"Candle files in {candle_dir}: {total_candle_files}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download Hyperliquid historical data for backtesting"
    )
    parser.add_argument("--days", type=int, default=90, help="Days of history (default: 90)")
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print(f"=== Downloading {args.days} days of Hyperliquid data ===")
    print(f"Output: {DATA_DIR}\n")

    # Step 1: Get top 30 assets
    assets = get_top_assets(30)
    time.sleep(RATE_LIMIT_SEC)

    # Step 2: Download funding rates
    print(f"\n--- Funding Rates ---")
    download_funding_rates(assets, args.days)

    # Step 3: Download candles
    print(f"\n--- Hourly Candles ---")
    download_candles(assets, args.days)

    print(f"\n=== Download complete ===")


if __name__ == "__main__":
    main()
