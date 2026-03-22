from __future__ import annotations

import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SUPPORT_SITECUSTOMIZE = REPO_ROOT / "tests" / "support" / "offline_requests_sitecustomize.py"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def append_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'a') as handle:
        for record in records:
            handle.write(json.dumps(record) + '\n')


def default_hyperliquid_fixture(*, opportunity: bool, mid_price: float = 50_000.0) -> dict[str, Any]:
    funding = -0.0005 if opportunity else 0.0
    volume = 2_000_000.0 if opportunity else 100_000.0
    return {
        "universe_size": 100,
        "signal_asset": "BTC",
        "entry_price": 50_000.0,
        "funding": funding,
        "dayNtlVlm": volume,
        "openInterest": 20.0,
        "all_mids": {"BTC": mid_price},
        "l2_books": {"BTC": {"bid": 49_990.0, "ask": 50_010.0}},
    }


def _polymarket_market(
    market_id: str,
    question: str,
    *,
    yes_ask: float,
    yes_bid: float,
    yes_price: float | None = None,
    no_ask: float = 0.58,
    no_bid: float = 0.57,
    no_price: float | None = None,
    liquidity: float = 20_000.0,
) -> dict[str, Any]:
    return {
        "conditionId": market_id,
        "question": question,
        "liquidity": liquidity,
        "tokens": [
            {
                "token_id": f"{market_id}-YES",
                "outcome": "YES",
                "bestBid": yes_bid,
                "bestAsk": yes_ask,
                "price": yes_price if yes_price is not None else yes_ask,
            },
            {
                "token_id": f"{market_id}-NO",
                "outcome": "NO",
                "bestBid": no_bid,
                "bestAsk": no_ask,
                "price": no_price if no_price is not None else no_ask,
            },
        ],
    }


def default_polymarket_fixture(*, opportunity: bool, yes_price: float = 0.42) -> dict[str, Any]:
    primary_liquidity = 25_000.0 if opportunity else 500.0
    primary_yes_ask = 0.42 if opportunity else 0.62
    primary_yes_bid = 0.41 if opportunity else 0.61
    return {
        "markets": [
            _polymarket_market(
                "pm-btc-up",
                "Will BTC close above 60k?",
                yes_ask=primary_yes_ask,
                yes_bid=primary_yes_bid,
                yes_price=yes_price,
                liquidity=primary_liquidity,
            ),
            _polymarket_market(
                "pm-eth-up",
                "Will ETH close above 4k?",
                yes_ask=0.61,
                yes_bid=0.60,
                yes_price=0.61,
                liquidity=500.0,
            ),
            _polymarket_market(
                "pm-sol-up",
                "Will SOL close above 250?",
                yes_ask=0.59,
                yes_bid=0.58,
                yes_price=0.59,
                liquidity=500.0,
            ),
        ]
    }


def write_fixture(
    path: Path,
    *,
    hyperliquid: dict[str, Any] | None = None,
    polymarket: dict[str, Any] | None = None,
) -> None:
    payload = {
        "hyperliquid": deepcopy(hyperliquid if hyperliquid is not None else default_hyperliquid_fixture(opportunity=False)),
        "polymarket": deepcopy(polymarket if polymarket is not None else default_polymarket_fixture(opportunity=False)),
    }
    write_json(path, payload)


def prepare_patch_dir(workspace_root: Path) -> Path:
    patch_dir = workspace_root / "patches"
    patch_dir.mkdir(parents=True, exist_ok=True)
    (patch_dir / "sitecustomize.py").write_text(SUPPORT_SITECUSTOMIZE.read_text())
    return patch_dir


def build_env(workspace_root: Path, fixture_path: Path, mode: str, patch_dir: Path | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["OPENCLAW_WORKSPACE"] = str(workspace_root)
    env["OPENCLAW_TRADING_MODE"] = mode
    env["OPENCLAW_OFFLINE_FIXTURE"] = str(fixture_path)
    patch_dir = patch_dir or prepare_patch_dir(workspace_root)
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(patch_dir) if not existing_pythonpath else f"{patch_dir}:{existing_pythonpath}"
    return env


def run_agency_cycle(workspace_root: Path, fixture_path: Path, mode: str) -> subprocess.CompletedProcess[str]:
    patch_dir = prepare_patch_dir(workspace_root)
    return subprocess.run(
        ["python3", "scripts/trading-agency-phase1.py"],
        cwd=REPO_ROOT,
        env=build_env(workspace_root, fixture_path, mode, patch_dir),
        capture_output=True,
        text=True,
        timeout=120,
    )
