#!/usr/bin/env python3
"""
CLI: run the cross-exchange funding spread scanner.

Usage:
  python scripts/scan_spreads.py                  # one-shot scan
  python scripts/scan_spreads.py --continuous     # scan every 5 min, forever
  python scripts/scan_spreads.py --continuous --hours 6
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Ensure repo root on sys.path when run as script
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.collectors.spread_scanner import CrossExchangeSpreadScanner  # noqa: E402

OUTPUT_PATH = _REPO_ROOT / "data" / "spreads" / "funding_spreads.jsonl"
SCAN_INTERVAL_SECONDS = 300  # 5 minutes


def _fmt_pct(frac: float, sign: bool = True) -> str:
    """Render a fraction as a percent string: 0.00012 -> '+0.0120%'."""
    pct = frac * 100
    if sign:
        return f"{pct:+.4f}%"
    return f"{pct:.4f}%"


def _print_report(scan: dict) -> None:
    ts = scan["timestamp_utc"]
    # trim to minute for header readability
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        header_ts = dt.strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        header_ts = ts

    spreads = scan["spreads"]
    print(f"\n=== Cross-Exchange Funding Spreads ({header_ts}) ===")

    executable = [s for s in spreads if s["executable"]]
    data_only = [s for s in spreads if not s["executable"]]

    print("\n  EXECUTABLE (HL ↔ Kraken):")
    if not executable:
        print("  (no opportunities above fee threshold with volume ≥ $5M)")
    else:
        print(
            f"  {'Asset':<8}| {'HL 8h':<10}| {'Kraken 8h':<11}| "
            f"{'Spread':<9}| {'Net APY':<9}| Direction"
        )
        print("  " + "-" * 78)
        for s in executable:
            print(
                f"  {s['asset']:<8}| {_fmt_pct(s['hl_rate_8h']):<10}| "
                f"{_fmt_pct(s['other_rate_8h']):<11}| "
                f"{_fmt_pct(s['abs_spread_8h'], sign=False):<9}| "
                f"{s['net_apy_optimistic']:>6.1f}%  | {s['direction']}"
            )

    print("\n  DATA-ONLY (HL ↔ Binance/Bybit — cannot execute):")
    if not data_only:
        print("  (none)")
    else:
        print(
            f"  {'Asset':<8}| {'HL 8h':<10}| {'CEX 8h':<10}| "
            f"{'Spread':<9}| {'Net APY':<9}| {'Direction':<24}| Exchange"
        )
        print("  " + "-" * 95)
        for s in data_only:
            print(
                f"  {s['asset']:<8}| {_fmt_pct(s['hl_rate_8h']):<10}| "
                f"{_fmt_pct(s['other_rate_8h']):<10}| "
                f"{_fmt_pct(s['abs_spread_8h'], sign=False):<9}| "
                f"{s['net_apy_optimistic']:>6.1f}%  | "
                f"{s['direction']:<24}| {s['other_exchange']}"
            )

    print()


def _append_jsonl(scan: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Persist a compact record — drop the full rates payload to keep lines small
    record = {
        "timestamp_utc": scan["timestamp_utc"],
        "scan_duration_s": scan["scan_duration_s"],
        "spreads": scan["spreads"],
    }
    with path.open("a") as f:
        f.write(json.dumps(record) + "\n")


def run_once(scanner: CrossExchangeSpreadScanner) -> None:
    scan = scanner.scan_once()
    _print_report(scan)
    _append_jsonl(scan, OUTPUT_PATH)
    print(f"  [saved to {OUTPUT_PATH.relative_to(_REPO_ROOT)}]")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--continuous", action="store_true",
                        help="Scan every 5 minutes continuously")
    parser.add_argument("--hours", type=float, default=None,
                        help="Stop after N hours in continuous mode")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    scanner = CrossExchangeSpreadScanner()

    if not args.continuous:
        run_once(scanner)
        return 0

    deadline = None
    if args.hours is not None:
        deadline = time.monotonic() + args.hours * 3600

    print(f"Continuous scan every {SCAN_INTERVAL_SECONDS}s. Ctrl-C to stop.")
    try:
        while True:
            try:
                run_once(scanner)
            except Exception as e:  # keep loop alive
                logging.exception("Scan iteration failed: %s", e)

            if deadline is not None and time.monotonic() >= deadline:
                print("Deadline reached; exiting.")
                return 0

            # Sleep until next boundary, but check deadline periodically
            remaining = SCAN_INTERVAL_SECONDS
            while remaining > 0:
                step = min(remaining, 10)
                time.sleep(step)
                remaining -= step
                if deadline is not None and time.monotonic() >= deadline:
                    print("Deadline reached; exiting.")
                    return 0
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
