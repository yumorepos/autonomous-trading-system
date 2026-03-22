"""Offline request patch for subprocess-driven integration tests.

Copy or expose this module as ``sitecustomize.py`` via ``PYTHONPATH`` and set
``OPENCLAW_OFFLINE_FIXTURE`` to a JSON file describing deterministic exchange
responses. The canonical runtime can then execute without live network access.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any


@dataclass
class _FakeResponse:
    payload: Any
    status_code: int = 200
    elapsed_seconds: float = 0.01

    def __post_init__(self) -> None:
        self.elapsed = SimpleNamespace(total_seconds=lambda: self.elapsed_seconds)

    def json(self) -> Any:
        return self.payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _load_fixture() -> dict[str, Any]:
    fixture_path = os.getenv("OPENCLAW_OFFLINE_FIXTURE")
    if not fixture_path:
        return {}
    return json.loads(Path(fixture_path).read_text())


def _hyperliquid_meta_payload(config: dict[str, Any]) -> list[Any]:
    universe_size = int(config.get("universe_size", 100))
    signal_asset = str(config.get("signal_asset", "BTC"))
    signal_price = float(config.get("entry_price", 50_000.0))
    signal_funding = float(config.get("funding", -0.0005))
    signal_volume = float(config.get("dayNtlVlm", 2_000_000.0))
    signal_open_interest = float(config.get("openInterest", 20.0))

    universe = [{"name": signal_asset}]
    contexts = [{
        "coin": signal_asset,
        "funding": signal_funding,
        "markPx": str(signal_price),
        "dayNtlVlm": str(signal_volume),
        "openInterest": str(signal_open_interest),
    }]

    for index in range(max(0, universe_size - 1)):
        asset = f"ALT{index:03d}"
        universe.append({"name": asset})
        contexts.append({
            "coin": asset,
            "funding": "0.00001",
            "markPx": "10",
            "dayNtlVlm": "1000",
            "openInterest": "5",
        })

    return [{"universe": universe}, contexts]


def _hyperliquid_all_mids(config: dict[str, Any]) -> dict[str, str]:
    mids = {str(asset): str(price) for asset, price in (config.get("all_mids") or {}).items()}
    if mids:
        return mids
    return {str(config.get("signal_asset", "BTC")): str(config.get("entry_price", 50_000.0))}


def _hyperliquid_l2_book(config: dict[str, Any], asset: str) -> dict[str, Any]:
    books = config.get("l2_books") or {}
    book = books.get(asset) or books.get(str(asset)) or {
        "bid": float(config.get("entry_price", 50_000.0)) - 10.0,
        "ask": float(config.get("entry_price", 50_000.0)) + 10.0,
    }
    return {
        "levels": [
            [{"px": str(book["bid"])}],
            [{"px": str(book["ask"])}],
        ]
    }


def _patch_requests() -> None:
    fixture = _load_fixture()
    if not fixture:
        return

    import requests

    def fake_post(url: str, json: dict[str, Any] | None = None, timeout: float = 0, **_: Any) -> _FakeResponse:
        hyperliquid = fixture.get("hyperliquid") or {}
        request_type = (json or {}).get("type")
        if "hyperliquid.xyz/info" in url and request_type == "metaAndAssetCtxs":
            return _FakeResponse(_hyperliquid_meta_payload(hyperliquid))
        if "hyperliquid.xyz/info" in url and request_type == "allMids":
            return _FakeResponse(_hyperliquid_all_mids(hyperliquid))
        if "hyperliquid.xyz/info" in url and request_type == "l2Book":
            return _FakeResponse(_hyperliquid_l2_book(hyperliquid, (json or {}).get("coin", "")))
        raise RuntimeError(f"offline fixture missing POST handler for {url} with payload {(json or {})}")

    def fake_get(url: str, params: dict[str, Any] | None = None, timeout: float = 0, **_: Any) -> _FakeResponse:
        if "gamma-api.polymarket.com/markets" in url:
            polymarket = fixture.get("polymarket") or {}
            condition_id = (params or {}).get("condition_id")
            markets = polymarket.get("markets") or []
            if condition_id:
                markets = [
                    market
                    for market in markets
                    if str(market.get("conditionId") or market.get("condition_id") or market.get("id")) == str(condition_id)
                ]
            return _FakeResponse(markets)
        raise RuntimeError(f"offline fixture missing GET handler for {url} with params {(params or {})}")

    requests.post = fake_post
    requests.get = fake_get
    requests.Timeout = RuntimeError
    requests.RequestException = RuntimeError


_patch_requests()
