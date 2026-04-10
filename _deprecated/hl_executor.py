#!/usr/bin/env python3
"""
⛔ DEPRECATED — DO NOT USE

This script is DISABLED. All trading is now handled by trading_engine.py.

Reason: Fragmented exit paths create state inconsistency. The engine is the
        single authoritative loop that manages all position lifecycle.

Migration: Use trading_engine.py (handles both entries and exits)

=== ORIGINAL DOCSTRING (PRESERVED FOR REFERENCE) ===
Hyperliquid Safe Execution Module — CLOSE/REDUCE ONLY.

This module can ONLY close or reduce existing positions.
It CANNOT open new positions or increase exposure.

Safety features:
  - Circuit breaker (loss count, daily loss, drawdown)
  - Slippage check before execution
  - Duplicate order prevention
  - Max position size validation
  - Kill switch (emergency close all)
  - Full audit logging

Usage:
    python scripts/hl_executor.py status          # Show positions + risk state
    python scripts/hl_executor.py close ETH       # Close ETH position
    python scripts/hl_executor.py reduce ETH 0.001 # Reduce ETH by 0.001
    python scripts/hl_executor.py killswitch       # Emergency close ALL
    python scripts/hl_executor.py --dry-run close ETH  # Simulate without executing
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.runtime import WORKSPACE_ROOT as WORKSPACE, LOGS_DIR

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXECUTION_LOG = LOGS_DIR / "hl-execution.jsonl"
CIRCUIT_BREAKER_STATE = LOGS_DIR / "circuit-breaker-state.json"

MAX_SLIPPAGE = 0.03        # 3% max slippage from mid price
MAX_LOSSES_BEFORE_HALT = 3
MAX_DAILY_LOSS_USD = 3.0
MAX_DRAWDOWN_PCT = 0.15    # 15% drawdown from peak (CANARY_PROTOCOL)

BANNER = "⚠️ HYPERLIQUID EXECUTOR — CLOSE/REDUCE ONLY — NO NEW POSITIONS"


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def log_execution(event: dict[str, Any]) -> None:
    """Append execution event to JSONL log."""
    event["logged_at"] = datetime.now(timezone.utc).isoformat()
    EXECUTION_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(EXECUTION_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")
    print(f"  [LOG] {event.get('action', '?')}: {event.get('coin', '?')} — {event.get('result', '?')}")


# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------

class CircuitBreaker:
    """Tracks losses and halts execution when thresholds are breached."""

    def __init__(self):
        self.state = self._load()

    def _load(self) -> dict[str, Any]:
        if CIRCUIT_BREAKER_STATE.exists():
            try:
                return json.loads(CIRCUIT_BREAKER_STATE.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return {
            "peak_value": 0.0,
            "daily_losses": [],
            "consecutive_losses": 0,
            "halted": False,
            "halt_reason": None,
            "updated_at": None,
        }

    def _save(self) -> None:
        self.state["updated_at"] = datetime.now(timezone.utc).isoformat()
        CIRCUIT_BREAKER_STATE.parent.mkdir(parents=True, exist_ok=True)
        CIRCUIT_BREAKER_STATE.write_text(json.dumps(self.state, indent=2))

    def update_peak(self, account_value: float) -> None:
        if account_value > self.state["peak_value"]:
            self.state["peak_value"] = account_value
            self._save()

    def record_loss(self, amount_usd: float) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.state["daily_losses"].append({"date": today, "amount": amount_usd})
        self.state["consecutive_losses"] += 1
        # Prune old entries
        cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        self.state["daily_losses"] = [
            l for l in self.state["daily_losses"] if l["date"] >= cutoff
        ]
        self._save()

    def record_win(self) -> None:
        self.state["consecutive_losses"] = 0
        self._save()

    def check(self, account_value: float) -> tuple[bool, str]:
        """Returns (allowed, reason). allowed=True means execution is safe."""
        if self.state["halted"]:
            return False, f"HALTED: {self.state['halt_reason']}"

        # Consecutive losses
        if self.state["consecutive_losses"] >= MAX_LOSSES_BEFORE_HALT:
            self.state["halted"] = True
            self.state["halt_reason"] = f"{self.state['consecutive_losses']} consecutive losses"
            self._save()
            return False, f"CIRCUIT BREAKER: {self.state['consecutive_losses']} consecutive losses"

        # Daily loss
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        daily_total = sum(l["amount"] for l in self.state["daily_losses"] if l["date"] == today)
        if daily_total >= MAX_DAILY_LOSS_USD:
            self.state["halted"] = True
            self.state["halt_reason"] = f"Daily loss ${daily_total:.2f} >= ${MAX_DAILY_LOSS_USD:.2f}"
            self._save()
            return False, f"CIRCUIT BREAKER: Daily loss ${daily_total:.2f} >= max ${MAX_DAILY_LOSS_USD:.2f}"

        # Drawdown
        if self.state["peak_value"] > 0:
            drawdown = (self.state["peak_value"] - account_value) / self.state["peak_value"]
            if drawdown >= MAX_DRAWDOWN_PCT:
                self.state["halted"] = True
                self.state["halt_reason"] = f"Drawdown {drawdown:.1%} >= {MAX_DRAWDOWN_PCT:.0%}"
                self._save()
                return False, f"CIRCUIT BREAKER: Drawdown {drawdown:.1%} from peak ${self.state['peak_value']:.4f}"

        return True, "OK"

    def reset(self) -> None:
        """Manual reset of circuit breaker — requires explicit operator action."""
        self.state["halted"] = False
        self.state["halt_reason"] = None
        self.state["consecutive_losses"] = 0
        self.state["daily_losses"] = []
        self._save()


# ---------------------------------------------------------------------------
# Hyperliquid Client
# ---------------------------------------------------------------------------

class HyperliquidExecutor:
    """Safe execution client — CLOSE/REDUCE only."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.circuit_breaker = CircuitBreaker()

        key = os.environ.get("HL_PRIVATE_KEY", "")
        if not key:
            raise RuntimeError("HL_PRIVATE_KEY not set — cannot initialize executor")

        from hyperliquid.exchange import Exchange
        from hyperliquid.info import Info
        from hyperliquid.utils import constants
        from eth_account import Account

        self.account = Account.from_key(key)
        self.address = self.account.address
        self.info = Info(constants.MAINNET_API_URL, skip_ws=True)
        self.exchange = Exchange(self.account, constants.MAINNET_API_URL)

        # Track recent order IDs for duplicate prevention
        self._recent_orders: list[str] = []

    def get_account_state(self) -> dict[str, Any]:
        state = self.info.user_state(self.address)
        margin = state.get("marginSummary", {})
        return {
            "address": self.address,
            "account_value": float(margin.get("accountValue", 0)),
            "total_notional": float(margin.get("totalNtlPos", 0)),
            "withdrawable": float(state.get("withdrawable", 0)),
        }

    def get_positions(self) -> list[dict[str, Any]]:
        state = self.info.user_state(self.address)
        positions = []
        for ap in state.get("assetPositions", []):
            p = ap.get("position", {})
            szi = float(p.get("szi", 0))
            if szi == 0:
                continue
            positions.append({
                "coin": p["coin"],
                "direction": "long" if szi > 0 else "short",
                "size": abs(szi),
                "entry_price": float(p.get("entryPx", 0)),
                "position_value": float(p.get("positionValue", 0)),
                "unrealized_pnl": float(p.get("unrealizedPnl", 0)),
                "roe": float(p.get("returnOnEquity", 0)),
                "leverage": p.get("leverage", {}).get("value", 1),
                "margin_used": float(p.get("marginUsed", 0)),
            })
        return positions

    def get_mid_price(self, coin: str) -> float | None:
        """Fetch current mid price for a coin."""
        try:
            all_mids = self.info.all_mids()
            return float(all_mids.get(coin, 0)) or None
        except Exception:
            return None

    def _check_slippage(self, coin: str, expected_price: float | None) -> tuple[bool, str, float | None]:
        """Check if current price is within acceptable slippage of expected."""
        mid = self.get_mid_price(coin)
        if mid is None:
            return False, f"Cannot fetch mid price for {coin}", None
        if expected_price and expected_price > 0:
            slip = abs(mid - expected_price) / expected_price
            if slip > MAX_SLIPPAGE:
                return False, f"Slippage {slip:.1%} > max {MAX_SLIPPAGE:.0%} (mid=${mid:.2f}, expected=${expected_price:.2f})", mid
        return True, "OK", mid

    def _check_duplicate(self, coin: str, action: str) -> tuple[bool, str]:
        """Prevent duplicate orders within 60 seconds."""
        order_key = f"{coin}:{action}:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M')}"
        if order_key in self._recent_orders:
            return False, f"Duplicate order detected: {order_key}"
        self._recent_orders.append(order_key)
        # Keep only last 20
        self._recent_orders = self._recent_orders[-20:]
        return True, "OK"

    def close_position(self, coin: str, slippage: float = 0.05) -> dict[str, Any]:
        """Close entire position for a coin. CLOSE ONLY — no opening."""
        result: dict[str, Any] = {
            "action": "close_position", "coin": coin, "dry_run": self.dry_run,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # 1. Get current position
        positions = self.get_positions()
        pos = next((p for p in positions if p["coin"] == coin), None)
        if not pos:
            result["result"] = "NO_POSITION"
            result["message"] = f"No open position for {coin}"
            log_execution(result)
            return result

        result["position_before"] = pos

        # 2. Circuit breaker check
        acct = self.get_account_state()
        self.circuit_breaker.update_peak(acct["account_value"])
        allowed, reason = self.circuit_breaker.check(acct["account_value"])
        if not allowed:
            result["result"] = "BLOCKED_CIRCUIT_BREAKER"
            result["message"] = reason
            log_execution(result)
            return result

        # 3. Slippage check
        ok, msg, mid = self._check_slippage(coin, pos["entry_price"])
        result["mid_price"] = mid
        if not ok:
            result["result"] = "BLOCKED_SLIPPAGE"
            result["message"] = msg
            log_execution(result)
            return result

        # 4. Duplicate check
        ok, msg = self._check_duplicate(coin, "close")
        if not ok:
            result["result"] = "BLOCKED_DUPLICATE"
            result["message"] = msg
            log_execution(result)
            return result

        # 5. Execute or dry-run
        if self.dry_run:
            result["result"] = "DRY_RUN"
            result["message"] = f"Would close {pos['size']} {coin} {pos['direction']} @ mid=${mid}"
            result["sdk_call"] = f"exchange.market_close(coin='{coin}', slippage={slippage})"
            log_execution(result)
            return result

        try:
            response = self.exchange.market_close(coin=coin, slippage=slippage)
            result["result"] = "EXECUTED"
            result["exchange_response"] = response
            result["sdk_call"] = f"exchange.market_close(coin='{coin}', slippage={slippage})"

            # Record P&L for circuit breaker
            pnl = pos["unrealized_pnl"]
            if pnl < 0:
                self.circuit_breaker.record_loss(abs(pnl))
            else:
                self.circuit_breaker.record_win()

            # Verify position closed
            time.sleep(1)
            new_positions = self.get_positions()
            still_open = any(p["coin"] == coin for p in new_positions)
            result["position_after_closed"] = not still_open
            result["positions_remaining"] = len(new_positions)

        except Exception as e:
            result["result"] = "ERROR"
            result["message"] = f"{type(e).__name__}: {e}"

        log_execution(result)
        return result

    def reduce_position(self, coin: str, reduce_size: float, slippage: float = 0.05) -> dict[str, Any]:
        """Reduce position size. REDUCE ONLY — cannot increase."""
        result: dict[str, Any] = {
            "action": "reduce_position", "coin": coin, "reduce_size": reduce_size,
            "dry_run": self.dry_run, "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        positions = self.get_positions()
        pos = next((p for p in positions if p["coin"] == coin), None)
        if not pos:
            result["result"] = "NO_POSITION"
            log_execution(result)
            return result

        if reduce_size >= pos["size"]:
            result["message"] = f"Reduce size {reduce_size} >= position {pos['size']}, will close entirely"
            return self.close_position(coin, slippage)

        result["position_before"] = pos

        # Safety checks
        acct = self.get_account_state()
        self.circuit_breaker.update_peak(acct["account_value"])
        allowed, reason = self.circuit_breaker.check(acct["account_value"])
        if not allowed:
            result["result"] = "BLOCKED_CIRCUIT_BREAKER"
            result["message"] = reason
            log_execution(result)
            return result

        ok, msg, mid = self._check_slippage(coin, pos["entry_price"])
        result["mid_price"] = mid
        if not ok:
            result["result"] = "BLOCKED_SLIPPAGE"
            result["message"] = msg
            log_execution(result)
            return result

        ok, msg = self._check_duplicate(coin, f"reduce_{reduce_size}")
        if not ok:
            result["result"] = "BLOCKED_DUPLICATE"
            result["message"] = msg
            log_execution(result)
            return result

        if self.dry_run:
            is_buy = pos["direction"] == "short"  # Buy to close short, sell to close long
            result["result"] = "DRY_RUN"
            result["message"] = f"Would reduce {coin} by {reduce_size} (remaining: {pos['size'] - reduce_size:.6f})"
            result["sdk_call"] = f"exchange.market_open('{coin}', is_buy={is_buy}, sz={reduce_size}, slippage={slippage})"
            log_execution(result)
            return result

        try:
            is_buy = pos["direction"] == "short"
            response = self.exchange.market_open(coin, is_buy=is_buy, sz=reduce_size, slippage=slippage)
            result["result"] = "EXECUTED"
            result["exchange_response"] = response
            result["sdk_call"] = f"exchange.market_open('{coin}', is_buy={is_buy}, sz={reduce_size})"
            log_execution(result)
        except Exception as e:
            result["result"] = "ERROR"
            result["message"] = f"{type(e).__name__}: {e}"
            log_execution(result)

        return result

    def killswitch(self) -> list[dict[str, Any]]:
        """EMERGENCY: Close ALL positions immediately."""
        print(f"\n🚨 KILL SWITCH ACTIVATED — closing all positions")
        results = []
        positions = self.get_positions()
        if not positions:
            print("  No positions to close.")
            return [{"action": "killswitch", "result": "NO_POSITIONS"}]

        for pos in positions:
            print(f"  Closing {pos['coin']} {pos['direction']} {pos['size']}...")
            r = self.close_position(pos["coin"], slippage=0.10)  # Higher slippage for emergency
            results.append(r)
        return results

    def status(self) -> dict[str, Any]:
        """Full status report."""
        acct = self.get_account_state()
        positions = self.get_positions()
        cb = self.circuit_breaker
        cb.update_peak(acct["account_value"])
        allowed, reason = cb.check(acct["account_value"])

        return {
            "account": acct,
            "positions": positions,
            "circuit_breaker": {
                "allowed": allowed,
                "reason": reason,
                "halted": cb.state["halted"],
                "consecutive_losses": cb.state["consecutive_losses"],
                "peak_value": cb.state["peak_value"],
            },
            "execution_mode": "DRY_RUN" if self.dry_run else "LIVE",
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]

    if not args:
        args = ["status"]

    command = args[0]

    print(f"\n{'='*60}")
    print(f"  {BANNER}")
    print(f"  Mode: {'DRY RUN' if dry_run else '🔴 LIVE'}")
    print(f"{'='*60}\n")

    executor = HyperliquidExecutor(dry_run=dry_run)

    if command == "status":
        s = executor.status()
        print(f"Address: {s['account']['address']}")
        print(f"Account Value: ${s['account']['account_value']:.6f}")
        print(f"Notional: ${s['account']['total_notional']:.4f}")
        print(f"Circuit Breaker: {'🟢 OK' if s['circuit_breaker']['allowed'] else '🔴 ' + s['circuit_breaker']['reason']}")
        print(f"\nPositions ({len(s['positions'])}):")
        for p in s["positions"]:
            print(f"  {p['coin']} {p['direction']} {p['size']} @ ${p['entry_price']:,.2f} | PnL: ${p['unrealized_pnl']:+.4f} ({p['roe']:+.1%}) | {p['leverage']}x")

    elif command == "close" and len(args) >= 2:
        result = executor.close_position(args[1])
        print(f"\nResult: {json.dumps(result, indent=2, default=str)}")

    elif command == "reduce" and len(args) >= 3:
        result = executor.reduce_position(args[1], float(args[2]))
        print(f"\nResult: {json.dumps(result, indent=2, default=str)}")

    elif command == "killswitch":
        results = executor.killswitch()
        for r in results:
            print(f"\n{json.dumps(r, indent=2, default=str)}")

    else:
        print("Usage: hl_executor.py [--dry-run] <status|close COIN|reduce COIN SIZE|killswitch>")


if __name__ == "__main__":
    print("=" * 70)
    print("⛔ SCRIPT DISABLED")
    print("=" * 70)
    print()
    print("This executor script is deprecated and disabled.")
    print("All trading (entry + exit) is now handled by: scripts/trading_engine.py")
    print()
    print("Reason: Single authoritative loop prevents state inconsistency.")
    print()
    print("For manual exit (emergency only):")
    print("  python3 scripts/manual_exit.py <COIN>  # Force-close position")
    print()
    print("For status:")
    print("  python3 scripts/trading_engine.py --status")
    print()
    sys.exit(1)
    
    # ORIGINAL CODE (UNREACHABLE):
    main()
