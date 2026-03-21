#!/usr/bin/env python3
"""Bootstrap/runtime dependency verification for canonical paper-trading flows."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.runtime import TRADING_MODE, mode_includes_hyperliquid, mode_includes_polymarket

BASE_DEPENDENCIES = ["requests"]
OPTIONAL_DEPENDENCIES = {
    "analytics": ["numpy", "psutil"],
}


def check_dependency(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def main() -> int:
    print("=" * 80)
    print("OPENCLAW BOOTSTRAP CHECK")
    print("=" * 80)
    print(f"Trading mode: {TRADING_MODE}")
    print(f"Hyperliquid enabled: {mode_includes_hyperliquid()}")
    print(f"Polymarket enabled: {mode_includes_polymarket()}")
    print()

    missing = [module_name for module_name in BASE_DEPENDENCIES if not check_dependency(module_name)]

    if missing:
        print("[FAIL] Missing required runtime dependencies:")
        for module_name in missing:
            print(f"  - {module_name}")
        print()
        print("Install them with:")
        print("  python3 -m venv .venv")
        print("  source .venv/bin/activate")
        print("  pip install -r requirements.txt")
        return 1

    print("[OK] Required runtime dependencies present")

    missing_optional = [
        module_name
        for group in OPTIONAL_DEPENDENCIES.values()
        for module_name in group
        if not check_dependency(module_name)
    ]
    if missing_optional:
        print("[WARN] Optional analytics/monitoring dependencies missing:")
        for module_name in missing_optional:
            print(f"  - {module_name}")
        print("       These affect supporting analytics scripts, not the core paper-trading bootstrap.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
