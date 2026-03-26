#!/usr/bin/env python3
"""
Risk Guardian — Autonomous Position Protection for Hyperliquid.

CLOSES positions automatically when risk thresholds are breached.
CANNOT open new positions. CANNOT increase exposure. Protection only.

Designed to run via cron or manual invocation. Idempotent — safe to rerun.

Usage:
    python scripts/risk-guardian.py              # Run once (cron-safe)
    python scripts/risk-guardian.py --dry-run    # Simulate without executing
    python scripts/risk-guardian.py --status     # Show current state only
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

# ---------------------------------------------------------------------------
# Risk Parameters
# ---------------------------------------------------------------------------

STOP_LOSS_ROE = -0.15           # -15% ROE
TIMEOUT_HOURS = 24              # 24h max hold
DRAWDOWN_PCT = 0.20             # 20% from peak account value
MAX_CONCURRENT = 5              # Max open positions
MAX_EXPOSURE_PER_TRADE = 20.0   # $20 per trade
MAX_SLIPPAGE = 0.05             # 5% max slippage
EXECUTION_COOLDOWN_SEC = 120    # 2 min between same-coin executions
CIRCUIT_BREAKER_LOSSES = 5      # Halt after 5 consecutive losses
MAX_RETRIES = 1                 # Retry once on execution failure

# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

GUARDIAN_LOG = LOGS_DIR / "risk-guardian.jsonl"
GUARDIAN_STATE = LOGS_DIR / "risk-guardian-state.json"
GUARDIAN_REPORT = WORKSPACE / "RISK_GUARDIAN_REPORT.md"


# ---------------------------------------------------------------------------
# State Manager
# ---------------------------------------------------------------------------

class GuardianState:
    """Persistent state for idempotent, cron-safe operation."""

    def __init__(self):
        self.path = GUARDIAN_STATE
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return {
            "peak_account_value": 0.0,
            "consecutive_losses": 0,
            "halted": False,
            "halt_reason": None,
            "recent_executions": [],  # [{coin, timestamp, action}]
            "total_closes": 0,
            "total_losses_usd": 0.0,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    def save(self) -> None:
        self.data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2))

    def update_peak(self, value: float) -> None:
        if value > self.data["peak_account_value"]:
            self.data["peak_account_value"] = value
            self.save()

    def record_close(self, coin: str, pnl: float) -> None:
        self.data["total_closes"] += 1
        self.data["recent_executions"].append({
            "coin": coin, "action": "close",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "pnl": pnl,
        })
        # Keep last 50
        self.data["recent_executions"] = self.data["recent_executions"][-50:]
        if pnl < 0:
            self.data["consecutive_losses"] += 1
            self.data["total_losses_usd"] += abs(pnl)
        else:
            self.data["consecutive_losses"] = 0
        self.save()

    def check_circuit_breaker(self, account_value: float) -> tuple[bool, str]:
        """Returns (safe, reason). safe=True means OK to execute."""
        if self.data["halted"]:
            return False, f"SYSTEM HALTED: {self.data['halt_reason']}"

        if self.data["consecutive_losses"] >= CIRCUIT_BREAKER_LOSSES:
            self.data["halted"] = True
            self.data["halt_reason"] = f"{self.data['consecutive_losses']} consecutive losses"
            self.save()
            return False, f"CIRCUIT BREAKER: {self.data['consecutive_losses']} consecutive losses"

        peak = self.data["peak_account_value"]
        if peak > 0 and account_value > 0:
            dd = (peak - account_value) / peak
            if dd >= DRAWDOWN_PCT:
                self.data["halted"] = True
                self.data["halt_reason"] = f"Drawdown {dd:.1%} from peak ${peak:.4f}"
                self.save()
                return False, f"CIRCUIT BREAKER: {dd:.1%} drawdown from peak ${peak:.4f}"

        return True, "OK"

    def is_in_cooldown(self, coin: str) -> bool:
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=EXECUTION_COOLDOWN_SEC)).isoformat()
        for ex in reversed(self.data["recent_executions"]):
            if ex["coin"] == coin and ex["timestamp"] > cutoff:
                return True
        return False

    def reset_halt(self) -> None:
        self.data["halted"] = False
        self.data["halt_reason"] = None
        self.data["consecutive_losses"] = 0
        self.save()


# ---------------------------------------------------------------------------
# Log
# ---------------------------------------------------------------------------

def log_event(event: dict[str, Any]) -> None:
    event["logged_at"] = datetime.now(timezone.utc).isoformat()
    GUARDIAN_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(GUARDIAN_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, default=str) + "\n")


# ---------------------------------------------------------------------------
# Hyperliquid Client
# ---------------------------------------------------------------------------

class HLClient:
    """Thin Hyperliquid wrapper for risk guardian."""

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

    def get_state(self) -> dict[str, Any]:
        state = self.info.user_state(self.address)
        margin = state.get("marginSummary", {})
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
                "cum_funding": float(p.get("cumFunding", {}).get("sinceOpen", 0)),
            })
        return {
            "address": self.address,
            "account_value": float(margin.get("accountValue", 0)),
            "total_notional": float(margin.get("totalNtlPos", 0)),
            "withdrawable": float(state.get("withdrawable", 0)),
            "positions": positions,
        }

    def get_mid(self, coin: str) -> float | None:
        try:
            mids = self.info.all_mids()
            return float(mids.get(coin, 0)) or None
        except Exception:
            return None

    def close(self, coin: str, slippage: float = MAX_SLIPPAGE) -> dict[str, Any]:
        return self.exchange.market_close(coin=coin, slippage=slippage)


# ---------------------------------------------------------------------------
# Risk Evaluation
# ---------------------------------------------------------------------------

def evaluate_position(pos: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a position against all risk rules. Returns enriched record."""
    roe = pos["roe"]
    value = pos["position_value"]
    coin = pos["coin"]

    triggers: list[str] = []
    action = "HOLD"

    # Stop-loss
    if roe <= STOP_LOSS_ROE:
        triggers.append(f"STOP_LOSS: ROE {roe:+.1%} <= {STOP_LOSS_ROE:.0%}")
        action = "CLOSE"

    # Exposure check
    if value > MAX_EXPOSURE_PER_TRADE:
        triggers.append(f"OVER_EXPOSURE: ${value:.2f} > ${MAX_EXPOSURE_PER_TRADE:.2f}")
        # Don't auto-close for over-exposure, just alert
        if action == "HOLD":
            action = "ALERT"

    return {
        **pos,
        "triggers": triggers,
        "action": action,
    }


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def execute_close(
    client: HLClient, pos: dict[str, Any], state: GuardianState, dry_run: bool
) -> dict[str, Any]:
    """Execute a position close with full safety checks."""
    coin = pos["coin"]
    result: dict[str, Any] = {
        "action": "guardian_close",
        "coin": coin,
        "dry_run": dry_run,
        "triggers": pos.get("triggers", []),
        "position_before": {
            "size": pos["size"], "direction": pos["direction"],
            "entry_price": pos["entry_price"], "roe": pos["roe"],
            "unrealized_pnl": pos["unrealized_pnl"],
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Safety: cooldown
    if state.is_in_cooldown(coin):
        result["result"] = "BLOCKED_COOLDOWN"
        result["message"] = f"{coin} in {EXECUTION_COOLDOWN_SEC}s cooldown"
        log_event(result)
        return result

    # Safety: circuit breaker
    acct = client.get_state()
    state.update_peak(acct["account_value"])
    safe, reason = state.check_circuit_breaker(acct["account_value"])
    if not safe:
        result["result"] = "BLOCKED_CIRCUIT_BREAKER"
        result["message"] = reason
        log_event(result)
        return result

    # Safety: slippage
    mid = client.get_mid(coin)
    result["mid_price"] = mid
    if mid and pos["entry_price"] > 0:
        slip = abs(mid - pos["entry_price"]) / pos["entry_price"]
        if slip > MAX_SLIPPAGE:
            result["result"] = "BLOCKED_SLIPPAGE"
            result["message"] = f"Slippage {slip:.1%} > {MAX_SLIPPAGE:.0%}"
            log_event(result)
            return result

    # Log intent BEFORE execution
    log_event({**result, "phase": "INTENT"})

    if dry_run:
        result["result"] = "DRY_RUN"
        result["message"] = f"Would close {pos['size']} {coin} {pos['direction']}"
        result["sdk_call"] = f"exchange.market_close(coin='{coin}')"
        log_event(result)
        return result

    # Execute with retry
    for attempt in range(1 + MAX_RETRIES):
        try:
            response = client.close(coin)
            result["exchange_response"] = response
            result["attempt"] = attempt + 1

            # Check if filled
            statuses = response.get("response", {}).get("data", {}).get("statuses", [])
            filled = any("filled" in s for s in statuses if isinstance(s, dict))
            errored = any("error" in s for s in statuses if isinstance(s, dict))

            if filled:
                result["result"] = "EXECUTED"
                state.record_close(coin, pos["unrealized_pnl"])
                break
            elif errored:
                error_msg = statuses[0].get("error", "unknown") if statuses else "unknown"
                result["result"] = "EXCHANGE_REJECTED"
                result["message"] = error_msg
                if attempt < MAX_RETRIES:
                    time.sleep(2)
                    continue
                break
            else:
                result["result"] = "UNKNOWN_RESPONSE"
                break

        except Exception as e:
            result["result"] = "ERROR"
            result["message"] = f"{type(e).__name__}: {e}"
            result["attempt"] = attempt + 1
            if attempt < MAX_RETRIES:
                time.sleep(2)
                continue

    # Verify
    if result.get("result") == "EXECUTED":
        time.sleep(1)
        new_state = client.get_state()
        still_open = any(p["coin"] == coin for p in new_state["positions"])
        result["verified_closed"] = not still_open
        result["account_after"] = new_state["account_value"]
        if still_open:
            result["result"] = "EXECUTED_NOT_VERIFIED"
            log_event({"level": "CRITICAL", "message": f"Close sent but {coin} still open"})

    log_event(result)
    return result


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def write_report(
    account: dict[str, Any], evaluated: list[dict[str, Any]],
    actions: list[dict[str, Any]], state: GuardianState, dry_run: bool,
) -> str:
    now = datetime.now(timezone.utc)
    lines = [
        "# Risk Guardian Report",
        "",
        f"> ⚠️ AUTONOMOUS PROTECTION — {'DRY RUN' if dry_run else '🔴 LIVE'}",
        "",
        f"**Run:** {now.isoformat()}  ",
        f"**Account:** `{account.get('address', '?')[:12]}...`  ",
        f"**Value:** ${account.get('account_value', 0):.6f}  ",
        f"**Peak:** ${state.data.get('peak_account_value', 0):.6f}  ",
        f"**Circuit Breaker:** {'🔴 HALTED: ' + (state.data.get('halt_reason') or '') if state.data.get('halted') else '🟢 OK'}  ",
        f"**Consecutive Losses:** {state.data.get('consecutive_losses', 0)} / {CIRCUIT_BREAKER_LOSSES}",
        "",
    ]

    # Positions
    if evaluated:
        lines.append("## Positions")
        lines.append("| Coin | Dir | Size | Entry | ROE | PnL | Action | Triggers |")
        lines.append("|------|-----|------|-------|-----|-----|--------|----------|")
        for p in evaluated:
            triggers = "; ".join(p.get("triggers", [])) or "—"
            lines.append(
                f"| {p['coin']} | {p['direction']} | {p['size']} "
                f"| ${p['entry_price']:,.2f} | {p['roe']:+.1%} "
                f"| ${p['unrealized_pnl']:+.4f} | **{p['action']}** | {triggers} |"
            )
        lines.append("")
    else:
        lines.append("## Positions\n_No open positions._\n")

    # Actions taken
    if actions:
        lines.append("## Actions Taken")
        for a in actions:
            emoji = "✅" if a.get("result") == "EXECUTED" else "🔶" if a.get("result") == "DRY_RUN" else "❌"
            lines.append(f"- {emoji} **{a['coin']}**: {a.get('result', '?')} — {'; '.join(a.get('triggers', []))}")
        lines.append("")

    # Risk Parameters
    lines.extend([
        "## Risk Parameters",
        f"- Stop-loss: {STOP_LOSS_ROE:.0%} ROE",
        f"- Timeout: {TIMEOUT_HOURS}h",
        f"- Drawdown halt: {DRAWDOWN_PCT:.0%}",
        f"- Max exposure/trade: ${MAX_EXPOSURE_PER_TRADE}",
        f"- Slippage limit: {MAX_SLIPPAGE:.0%}",
        f"- Cooldown: {EXECUTION_COOLDOWN_SEC}s",
        f"- Circuit breaker: {CIRCUIT_BREAKER_LOSSES} losses",
        "",
        "---",
        f"_Risk Guardian v1 — {now.isoformat()}_",
    ])

    report = "\n".join(lines)
    GUARDIAN_REPORT.write_text(report, encoding="utf-8")
    return report


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_guardian(dry_run: bool = False, status_only: bool = False) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    mode = "DRY RUN" if dry_run else "🔴 LIVE"
    print(f"\n{'='*60}")
    print(f"  RISK GUARDIAN — {mode}")
    print(f"  {now.isoformat()}")
    print(f"{'='*60}\n")

    state = GuardianState()
    client = HLClient()

    # 1. Read account
    acct = client.get_state()
    state.update_peak(acct["account_value"])
    positions = acct["positions"]
    print(f"[1/4] Account: ${acct['account_value']:.6f} | Positions: {len(positions)}")

    if status_only:
        for p in positions:
            print(f"  {p['coin']} {p['direction']} {p['size']} | ROE: {p['roe']:+.1%} | PnL: ${p['unrealized_pnl']:+.4f}")
        safe, reason = state.check_circuit_breaker(acct["account_value"])
        print(f"  Circuit breaker: {'🟢 ' + reason if safe else '🔴 ' + reason}")
        return {"status": "OK", "positions": len(positions)}

    # 2. Evaluate
    evaluated = [evaluate_position(p) for p in positions]
    closes_needed = [p for p in evaluated if p["action"] == "CLOSE"]
    alerts = [p for p in evaluated if p["action"] == "ALERT"]
    holds = [p for p in evaluated if p["action"] == "HOLD"]
    print(f"[2/4] Evaluated: {len(holds)} HOLD | {len(closes_needed)} CLOSE | {len(alerts)} ALERT")

    for a in alerts:
        print(f"  ⚠️ ALERT: {a['coin']} — {'; '.join(a['triggers'])}")

    # 3. Execute closes
    actions_taken = []
    for p in closes_needed:
        print(f"[3/4] CLOSING {p['coin']} — {'; '.join(p['triggers'])}")
        result = execute_close(client, p, state, dry_run)
        actions_taken.append(result)
        print(f"       Result: {result.get('result', '?')}")

    if not closes_needed:
        print(f"[3/4] No closes needed")

    # 4. Report
    write_report(acct, evaluated, actions_taken, state, dry_run)
    print(f"[4/4] Report: {GUARDIAN_REPORT}")

    summary = {
        "timestamp": now.isoformat(),
        "positions": len(positions),
        "closes": len(closes_needed),
        "actions": [{"coin": a["coin"], "result": a.get("result")} for a in actions_taken],
        "circuit_breaker_ok": not state.data.get("halted", False),
    }
    log_event({"event": "guardian_run", **summary})
    state.save()

    print(f"\n{'='*60}")
    print(f"  DONE — {len(holds)} held, {len(actions_taken)} acted, {len(alerts)} alerted")
    print(f"{'='*60}\n")
    return summary


if __name__ == "__main__":
    args = sys.argv[1:]
    dry = "--dry-run" in args
    status = "--status" in args
    run_guardian(dry_run=dry, status_only=status)
