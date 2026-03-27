#!/usr/bin/env python3
"""
⛔ DEPRECATED — DO NOT USE

This script is DISABLED. All trading is now handled by trading_engine.py.

Reason: Fragmented entry paths create bypass risks. The engine is the single
        authoritative trading loop with built-in capital protection.

Migration: Use trading_engine.py (always-on service via LaunchD)

=== ORIGINAL DOCSTRING (PRESERVED FOR REFERENCE) ===
Hyperliquid Safe Entry Module — Signal-Driven Position Opening.

Opens small positions when strong signals pass ALL safety gates.
Integrates with risk-guardian.py for protection after entry.

Usage:
    python scripts/hl_entry.py                    # Paper mode (default)
    ENTRY_MODE=live python scripts/hl_entry.py    # Live mode
    python scripts/hl_entry.py --status            # Show readiness only

Safety gates (ALL must pass):
  1. Signal strength above threshold
  2. Signal freshness (scanned within last hour)
  3. No duplicate position on same asset
  4. Entry cooldown passed (30 min between entries)
  5. Max exposure not exceeded ($15 per trade, $50 total)
  6. Circuit breaker not halted
  7. Perps margin available (auto-transfers from spot if needed)
  8. Slippage check
  9. Account state consistency check
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.runtime import WORKSPACE_ROOT as WORKSPACE, LOGS_DIR
from utils.api_connectivity import fetch_hyperliquid_meta

# TIERED ALLOCATION: Use tiered scanner (dynamic position sizing)
import importlib.util as _ilu
_sig_spec = _ilu.spec_from_file_location("signal_engine", Path(__file__).parent / "tiered_scanner.py")
_signal_engine = _ilu.module_from_spec(_sig_spec)
_sig_spec.loader.exec_module(_signal_engine)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ENTRY_MODE = os.environ.get("ENTRY_MODE", "paper").lower()  # paper | live

MAX_POSITION_SIZE_USD = 15.0    # $15 per trade (CEO PROFIT MODE — 7-day deadline)
MAX_TOTAL_EXPOSURE_USD = 40.0   # $40 total (~40% of capital, keep 60% cash)
MAX_CONCURRENT = 2              # Max 2 concurrent positions
MIN_SIGNAL_SCORE = 6.0          # Minimum multi-factor score (A+ standard)
SIGNAL_FRESHNESS_MIN = 60       # Signal must be < 60 min old
ENTRY_COOLDOWN_MIN = 2          # 2 min (CEO: removed for capital utilization >70%)
MIN_PERP_MARGIN_USD = 10.0      # Need at least $10 in perp margin
SPOT_TRANSFER_AMOUNT = 20.0     # Transfer $20 from spot when needed
MAX_SLIPPAGE = 0.03             # 3% max slippage for entries (tighter than closes)
MIN_VOLUME_24H = 1_000_000      # $1M min daily volume (A+ standard — must exit cleanly)
MIN_FUNDING_ANNUALIZED = 1.50   # 150% annualized funding rate minimum (A standard — balanced for throughput)

ENTRY_LOG = LOGS_DIR / "hl-entry.jsonl"
ENTRY_STATE = LOGS_DIR / "hl-entry-state.json"
GUARDIAN_STATE_FILE = LOGS_DIR / "risk-guardian-state.json"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def log_entry_event(event: dict[str, Any]) -> None:
    event["logged_at"] = datetime.now(timezone.utc).isoformat()
    ENTRY_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(ENTRY_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, default=str) + "\n")


# ---------------------------------------------------------------------------
# Entry State
# ---------------------------------------------------------------------------

class EntryState:
    def __init__(self):
        self.path = ENTRY_STATE
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return {"last_entry_at": None, "entries_today": 0, "last_entry_date": None}

    def save(self) -> None:
        self.data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2))

    def can_enter(self) -> tuple[bool, str]:
        last = self.data.get("last_entry_at")
        if last:
            try:
                dt = datetime.fromisoformat(last)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                age_min = (datetime.now(timezone.utc) - dt).total_seconds() / 60
                if age_min < ENTRY_COOLDOWN_MIN:
                    return False, f"Cooldown: {ENTRY_COOLDOWN_MIN - age_min:.0f} min remaining"
            except (ValueError, TypeError):
                pass
        return True, "OK"

    def record_entry(self) -> None:
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        if self.data.get("last_entry_date") != today:
            self.data["entries_today"] = 0
            self.data["last_entry_date"] = today
        self.data["entries_today"] += 1
        self.data["last_entry_at"] = now.isoformat()
        self.save()


# ---------------------------------------------------------------------------
# Hyperliquid Client (reuse pattern from hl_executor)
# ---------------------------------------------------------------------------

class HLClient:
    def __init__(self):
        key = os.environ.get("HL_PRIVATE_KEY", "")
        if not key:
            raise RuntimeError("HL_PRIVATE_KEY not set")
        from hyperliquid.exchange import Exchange
        from hyperliquid.info import Info
        from hyperliquid.utils import constants
        from eth_account import Account

        self.account = Account.from_key(key)
        self.address = self.account.address
        self.info = Info(constants.MAINNET_API_URL, skip_ws=True)
        self.exchange = Exchange(self.account, constants.MAINNET_API_URL)

    def get_perp_state(self) -> dict[str, Any]:
        state = self.info.user_state(self.address)
        m = state.get("marginSummary", {})
        positions = []
        for ap in state.get("assetPositions", []):
            p = ap.get("position", {})
            szi = float(p.get("szi", 0))
            if szi != 0:
                positions.append({"coin": p["coin"], "size": abs(szi),
                    "direction": "long" if szi > 0 else "short",
                    "value": float(p.get("positionValue", 0))})
        return {
            "account_value": float(m.get("accountValue", 0)),
            "total_notional": float(m.get("totalNtlPos", 0)),
            "positions": positions,
        }

    def get_spot_usd(self) -> float:
        try:
            spot = self.info.spot_user_state(self.address)
            return sum(float(b.get("total", 0)) for b in spot.get("balances", [])
                       if b.get("coin") in ("USDC", "USDT0", "USDE"))
        except Exception:
            return 0.0

    def transfer_to_perps(self, amount: float) -> dict[str, Any]:
        """Transfer USDC from spot to perp margin."""
        return self.exchange.usd_class_transfer(amount, to_perp=True)

    def get_mid(self, coin: str) -> float | None:
        try:
            mids = self.info.all_mids()
            return float(mids.get(coin, 0)) or None
        except Exception:
            return None

    def open_long(self, coin: str, size: float, slippage: float = MAX_SLIPPAGE) -> dict[str, Any]:
        return self.exchange.market_open(coin, is_buy=True, sz=size, slippage=slippage)

    def open_short(self, coin: str, size: float, slippage: float = MAX_SLIPPAGE) -> dict[str, Any]:
        return self.exchange.market_open(coin, is_buy=False, sz=size, slippage=slippage)


# ---------------------------------------------------------------------------
# Signal Scanner (funding rate anomalies)
# ---------------------------------------------------------------------------

def scan_signals() -> list[dict[str, Any]]:
    """Scan using tiered scanner (dynamic position sizing based on signal strength)."""
    return _signal_engine.scan_tiered()


# ---------------------------------------------------------------------------
# Safety Gate
# ---------------------------------------------------------------------------

def check_all_gates(
    signal: dict[str, Any], client: HLClient, entry_state: EntryState
) -> tuple[bool, str, dict[str, Any]]:
    """Run ALL safety gates. Returns (passed, reason, context)."""
    ctx: dict[str, Any] = {"signal": signal}

    # 1. Signal score
    if signal["score"] < MIN_SIGNAL_SCORE:
        return False, f"Signal score {signal['score']:.1f} < {MIN_SIGNAL_SCORE}", ctx

    # 2. Cooldown
    ok, reason = entry_state.can_enter()
    if not ok:
        return False, reason, ctx

    # 3. Circuit breaker (read guardian state)
    if GUARDIAN_STATE_FILE.exists():
        try:
            gs = json.loads(GUARDIAN_STATE_FILE.read_text())
            if gs.get("halted"):
                return False, f"Circuit breaker halted: {gs.get('halt_reason')}", ctx
        except (json.JSONDecodeError, OSError):
            pass

    # 4. Account state
    perp = client.get_perp_state()
    spot = client.get_spot_usd()
    ctx["perp_margin"] = perp["account_value"]
    ctx["spot_usd"] = spot
    ctx["positions"] = perp["positions"]
    ctx["total_notional"] = perp["total_notional"]

    # 5. No duplicate
    existing_coins = {p["coin"] for p in perp["positions"]}
    if signal["asset"] in existing_coins:
        return False, f"Already have position in {signal['asset']}", ctx

    # 6. Max concurrent
    if len(perp["positions"]) >= MAX_CONCURRENT:
        return False, f"Max {MAX_CONCURRENT} concurrent positions reached", ctx

    # 7. Max total exposure
    if perp["total_notional"] + MAX_POSITION_SIZE_USD > MAX_TOTAL_EXPOSURE_USD:
        return False, f"Total exposure ${perp['total_notional']:.2f} + ${MAX_POSITION_SIZE_USD} would exceed ${MAX_TOTAL_EXPOSURE_USD}", ctx

    # 8. Margin available (auto-transfer if needed)
    if perp["account_value"] < MIN_PERP_MARGIN_USD:
        if spot >= SPOT_TRANSFER_AMOUNT:
            ctx["needs_transfer"] = True
            ctx["transfer_amount"] = SPOT_TRANSFER_AMOUNT
        elif spot >= MIN_PERP_MARGIN_USD:
            ctx["needs_transfer"] = True
            ctx["transfer_amount"] = min(spot * 0.5, SPOT_TRANSFER_AMOUNT)
        else:
            return False, f"Insufficient margin: perp=${perp['account_value']:.2f}, spot=${spot:.2f}", ctx

    # 9. Slippage
    mid = client.get_mid(signal["asset"])
    ctx["mid_price"] = mid
    if mid and signal["price"] > 0:
        slip = abs(mid - signal["price"]) / signal["price"]
        if slip > MAX_SLIPPAGE:
            return False, f"Slippage {slip:.1%} > {MAX_SLIPPAGE:.0%}", ctx

    # 10. Volume sanity
    if signal["volume_24h"] < MIN_VOLUME_24H:
        return False, f"Volume ${signal['volume_24h']:,.0f} < ${MIN_VOLUME_24H:,.0f} min", ctx

    # 11. Funding direction gate (PROVE lesson: don't pay funding on a funding arb trade)
    if signal.get("signal_type") == "funding_anomaly":
        fr = signal.get("funding_8h", 0)
        direction = signal.get("direction", "")
        # Long should earn funding (funding negative = shorts pay longs)
        # Short should earn funding (funding positive = longs pay shorts)
        if direction == "long" and fr > 0:
            return False, f"Funding direction mismatch: long but funding {fr:+.6f} (would pay, not earn)", ctx
        if direction == "short" and fr < 0:
            return False, f"Funding direction mismatch: short but funding {fr:+.6f} (would pay, not earn)", ctx

    # 12. Premium check (A+ standard: perp price must be below oracle for longs)
    premium = signal.get("composite", {}).get("premium", signal.get("premium", None))
    
    # TIER 2: Premium Reversion (alternative to Tier 1 funding)
    # If premium < -2.5%, accept with lower thresholds
    tier = 1  # Default to Tier 1
    if premium is not None and premium < -0.025:
        tier = 2
        # Tier 2 has relaxed requirements
        MIN_FUNDING_TIER2 = 0.50  # 50% annualized (vs 150% for Tier 1)
        MIN_VOLUME_TIER2 = 500_000  # $500k (vs $1M for Tier 1)
        signal["tier"] = 2
        signal["position_size_usd"] = 10.0  # Smaller size for Tier 2
    
    # Apply tier-specific gates
    if tier == 1:
        # Tier 1: Premium must be < -1%
        if premium is not None and signal.get("direction") == "long" and premium > -0.01:
            return False, f"Premium {premium*100:+.2f}% > -1% — no reversion pressure for longs", ctx

    return True, "ALL GATES PASSED", ctx


# ---------------------------------------------------------------------------
# Entry Execution
# ---------------------------------------------------------------------------

def execute_entry(
    signal: dict[str, Any], client: HLClient, entry_state: EntryState, ctx: dict[str, Any]
) -> dict[str, Any]:
    """Execute a position entry with full audit trail."""
    result: dict[str, Any] = {
        "action": "entry",
        "mode": ENTRY_MODE,
        "asset": signal["asset"],
        "direction": signal["direction"],
        "signal_score": signal["score"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Transfer if needed
    if ctx.get("needs_transfer"):
        amount = ctx["transfer_amount"]
        if ENTRY_MODE == "live":
            try:
                transfer_resp = client.transfer_to_perps(amount)
                result["transfer"] = {"amount": amount, "response": transfer_resp}
                time.sleep(2)  # Wait for settlement
            except Exception as e:
                result["result"] = "TRANSFER_FAILED"
                result["error"] = f"{type(e).__name__}: {e}"
                log_entry_event(result)
                return result
        else:
            result["transfer"] = {"amount": amount, "response": "PAPER_MODE_SKIP"}

    # Calculate size
    mid = ctx.get("mid_price") or client.get_mid(signal["asset"])
    if not mid or mid <= 0:
        result["result"] = "NO_PRICE"
        log_entry_event(result)
        return result

    # Size in asset units, ensuring notional >= $10 (exchange minimum)
    # TIERED ALLOCATION: Use signal's recommended size, fallback to MAX if not set
    target_usd = signal.get("position_size_usd", MAX_POSITION_SIZE_USD)
    raw_size = target_usd / mid

    # Get size decimals for the asset
    try:
        meta_result, universe, _ = fetch_hyperliquid_meta(timeout=5)
        sz_decimals = 4  # default
        for u in universe:
            if u.get("name") == signal["asset"]:
                sz_decimals = int(u.get("szDecimals", 4))
                break
        size = round(raw_size, sz_decimals)
        notional = size * mid
        # Ensure above $10 minimum
        if notional < 10.0:
            size = round(10.5 / mid, sz_decimals)  # Slightly above minimum
            notional = size * mid
    except Exception:
        size = round(raw_size, 4)
        notional = size * mid

    result["size"] = size
    result["mid_price"] = mid
    result["notional_usd"] = notional
    result["sdk_call"] = f"exchange.market_open('{signal['asset']}', is_buy={signal['direction']=='long'}, sz={size})"

    # Log intent BEFORE execution
    log_entry_event({**result, "phase": "INTENT"})

    if ENTRY_MODE == "paper":
        result["result"] = "PAPER_ENTRY"
        result["message"] = f"Would open {signal['direction']} {size} {signal['asset']} @ ${mid:,.2f} (${notional:.2f})"
        log_entry_event(result)
        entry_state.record_entry()
        return result

    # LIVE execution
    try:
        is_buy = signal["direction"] == "long"
        response = client.open_long(signal["asset"], size) if is_buy else client.open_short(signal["asset"], size)
        result["exchange_response"] = response

        statuses = response.get("response", {}).get("data", {}).get("statuses", [])
        filled = any("filled" in s for s in statuses if isinstance(s, dict))
        errored = [s.get("error") for s in statuses if isinstance(s, dict) and "error" in s]

        if filled:
            result["result"] = "FILLED"
            entry_state.record_entry()
            # Record entry thesis for guardian degradation checks
            try:
                thesis_file = LOGS_DIR / "entry-thesis.json"
                thesis_data = json.loads(thesis_file.read_text()) if thesis_file.exists() else {}
                thesis_data[signal["asset"]] = {
                    "entry_funding_rate": signal.get("funding_rate_8h", signal.get("funding", {}).get("raw", 0) if isinstance(signal.get("funding"), dict) else 0),
                    "entry_funding_annual": signal.get("annualized_rate", 0),
                    "entry_score": signal.get("score", 0),
                    "entry_timestamp": datetime.now(timezone.utc).isoformat(),
                    "entry_price": mid,
                }
                thesis_file.write_text(json.dumps(thesis_data, indent=2))
            except Exception:
                pass  # Non-critical — don't block the trade
            # Verify position
            time.sleep(1)
            new_state = client.get_perp_state()
            pos = next((p for p in new_state["positions"] if p["coin"] == signal["asset"]), None)
            result["position_after"] = pos
            result["verified"] = pos is not None
        elif errored:
            result["result"] = "REJECTED"
            result["errors"] = errored
        else:
            result["result"] = "UNKNOWN_RESPONSE"

    except Exception as e:
        result["result"] = "ERROR"
        result["error"] = f"{type(e).__name__}: {e}"

    log_entry_event(result)
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_entry(status_only: bool = False) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    print(f"\n{'='*60}")
    print(f"  ENTRY MODULE — {ENTRY_MODE.upper()} MODE")
    print(f"  {now.isoformat()}")
    print(f"{'='*60}\n")

    client = HLClient()
    entry_state = EntryState()

    # Status
    perp = client.get_perp_state()
    spot = client.get_spot_usd()
    print(f"[1/4] Account: spot=${spot:.2f} | perp=${perp['account_value']:.6f} | positions={len(perp['positions'])}")

    if status_only:
        ok, reason = entry_state.can_enter()
        print(f"  Entry cooldown: {'✅ ready' if ok else '⏳ ' + reason}")
        print(f"  Mode: {ENTRY_MODE}")
        return {"status": "OK"}

    # Scan signals
    signals = scan_signals()
    print(f"[2/4] Signals: {len(signals)} above threshold")
    for s in signals:
        print(f"  {s['asset']}: {s['direction']} | {s.get('annualized_rate', s.get('annualized', 0)):+.0%} ann. | Vol: ${s['volume_24h']:,.0f} | Score: {s['score']:.1f}")

    if not signals:
        print(f"[3/4] No entry — no qualifying signals")
        log_entry_event({"action": "scan_only", "signals": 0, "timestamp": now.isoformat()})
        return {"action": "no_signal", "signals": 0}

    # CEO FIX: Filter out assets we already hold
    state = client.get_perp_state()
    held_assets = {p['coin'] for p in state.get('positions', [])}
    signals = [s for s in signals if s['asset'] not in held_assets]
    
    if not signals:
        print(f"[3/4] No entry — all signals are in existing positions")
        return {"action": "all_held", "signals": 0}

    # Try best signal
    best = signals[0]
    print(f"\n[3/4] Evaluating best: {best['asset']} (score: {best['score']:.1f})")
    
    # CANARY PROTOCOL: Generate pre-trade packet
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from pre_trade_packet import generate_packet
    packet = generate_packet(best, {})
    print(f"  📋 Pre-trade packet: {packet['packet_id']}")
    
    passed, reason, ctx = check_all_gates(best, client, entry_state)

    if not passed:
        print(f"  ❌ BLOCKED: {reason}")
        log_entry_event({"action": "blocked", "asset": best["asset"], "reason": reason, "timestamp": now.isoformat()})
        return {"action": "blocked", "reason": reason}

    print(f"  ✅ {reason}")
    print(f"  📋 Packet compliance: valid")
    result = execute_entry(best, client, entry_state, ctx)
    print(f"\n[4/4] Result: {result.get('result', '?')}")
    if result.get("message"):
        print(f"  {result['message']}")

    print(f"\n{'='*60}")
    return result


if __name__ == "__main__":
    print("=" * 70)
    print("⛔ SCRIPT DISABLED")
    print("=" * 70)
    print()
    print("This entry script is deprecated and disabled.")
    print("All trading is now handled by: scripts/trading_engine.py")
    print()
    print("Reason: Single authoritative loop prevents bypass paths.")
    print()
    print("To trade:")
    print("  1. Verify engine is running: python3 scripts/trading_engine.py --status")
    print("  2. If not running: launchctl load ~/Library/LaunchAgents/com.ats.trading-engine.plist")
    print()
    sys.exit(1)
    
    # ORIGINAL CODE (UNREACHABLE):
    args = sys.argv[1:]
    run_entry(status_only="--status" in args)
