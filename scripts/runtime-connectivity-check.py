#!/usr/bin/env python3
"""Safe paper-trading runtime connectivity check for external market-data APIs."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.runtime import LOGS_DIR, TRADING_MODE
from utils.api_connectivity import fetch_hyperliquid_meta
from utils.runtime_logging import append_runtime_event

OUTPUT_FILE = LOGS_DIR / "runtime-connectivity-check.json"


def main() -> int:
    print("=" * 80)
    print("RUNTIME CONNECTIVITY CHECK")
    print("=" * 80)
    print(f"Trading mode: {TRADING_MODE}")
    print("Paper trading only: True")
    print()

    checks: list[dict] = []

    result, _, _ = fetch_hyperliquid_meta(timeout=10)
    checks.append(result.to_dict())
    print(
        f"[Hyperliquid] ok={result.ok} status_code={result.status_code} "
        f"latency_ms={result.latency_ms:.1f} record_count={result.record_count}"
    )
    if result.error:
        print(f"  error={result.error}")

    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": TRADING_MODE,
        "paper_only": True,
        "checks": checks,
        "all_passed": all(check["ok"] for check in checks) if checks else True,
    }
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w") as handle:
        json.dump(payload, handle, indent=2)

    append_runtime_event(
        stage="connectivity_check",
        exchange="system",
        lifecycle_stage="verification",
        status="INFO" if payload["all_passed"] else "ERROR",
        message="Runtime connectivity check completed",
        metadata=payload,
    )
    return 0 if payload["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
