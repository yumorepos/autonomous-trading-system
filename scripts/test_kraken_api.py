#!/usr/bin/env python3
"""
Smoke-test the Kraken Futures public tickers endpoint.
Prints number of perp instruments, top 5 by USD volume, and their funding rates.
No auth required.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import requests  # noqa: E402

from src.collectors.exchange_adapters.kraken import (  # noqa: E402
    KrakenAdapter,
    TICKERS_URL,
)


def main() -> int:
    print(f"GET {TICKERS_URL}")
    try:
        r = requests.get(TICKERS_URL, timeout=10)
    except requests.RequestException as e:
        print(f"ERROR: request failed: {e}")
        return 1

    print(f"HTTP {r.status_code}")
    if not r.ok:
        print(f"Body: {r.text[:500]}")
        return 1

    payload = r.json()
    tickers = payload.get("tickers") or []
    print(f"Total tickers returned: {len(tickers)}")

    adapter = KrakenAdapter()

    # Parse using our adapter logic so this also smoke-tests the adapter.
    perp_rows = []
    for t in tickers:
        sym = t.get("symbol", "")
        base = adapter._parse_base_asset(sym)
        if base is None:
            continue
        try:
            raw_rate = float(t.get("fundingRate") or 0)
            mark = float(t.get("markPrice") or 0)
            vol = float(t.get("vol24h") or 0)
        except (TypeError, ValueError):
            continue
        if mark <= 0:
            continue
        # Kraken `fundingRate` is absolute USD/contract; divide by mark for
        # the relative rate (matches adapter logic).
        rel_rate_4h = raw_rate / mark
        perp_rows.append({
            "symbol": sym,
            "base": base,
            "rate_4h": rel_rate_4h,
            "rate_8h": KrakenAdapter.normalize_rate_to_8h(rel_rate_4h),
            "mark": mark,
            "vol24h": vol,
            "usd_vol": vol * mark,
        })

    print(f"USD-margined perps (PF_*): {len(perp_rows)}")

    perp_rows.sort(key=lambda x: x["usd_vol"], reverse=True)
    print("\nTop 5 by USD 24h volume:")
    print(f"  {'Symbol':<16} {'Base':<6} {'24h USD Vol':>18} "
          f"{'Rate 4h':>12} {'Rate 8h':>12}")
    print("  " + "-" * 70)
    for row in perp_rows[:5]:
        print(f"  {row['symbol']:<16} {row['base']:<6} "
              f"${row['usd_vol']:>16,.0f}  "
              f"{row['rate_4h']*100:>10.4f}%  "
              f"{row['rate_8h']*100:>10.4f}%")

    print("\n✓ Kraken public tickers API is accessible (no auth needed).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
