#!/usr/bin/env python3
"""
Download historical data from Hyperliquid public API.

Fetches:
- 8-hourly funding rates for top 30 assets by volume
- Hourly OHLCV candles

Usage:
    python scripts/data/download_hl_history.py           # 90 days (default)
    python scripts/data/download_hl_history.py --days 30  # 30 days
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
API_URL = "https://api.hyperliquid.xyz/info"
RATE_LIMIT_SEC = 0.1  # 100ms between requests


def api_post(body: dict) -> dict | list:
    """POST to Hyperliquid info API."""
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=30)
    return json.loads(resp.read())


def get_top_assets(n: int = 30) -> list[str]:
    """Get top N assets by 24h volume."""
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
    print(f"Top {n} assets by volume: {', '.join(top)}")
    return top


def download_funding_rates(
    assets: list[str], days: int, out_path: Path
) -> None:
    """Download 8-hourly funding rates for all assets."""
    out_path.parent.mkdir(parents=True, exist_ok=True)

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = now_ms - (days * 24 * 3600 * 1000)

    rows: list[dict] = []
    total = len(assets)

    for i, asset in enumerate(assets, 1):
        print(f"  Funding [{i}/{total}] {asset}...", end="", flush=True)
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
                print(f" error: {e}")
                break

            if not data:
                break

            for entry in data:
                ts = int(entry["time"])
                rate = float(entry["fundingRate"])
                rows.append({
                    "timestamp": ts,
                    "asset": asset,
                    "funding_rate_8h": rate,
                })
                asset_count += 1
                cursor = max(cursor, ts + 1)

            # If we got fewer than expected, we've reached the end
            if len(data) < 500:
                break

        print(f" {asset_count} records")

    # Sort by timestamp, then asset
    rows.sort(key=lambda r: (r["timestamp"], r["asset"]))

    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "asset", "funding_rate_8h"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} funding records to {out_path}")


def download_candles(
    assets: list[str], days: int, out_dir: Path
) -> None:
    """Download hourly OHLCV candles for all assets."""
    out_dir.mkdir(parents=True, exist_ok=True)

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = now_ms - (days * 24 * 3600 * 1000)
    total = len(assets)

    for i, asset in enumerate(assets, 1):
        print(f"  Candles [{i}/{total}] {asset}...", end="", flush=True)
        candle_path = out_dir / f"{asset}_1h.csv"
        rows: list[dict] = []
        cursor = start_ms

        while cursor < now_ms:
            time.sleep(RATE_LIMIT_SEC)
            try:
                data = api_post({
                    "type": "candleSnapshot",
                    "coin": asset,
                    "interval": "1h",
                    "startTime": cursor,
                })
            except Exception as e:
                print(f" error: {e}")
                break

            if not data:
                break

            for c in data:
                ts = int(c["t"])
                rows.append({
                    "timestamp": ts,
                    "open": float(c["o"]),
                    "high": float(c["h"]),
                    "low": float(c["l"]),
                    "close": float(c["c"]),
                    "volume": float(c["v"]),
                })
                cursor = max(cursor, ts + 1)

            if len(data) < 500:
                break

        rows.sort(key=lambda r: r["timestamp"])

        # Deduplicate by timestamp
        seen = set()
        unique_rows = []
        for r in rows:
            if r["timestamp"] not in seen:
                seen.add(r["timestamp"])
                unique_rows.append(r)

        with open(candle_path, "w", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=["timestamp", "open", "high", "low", "close", "volume"]
            )
            writer.writeheader()
            writer.writerows(unique_rows)

        print(f" {len(unique_rows)} candles")

    print(f"Candles saved to {out_dir}/")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download Hyperliquid historical data")
    parser.add_argument("--days", type=int, default=90, help="Days of history (default: 90)")
    args = parser.parse_args()

    data_dir = REPO_ROOT / "data" / "historical"
    data_dir.mkdir(parents=True, exist_ok=True)

    print(f"=== Downloading {args.days} days of Hyperliquid data ===\n")

    # Step 1: Get top 30 assets
    assets = get_top_assets(30)
    time.sleep(RATE_LIMIT_SEC)

    # Step 2: Download funding rates
    print(f"\nDownloading funding rates...")
    download_funding_rates(assets, args.days, data_dir / "funding_rates.csv")

    # Step 3: Download candles
    print(f"\nDownloading hourly candles...")
    download_candles(assets, args.days, data_dir / "candles")

    print(f"\n=== Done ===")


if __name__ == "__main__":
    main()
