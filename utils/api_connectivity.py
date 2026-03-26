from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import requests


HYPERLIQUID_INFO_URL = "https://api.hyperliquid.xyz/info"
POLYMARKET_MARKETS_URL = "https://gamma-api.polymarket.com/markets"


@dataclass
class ConnectivityResult:
    source: str
    ok: bool
    status_code: int | None
    latency_ms: float
    error: str | None
    schema_valid: bool
    record_count: int
    endpoint: str
    payload_summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _schema_error(message: str, *, source: str, endpoint: str, status_code: int | None = None, latency_ms: float = 0.0) -> ConnectivityResult:
    return ConnectivityResult(
        source=source,
        ok=False,
        status_code=status_code,
        latency_ms=latency_ms,
        error=message,
        schema_valid=False,
        record_count=0,
        endpoint=endpoint,
        payload_summary={},
    )


def fetch_hyperliquid_meta(timeout: float = 5.0) -> tuple[ConnectivityResult, list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        response = requests.post(
            HYPERLIQUID_INFO_URL,
            json={"type": "metaAndAssetCtxs"},
            timeout=timeout,
        )
        elapsed_ms = response.elapsed.total_seconds() * 1000
        response.raise_for_status()
        payload = response.json()
    except requests.Timeout as exc:
        return _schema_error(
            f"timeout after {timeout:.1f}s: {exc}",
            source="hyperliquid",
            endpoint=HYPERLIQUID_INFO_URL,
        ), [], []
    except requests.RequestException as exc:
        status_code = getattr(exc.response, "status_code", None)
        return _schema_error(
            str(exc),
            source="hyperliquid",
            endpoint=HYPERLIQUID_INFO_URL,
            status_code=status_code,
        ), [], []
    except ValueError as exc:
        return _schema_error(
            f"invalid JSON: {exc}",
            source="hyperliquid",
            endpoint=HYPERLIQUID_INFO_URL,
        ), [], []

    if not isinstance(payload, list) or len(payload) < 2:
        return _schema_error(
            "expected [meta, assetCtxs] list payload",
            source="hyperliquid",
            endpoint=HYPERLIQUID_INFO_URL,
            status_code=response.status_code,
            latency_ms=elapsed_ms,
        ), [], []

    meta, contexts = payload[0], payload[1]
    universe = meta.get("universe") if isinstance(meta, dict) else None
    if not isinstance(universe, list) or not isinstance(contexts, list):
        return _schema_error(
            "missing universe/asset contexts lists",
            source="hyperliquid",
            endpoint=HYPERLIQUID_INFO_URL,
            status_code=response.status_code,
            latency_ms=elapsed_ms,
        ), [], []

    if len(universe) != len(contexts):
        return _schema_error(
            f"universe/context length mismatch: {len(universe)} vs {len(contexts)}",
            source="hyperliquid",
            endpoint=HYPERLIQUID_INFO_URL,
            status_code=response.status_code,
            latency_ms=elapsed_ms,
        ), [], []

    for index, asset in enumerate(universe[:10]):
        if not isinstance(asset, dict) or "name" not in asset:
            return _schema_error(
                f"asset[{index}] missing name",
                source="hyperliquid",
                endpoint=HYPERLIQUID_INFO_URL,
                status_code=response.status_code,
                latency_ms=elapsed_ms,
            ), [], []

    result = ConnectivityResult(
        source="hyperliquid",
        ok=True,
        status_code=response.status_code,
        latency_ms=elapsed_ms,
        error=None,
        schema_valid=True,
        record_count=min(len(universe), len(contexts)),
        endpoint=HYPERLIQUID_INFO_URL,
        payload_summary={
            "universe_count": len(universe),
            "contexts_count": len(contexts),
            "sample_assets": [asset.get("name") for asset in universe[:5]],
        },
    )
    return result, universe, contexts


def fetch_polymarket_markets(timeout: float = 5.0, limit: int = 100, closed: bool = False) -> tuple[ConnectivityResult, list[dict[str, Any]]]:
    try:
        response = requests.get(
            POLYMARKET_MARKETS_URL,
            params={"limit": limit, "closed": str(closed).lower()},
            timeout=timeout,
        )
        elapsed_ms = response.elapsed.total_seconds() * 1000
        response.raise_for_status()
        payload = response.json()
    except requests.Timeout as exc:
        return _schema_error(
            f"timeout after {timeout:.1f}s: {exc}",
            source="polymarket",
            endpoint=POLYMARKET_MARKETS_URL,
        ), []
    except requests.RequestException as exc:
        status_code = getattr(exc.response, "status_code", None)
        return _schema_error(
            str(exc),
            source="polymarket",
            endpoint=POLYMARKET_MARKETS_URL,
            status_code=status_code,
        ), []
    except ValueError as exc:
        return _schema_error(
            f"invalid JSON: {exc}",
            source="polymarket",
            endpoint=POLYMARKET_MARKETS_URL,
        ), []

    if not isinstance(payload, list):
        return _schema_error(
            "expected list payload",
            source="polymarket",
            endpoint=POLYMARKET_MARKETS_URL,
            status_code=response.status_code,
            latency_ms=elapsed_ms,
        ), []

    for index, market in enumerate(payload[:10]):
        if not isinstance(market, dict):
            return _schema_error(
                f"market[{index}] is not an object",
                source="polymarket",
                endpoint=POLYMARKET_MARKETS_URL,
                status_code=response.status_code,
                latency_ms=elapsed_ms,
            ), []
        if "question" not in market or "conditionId" not in market:
            return _schema_error(
                f"market[{index}] missing question or conditionId",
                source="polymarket",
                endpoint=POLYMARKET_MARKETS_URL,
                status_code=response.status_code,
                latency_ms=elapsed_ms,
            ), []

    result = ConnectivityResult(
        source="polymarket",
        ok=True,
        status_code=response.status_code,
        latency_ms=elapsed_ms,
        error=None,
        schema_valid=True,
        record_count=len(payload),
        endpoint=POLYMARKET_MARKETS_URL,
        payload_summary={
            "market_count": len(payload),
            "sample_questions": [
                market.get("question") or market.get("title") or market.get("slug")
                for market in payload[:3]
            ],
        },
    )
    return result, payload
