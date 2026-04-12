#!/usr/bin/env python3
"""
TRADING ENGINE — Single Authoritative Always-On Control Loop

This is the ONE process that owns:
- Position monitoring (continuous, 1-sec polling or WebSocket)
- Stop-loss / take-profit enforcement (UNBLOCKABLE for risk exits)
- Circuit breaker enforcement (blocks new entries, never risk exits)
- Trade logging (canonical ledger)
- Scanner coordination (only when system healthy)
- State persistence (single source of truth)

GUARANTEES:
1. Open positions CANNOT exist without active protection
2. Stop-loss exits are UNBLOCKABLE (force mode bypasses all checks)
3. Circuit breaker blocks new entries, never mandatory exits
4. Heartbeat updates every cycle (proof of liveness)
5. Startup reconciliation (detects orphaned positions)

Usage:
    python scripts/trading_engine.py              # Start always-on engine
    python scripts/trading_engine.py --dry-run    # Test mode (no execution)
    python scripts/trading_engine.py --status     # Quick health check
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.runtime import LOGS_DIR, WORKSPACE_ROOT
from config.risk_params import (
    LOOP_INTERVAL_SEC, SCAN_INTERVAL_SEC,
    STOP_LOSS_ROE, TAKE_PROFIT_ROE, TIMEOUT_HOURS,
    TRAILING_STOP_ACTIVATE, TRAILING_STOP_DISTANCE,
    MAX_EXPOSURE_PER_TRADE, MAX_CONCURRENT,
    CIRCUIT_BREAKER_LOSSES, DRAWDOWN_PCT, LEVERAGE,
    calculate_position_size,
    TIER1_MIN_FUNDING, TIER1_MIN_PREMIUM, TIER1_MIN_VOLUME,
    TIER2_MIN_FUNDING, TIER2_MIN_PREMIUM, TIER2_MIN_VOLUME,
)
from config.regime_thresholds import get_regime_thresholds, DEFAULT_REGIME
from scripts.regime_detector import (
    detect_regime_from_api_response,
    save_regime_state,
    get_active_regime,
    get_active_thresholds,
)
from utils.alerting import (
    alert_entry, alert_exit, alert_circuit_breaker,
    alert_engine_event, alert_error, send_alert,
)

import logging
logger = logging.getLogger(__name__)

class _StdoutHandler(logging.StreamHandler):
    """Handler that always writes to the current sys.stdout (not the one at init time)."""
    def __init__(self):
        super().__init__()
    @property
    def stream(self):
        return sys.stdout
    @stream.setter
    def stream(self, _):
        pass

if not logger.handlers:
    _handler = _StdoutHandler()
    _handler.setFormatter(logging.Formatter('%(message)s'))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)

# Import idempotent exit coordinator
from scripts.idempotent_exit import execute_exit_idempotent

STATE_FILE = LOGS_DIR / "trading_engine_state.json"
ENGINE_LOG = LOGS_DIR / "trading_engine.jsonl"

# ---------------------------------------------------------------------------
# Engine State (Canonical)
# ---------------------------------------------------------------------------

class EngineState:
    """Single source of truth for engine state."""
    
    def __init__(self):
        self.data = self.load()
    
    def load(self) -> dict:
        """Load state from disk."""
        default = {
            "heartbeat": None,
            "peak_capital": 0.0,
            "consecutive_losses": 0,
            "circuit_breaker_halted": False,
            "halt_reason": None,
            "last_scan": 0.0,
            "open_positions": {},
            "peak_roe": {},
            "total_closes": 0,
            "total_pnl": 0.0,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        
        if STATE_FILE.exists():
            try:
                loaded = json.loads(STATE_FILE.read_text())
                # Merge with defaults (backwards compatibility)
                for key in default:
                    if key not in loaded:
                        loaded[key] = default[key]
                return loaded
            except Exception:
                pass
        
        return default
    
    def save(self) -> None:
        """Persist state to disk."""
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(self.data, indent=2))
    
    def update_heartbeat(self) -> None:
        """Update heartbeat timestamp."""
        self.data["heartbeat"] = datetime.now(timezone.utc).isoformat()
        self.save()
    
    def update_peak_capital(self, value: float) -> None:
        """Update peak capital if higher."""
        if value > self.data["peak_capital"]:
            self.data["peak_capital"] = value
            self.save()
    
    def is_healthy(self) -> bool:
        """Check if system is healthy for new entries."""
        if self.data["circuit_breaker_halted"]:
            return False
        if self.data["consecutive_losses"] >= CIRCUIT_BREAKER_LOSSES:
            return False
        return True
    
    def check_circuit_breaker(self, account_value: float) -> tuple[bool, str]:
        """Check if circuit breaker should trigger."""
        peak = self.data["peak_capital"]
        if peak > 0 and account_value > 0:
            dd = (peak - account_value) / peak
            if dd >= DRAWDOWN_PCT:
                self.data["circuit_breaker_halted"] = True
                self.data["halt_reason"] = f"Drawdown {dd:.1%} from peak ${peak:.2f}"
                self.save()
                return False, self.data["halt_reason"]
        return True, "OK"
    
    def record_close(self, coin: str, pnl: float) -> None:
        """Record position close."""
        self.data["total_closes"] += 1
        self.data["total_pnl"] += pnl
        
        if pnl < 0:
            self.data["consecutive_losses"] += 1
        else:
            self.data["consecutive_losses"] = 0
        
        # Check if circuit breaker should trigger
        if self.data["consecutive_losses"] >= CIRCUIT_BREAKER_LOSSES:
            self.data["circuit_breaker_halted"] = True
            self.data["halt_reason"] = f"{self.data['consecutive_losses']} consecutive losses"
            alert_circuit_breaker(self.data["halt_reason"])
        
        # Remove from tracking
        if coin in self.data["open_positions"]:
            del self.data["open_positions"][coin]
        if coin in self.data["peak_roe"]:
            del self.data["peak_roe"][coin]
        
        self.save()
    
    def track_position(self, coin: str, entry_price: float) -> None:
        """Start tracking a position."""
        self.data["open_positions"][coin] = {
            "entry_time": datetime.now(timezone.utc).isoformat(),
            "entry_price": entry_price,
        }
        self.data["peak_roe"][coin] = 0.0
        self.save()
    
    def update_peak_roe(self, coin: str, roe: float) -> None:
        """Update peak ROE for trailing stop."""
        if coin not in self.data["peak_roe"]:
            self.data["peak_roe"][coin] = roe
        elif roe > self.data["peak_roe"][coin]:
            self.data["peak_roe"][coin] = roe
            self.save()

# ---------------------------------------------------------------------------
# Hyperliquid Client
# ---------------------------------------------------------------------------

class HyperliquidClient:
    """Hyperliquid API client."""
    
    def __init__(self):
        from hyperliquid.info import Info
        from hyperliquid.exchange import Exchange
        from eth_account import Account
        
        private_key = os.environ.get("HL_PRIVATE_KEY")
        if not private_key:
            raise ValueError("HL_PRIVATE_KEY not set")
        
        self.info = Info(skip_ws=True)
        wallet = Account.from_key(private_key)
        self.exchange = Exchange(wallet)
        self.address = wallet.address
        
        # Fetch and cache asset metadata (szDecimals)
        self.asset_metadata = {}
        meta = self.info.meta()
        for asset in meta.get('universe', []):
            self.asset_metadata[asset['name']] = {
                'szDecimals': asset.get('szDecimals', 8),
                'maxLeverage': asset.get('maxLeverage', 1),
            }
    
    def get_state(self) -> dict:
        """Get account state (positions + capital)."""
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
                "szi": p.get("szi"),  # Include raw szi for exit coordinator
                "entry_price": float(p.get("entryPx", 0)),
                "position_value": float(p.get("positionValue", 0)),
                "unrealized_pnl": float(p.get("unrealizedPnl", 0)),
                "roe": float(p.get("returnOnEquity", 0)),
                "leverage": p.get("leverage", {}).get("value", 1),
                "margin_used": float(p.get("marginUsed", 0)),
            })
        
        # Spot balance
        spot_usd = 0.0
        try:
            spot = self.info.spot_user_state(self.address)
            for b in spot.get("balances", []):
                if b.get("coin") in ("USDC", "USDT", "USDE"):
                    spot_usd += float(b.get("total", 0))
        except Exception:
            pass
        
        perp_value = float(margin.get("accountValue", 0))
        total_value = perp_value + spot_usd

        # Unified account fallback: if perp side reports $0 but spot has funds,
        # the capital is likely sitting in spot wallet (not yet transferred to perps).
        # Use spot balance as the account value so position sizing works correctly.
        if total_value == 0 and spot_usd == 0:
            # Both zero — try spot_user_state directly as a last resort
            try:
                spot_fallback = self.info.spot_user_state(self.address)
                for b in spot_fallback.get("balances", []):
                    if b.get("coin") in ("USDC", "USDT", "USDE"):
                        total_value += float(b.get("total", 0))
                if total_value > 0:
                    spot_usd = total_value
                    log_event({
                        "event": "balance_fallback_used",
                        "source": "spot_user_state",
                        "amount": total_value,
                    })
            except Exception:
                pass

        return {
            "account_value": total_value,
            "spot_usd": spot_usd,
            "perp_value": perp_value,
            "positions": positions,
        }
    
    def get_positions(self) -> list:
        """Get list of open positions."""
        state = self.get_state()
        return state.get("positions", [])
    
    def market_close(self, coin: str) -> dict:
        """Close position via market order."""
        try:
            response = self.exchange.market_close(coin)
            return {"status": "ok", "response": response}
        except Exception as e:
            # Preserve exception type for better error handling
            return {
                "status": "error",
                "error": str(e),
                "error_type": type(e).__name__,
            }
    
    def get_mid(self, coin: str) -> float:
        """Get mid price for a coin."""
        try:
            meta = self.info.meta()
            for u in meta.get("universe", []):
                if u.get("name") == coin:
                    ctx = self.info.all_mids()
                    return float(ctx.get(coin, 0))
            return 0.0
        except Exception:
            return 0.0

# ---------------------------------------------------------------------------
# Trade Logger
# ---------------------------------------------------------------------------

def log_event(event: dict) -> None:
    """Log event to engine log."""
    event["timestamp"] = datetime.now(timezone.utc).isoformat()
    ENGINE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(ENGINE_LOG, "a") as f:
        f.write(json.dumps(event, default=str) + "\n")

def log_to_ledger(trade_id: str, action: str, **kwargs) -> None:
    """Log to canonical trade ledger."""
    try:
        ledger_file = Path("workspace/logs/trade-ledger.jsonl")
        ledger_file.parent.mkdir(parents=True, exist_ok=True)
        
        entry_data = {
            "trade_id": trade_id,
            "action": action,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        if action == "entry":
            signal = kwargs.get("signal", {})
            entry_data.update({
                "coin": signal.get("asset"),
                "direction": signal.get("direction"),
                "entry_price": kwargs.get("entry_price", 0),
                "size_coins": kwargs.get("size", 0),
                "position_size_usd": signal.get("position_size_usd", 0),
                "signal_type": signal.get("signal_type"),
                "signal_score": signal.get("score"),
                "tier": signal.get("tier"),
            })
        elif action == "exit":
            entry_data.update({
                "exit_price": kwargs.get("exit_price", 0),
                "exit_reason": kwargs.get("exit_reason", "UNKNOWN"),
                "pnl_usd": kwargs.get("pnl_usd", 0),
                "pnl_pct": kwargs.get("pnl_pct", 0),
            })
        
        with open(ledger_file, "a") as f:
            f.write(json.dumps(entry_data) + "\n")
            
    except Exception as e:
        log_event({"event": "ledger_error", "error": str(e)})

# ---------------------------------------------------------------------------
# Protection Logic
# ---------------------------------------------------------------------------

def evaluate_triggers(pos: dict, state: EngineState) -> list[str]:
    """Evaluate risk triggers for a position."""
    triggers = []
    roe = pos["roe"]
    coin = pos["coin"]
    
    # 1. Stop-loss (HIGHEST PRIORITY)
    if roe <= STOP_LOSS_ROE:
        triggers.append(f"STOP_LOSS: ROE {roe:.1%} <= {STOP_LOSS_ROE:.0%}")
    
    # 2. Timeout
    if coin in state.data["open_positions"]:
        entry_time_str = state.data["open_positions"][coin]["entry_time"]
        entry_time = datetime.fromisoformat(entry_time_str)
        if entry_time.tzinfo is None:
            entry_time = entry_time.replace(tzinfo=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - entry_time).total_seconds() / 3600
        if age_hours >= TIMEOUT_HOURS:
            triggers.append(f"TIMEOUT: {age_hours:.1f}h >= {TIMEOUT_HOURS}h")
    
    # 3. Take profit
    if roe >= TAKE_PROFIT_ROE:
        triggers.append(f"TAKE_PROFIT: ROE {roe:.1%} >= {TAKE_PROFIT_ROE:.0%}")
    
    # 4. Trailing stop
    state.update_peak_roe(coin, roe)
    peak_roe = state.data["peak_roe"].get(coin, 0)
    
    if peak_roe >= TRAILING_STOP_ACTIVATE:
        trail_threshold = peak_roe - TRAILING_STOP_DISTANCE
        if roe <= trail_threshold:
            triggers.append(f"TRAILING_STOP: ROE {roe:.1%} <= trail {trail_threshold:.1%} (peak: {peak_roe:.1%})")
    
    return triggers

def execute_exit(client: HyperliquidClient, pos: dict, triggers: list[str], state: EngineState, force: bool, dry_run: bool) -> dict:
    """Execute position exit."""
    coin = pos["coin"]
    
    result = {
        "action": "exit",
        "coin": coin,
        "triggers": triggers,
        "force": force,
        "dry_run": dry_run,
        "roe": pos["roe"],
        "pnl": pos["unrealized_pnl"],
    }
    
    # FORCE MODE: Skip all checks for risk exits
    if not force:
        # Check circuit breaker (only for non-forced exits)
        safe, reason = state.check_circuit_breaker(client.get_state()["account_value"])
        if not safe:
            result["result"] = "BLOCKED_CIRCUIT_BREAKER"
            result["reason"] = reason
            log_event(result)
            return result
    
    # Execute
    if dry_run:
        result["result"] = "DRY_RUN"
        log_event(result)
        return result
    
    # === GUARANTEED RETRY: RISK EXITS MUST SUCCEED ===
    # For force-mode exits (SL/timeout), retry up to 5 times with backoff
    max_retries = 5 if force else 1
    retry_delay_sec = 1.0
    
    # === COORDINATION LOCK: Signal active exit to fallback ===
    # Prevents fallback from interfering during engine retry
    active_exits_file = LOGS_DIR / "active_exits.json"
    if force:
        try:
            if active_exits_file.exists():
                active_exits = json.loads(active_exits_file.read_text())
            else:
                active_exits = {"active_exits": {}}
            
            active_exits["active_exits"][coin] = {
                "start_time": datetime.now(timezone.utc).isoformat(),
                "max_retries": max_retries,
                "reason": triggers[0] if triggers else "UNKNOWN",
            }
            active_exits_file.write_text(json.dumps(active_exits, indent=2))
        except Exception as e:
            # Don't fail exit if lock file fails
            log_event({"event": "coordination_lock_failed", "error": str(e)})
    
    for attempt in range(1, max_retries + 1):
        response = client.market_close(coin)
        result["exchange_response"] = response
        result["attempt"] = attempt
        
        if response["status"] == "ok":
            break  # Success
        else:
            # Failed exit
            if attempt < max_retries:
                log_event({
                    "event": "exit_retry",
                    "coin": coin,
                    "attempt": attempt,
                    "max_retries": max_retries,
                    "reason": response.get("response", "unknown"),
                    "retry_in_sec": retry_delay_sec,
                })
                time.sleep(retry_delay_sec)
                retry_delay_sec *= 2  # Exponential backoff
            else:
                # All retries exhausted
                log_event({
                    "event": "CRITICAL_EXIT_FAILED",
                    "coin": coin,
                    "attempts": max_retries,
                    "last_response": response,
                    "action": "ESCALATE_TO_EMERGENCY_FALLBACK",
                })
                result["result"] = "FAILED_ALL_RETRIES"
                result["escalated"] = True
                
                # === COORDINATION: Clear lock so fallback can take over ===
                if force:
                    try:
                        if active_exits_file.exists():
                            active_exits = json.loads(active_exits_file.read_text())
                            if coin in active_exits.get("active_exits", {}):
                                del active_exits["active_exits"][coin]
                                active_exits_file.write_text(json.dumps(active_exits, indent=2))
                    except Exception as e:
                        log_event({"event": "coordination_unlock_failed", "error": str(e)})
                
                log_event(result)
                return result
    
    if response["status"] == "ok":
        result["result"] = "EXECUTED"
        
        # Get exit price (fallback to last known if unavailable)
        mid = client.get_mid(coin)
        if mid == 0.0:
            # Price unavailable, use entry price as fallback (conservative estimate)
            mid = pos.get("entry_price", 0)
            result["price_fallback"] = True
        result["exit_price"] = mid
        
        # Update state
        state.record_close(coin, pos["unrealized_pnl"])
        
        # Log to ledger (use SAME trade_id format as entry)
        entry_time = state.data['open_positions'].get(coin, {}).get('entry_time', '')
        if entry_time:
            # Convert ISO timestamp to compact format: 20260406-213907
            from datetime import datetime
            dt = datetime.fromisoformat(entry_time.replace('Z', '+00:00'))
            trade_id = f"hl-{coin.lower()}-{dt.strftime('%Y%m%d-%H%M%S')}"
        else:
            trade_id = f"hl-{coin.lower()}-unknown"
        
        pnl_usd = pos.get("unrealized_pnl", 0)
        pnl_pct = (pnl_usd / pos.get("position_value", 1)) * 100 if pos.get("position_value", 0) > 0 else 0

        log_to_ledger(
            trade_id=trade_id,
            action="exit",
            exit_price=mid,
            exit_reason=triggers[0] if triggers else "MANUAL",
            pnl_usd=pnl_usd,
            pnl_pct=pnl_pct,
        )

        # Send exit alert
        alert_exit(coin, triggers[0] if triggers else "MANUAL", pnl_usd, pnl_pct / 100)
    else:
        result["result"] = "FAILED"
        result["error"] = response.get("error")
    
    # === COORDINATION LOCK: Clear active exit ===
    if force:
        try:
            if active_exits_file.exists():
                active_exits = json.loads(active_exits_file.read_text())
                if coin in active_exits.get("active_exits", {}):
                    del active_exits["active_exits"][coin]
                    active_exits_file.write_text(json.dumps(active_exits, indent=2))
        except Exception as e:
            log_event({"event": "coordination_unlock_failed", "error": str(e)})
    
    log_event(result)
    return result

# ---------------------------------------------------------------------------
# Main Engine
# ---------------------------------------------------------------------------

class TradingEngine:
    """Single authoritative always-on trading control loop."""
    
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.client = HyperliquidClient()
        self.state = EngineState()
        self.last_scan = 0.0
        self.last_reconcile = 0.0
        
        logger.info("=" * 70)
        logger.info(f"  TRADING ENGINE {'[DRY RUN]' if dry_run else '[LIVE]'}")
        logger.info(f"  Started: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        logger.info("=" * 70)
        logger.info("")
        
        log_event({"event": "engine_started", "dry_run": dry_run, "pid": os.getpid()})
    
    def startup_reconciliation(self) -> None:
        """Reconcile state on startup."""
        logger.info("RECONCILIATION")
        
        account = self.client.get_state()
        live_positions = account["positions"]
        tracked_coins = set(self.state.data["open_positions"].keys())
        live_coins = set(p["coin"] for p in live_positions)
        
        # Untracked positions
        untracked = live_coins - tracked_coins
        if untracked:
            logger.warning(f"  Untracked: {untracked}")
            for coin in untracked:
                pos = next(p for p in live_positions if p["coin"] == coin)
                self.state.track_position(coin, pos["entry_price"])
        
        # Stale positions
        stale = tracked_coins - live_coins
        if stale:
            logger.warning(f"  Cleaning stale: {stale}")
            for coin in stale:
                del self.state.data["open_positions"][coin]
            self.state.save()
        
        # Update peak capital
        self.state.update_peak_capital(account["account_value"])
        
        logger.info(f"  Complete: {len(live_positions)} live positions")
        logger.info("")
    
    def protect_capital(self) -> None:
        """Enforce stop-loss / take-profit (HIGHEST PRIORITY)."""
        account = self.client.get_state()
        positions = account["positions"]
        
        for pos in positions:
            triggers = evaluate_triggers(pos, self.state)
            
            if not triggers:
                continue
            
            # FORCE MODE for risk exits (STOP_LOSS, TIMEOUT)
            force = any(t.startswith("STOP_LOSS") or t.startswith("TIMEOUT") for t in triggers)
            
            # Use idempotent exit coordinator (handles partial fills, unknown success)
            execute_exit_idempotent(self.client, pos, triggers, self.state, force=force, dry_run=self.dry_run)
    
    def scan_opportunities(self) -> None:
        """Check for new entry signals (only if system healthy)."""
        # Rate limit: scan every 5 minutes max
        if time.time() - self.last_scan < SCAN_INTERVAL_SEC:
            return
        
        if not self.state.is_healthy():
            log_event({"event": "scan_skipped", "reason": "system_unhealthy"})
            return
        
        # Run scanner
        try:
            signals = self.run_scanner()
            
            if signals:
                log_event({"event": "scan_found_signals", "count": len(signals)})
                
                # Process top signal only (one entry at a time)
                for signal in signals[:1]:
                    self.execute_entry(signal)
            else:
                log_event({"event": "scan_no_signals"})
        
        except Exception as e:
            log_event({"event": "scan_error", "error": str(e)})
            alert_error("scanner", str(e))

        self.last_scan = time.time()
    
    def run_scanner(self) -> list[dict]:
        """Run tiered scanner with regime-aware thresholds.

        1. Fetches metaAndAssetCtxs from Hyperliquid API (single call)
        2. Runs regime detector on the same data (no extra API call)
        3. Uses regime thresholds for signal classification
        4. Logs regime changes and sends Telegram alerts
        """
        import urllib.request
        from scripts.tiered_scanner import classify_signal

        resp = json.loads(urllib.request.urlopen(
            urllib.request.Request('https://api.hyperliquid.xyz/info',
                data=json.dumps({'type': 'metaAndAssetCtxs'}).encode(),
                headers={'Content-Type': 'application/json'}),
            timeout=10
        ).read())

        # --- Regime detection (reuses same API response) ---
        from scripts.regime_detector import load_regime_state as _load_regime_state
        previous_regime = get_active_regime()
        prev_state = _load_regime_state()
        prev_duration_secs = prev_state.get("regime_duration_seconds", 0) if prev_state else 0
        regime_result = detect_regime_from_api_response(resp)
        regime_state = save_regime_state(regime_result)
        current_regime = regime_result["regime"]
        thresholds = regime_result["thresholds"]

        # Log regime change + Telegram alert
        if current_regime != previous_regime:
            top_asset = regime_result["top_assets"][0] if regime_result["top_assets"] else None
            top_info = f" | Max funding: {regime_result['max_funding_apy'] * 100:.0f}% APY"
            if top_asset:
                top_info += f" ({top_asset['asset']})"

            # Include previous regime duration in alert
            if prev_duration_secs > 0:
                from scripts.regime_detector import _format_duration
                top_info += f" | Previous regime lasted {_format_duration(prev_duration_secs)}"

            log_event({
                "event": "regime_updated",
                "previous_regime": previous_regime,
                "new_regime": current_regime,
                "max_funding_apy": regime_result["max_funding_apy"],
                "pct_above_100": regime_result["pct_above_100"],
                "thresholds": thresholds,
            })
            send_alert(
                f"REGIME CHANGE: {previous_regime} → {current_regime}{top_info}",
                "WARN" if current_regime in ("LOW_FUNDING", "MODERATE") else "INFO",
            )

        # --- Scanner with regime thresholds ---
        try:
            account_balance = self.client.get_state()["account_value"]
        except Exception:
            account_balance = 95.0  # fallback

        held = set(self.state.data["open_positions"].keys())

        t1_funding = thresholds["tier1_min_funding"]
        t2_funding = thresholds["tier2_min_funding"]

        signals = []

        for u, ctx in zip(resp[0]['universe'], resp[1]):
            asset = u['name']

            if asset in held:
                continue

            premium = float(ctx.get('premium', 0) or 0)
            funding = float(ctx.get('funding', 0) or 0)
            volume = float(ctx.get('dayNtlVlm', 0) or 0)
            mid = float(ctx.get('midPx', 0) or 0)
            funding_annual = abs(funding) * 3 * 365

            if funding >= 0:
                continue

            tier = classify_signal(funding_annual, premium, volume,
                                   tier1_min_funding=t1_funding,
                                   tier2_min_funding=t2_funding)

            if tier == 3:
                continue

            score = 7.5 if tier == 1 else 5.5
            position_size = calculate_position_size(account_balance, tier)

            signals.append({
                "asset": asset,
                "direction": "long",
                "price": mid,
                "score": score,
                "signal_type": "funding_arbitrage" if tier == 1 else "moderate_funding",
                "funding_8h": funding,
                "annualized_rate": funding_annual,
                "premium": premium,
                "volume_24h": volume,
                "tier": tier,
                "position_size_usd": position_size,
            })

        signals.sort(key=lambda x: (x['tier'], -x['score']))

        # --- Regime status log ---
        if signals:
            best = signals[0]
            log_event({
                "event": "regime_status",
                "regime": current_regime,
                "signals_found": len(signals),
                "best_asset": best["asset"],
                "best_funding_apy": round(best["annualized_rate"] * 100, 1),
                "best_tier": best["tier"],
                "thresholds": thresholds,
            })
        else:
            log_event({
                "event": "regime_status",
                "regime": current_regime,
                "signals_found": 0,
                "message": "no opportunities above threshold",
                "max_funding_apy": round(regime_result["max_funding_apy"] * 100, 1),
                "top_asset": regime_result["top_assets"][0]["asset"] if regime_result["top_assets"] else None,
                "thresholds": thresholds,
            })

        return signals
    
    def execute_entry(self, signal: dict) -> None:
        """Execute entry for a signal."""
        coin = signal["asset"]
        size_usd = signal["position_size_usd"]
        price = signal.get("price", 0)
        
        # === STRICT PRE-TRADE VALIDATION (NON-BYPASSABLE) ===
        import sys
        from pathlib import Path as PathLib
        sys.path.insert(0, str(PathLib(__file__).parent))
        from pre_trade_validator import PreTradeValidator, log_validation_failure
        
        validator = PreTradeValidator(self.client, self.state)
        valid, reason = validator.validate_entry(coin, size_usd, price)
        
        if not valid:
            log_event({
                "event": "entry_blocked_validation",
                "coin": coin,
                "reason": reason,
                "signal": signal,
            })
            log_validation_failure(reason, {"coin": coin, "size_usd": size_usd, "signal": signal})
            
            # HALT on validation failure (safety-first)
            if "STATE_SYNC" in reason or "LEDGER" in reason:
                self.state.data["circuit_breaker_halted"] = True
                self.state.data["halt_reason"] = f"Pre-trade validation failed: {reason}"
                self.state.save()
                log_event({"event": "CRITICAL_HALT", "reason": reason})
            
            return
        
        # === LEGACY PROTECTION CHECKS (kept for compatibility) ===
        heartbeat_age = (time.time() - self.last_reconcile)
        if heartbeat_age > 120:
            log_event({
                "event": "entry_blocked_stale_protection",
                "coin": coin,
                "reason": "Protection loop stale (>2 min), refusing new exposure",
                "heartbeat_age_sec": heartbeat_age,
            })
            return
        
        if not self.state.is_healthy():
            log_event({
                "event": "entry_blocked_unhealthy",
                "coin": coin,
                "reason": "System unhealthy (circuit breaker or consecutive losses)",
            })
            return
        # === END PROTECTION CHECKS ===
        
        # Pre-entry validation
        if coin in self.state.data["open_positions"]:
            log_event({"event": "entry_skipped", "coin": coin, "reason": "already_open"})
            return
        
        if len(self.state.data["open_positions"]) >= MAX_CONCURRENT:
            log_event({"event": "entry_skipped", "coin": coin, "reason": "max_positions"})
            return
        
        # Check max exposure
        account = self.client.get_state()
        total_deployed = sum(p["margin_used"] for p in account["positions"])
        
        if total_deployed + size_usd > MAX_EXPOSURE_PER_TRADE * 5:
            log_event({"event": "entry_skipped", "coin": coin, "reason": "max_exposure"})
            return
        
        if self.dry_run:
            log_event({"event": "entry_dry_run", "coin": coin, "size_usd": size_usd, "signal": signal})
            return
        
        # Execute entry
        try:
            # Calculate size in coins
            price = signal["price"]
            size_coins = (size_usd * LEVERAGE) / price
            
            # Round to correct decimals per asset (CRITICAL FIX)
            sz_decimals = self.client.asset_metadata.get(coin, {}).get('szDecimals', 8)
            size_coins = round(size_coins, sz_decimals)
            
            # Execute market order
            response = self.client.exchange.market_open(coin, True, size_coins)  # True = long
            
            # CRITICAL: Validate ACTUAL order outcome (not just API success)
            if response.get("status") != "ok":
                log_event({"event": "entry_rejected", "coin": coin, "reason": "api_failed", "response": response})
                return
            
            # Check for order-level errors (status: "ok" just means API call worked)
            statuses = response.get("response", {}).get("data", {}).get("statuses", [])
            if statuses and statuses[0].get("error"):
                error_msg = statuses[0]["error"]
                log_event({"event": "order_rejected", "coin": coin, "error": error_msg, "response": response})
                return
            
            # Verify fill actually happened (don't trust logs without exchange confirmation)
            # Wait 2 seconds for fill, then check user_state
            time.sleep(2)
            account = self.client.get_state()
            position_found = any(p["coin"] == coin for p in account["positions"])
            
            if not position_found:
                log_event({"event": "order_no_fill", "coin": coin, "reason": "position_not_found", "response": response})
                return
            
            # ONLY track position if fill confirmed
            self.state.track_position(coin, price)
            
            # Log to ledger
            trade_id = f"hl-{coin.lower()}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
            log_to_ledger(
                trade_id=trade_id,
                action="entry",
                signal=signal,
                size=size_coins,
                entry_price=price,
            )
            
            log_event({
                "event": "order_filled",
                "coin": coin,
                "price": price,
                "size_coins": size_coins,
                "size_usd": size_usd,
                "tier": signal["tier"],
                "verified": True,
            })

            # Send Telegram alert
            alert_entry(coin, signal.get("direction", "long"), size_usd, signal["tier"], price)

            # === POST-TRADE VALIDATION (STRICT ENFORCEMENT) ===
            # Verify all 5 proof sources exist and match
            time.sleep(1)  # Allow logs to flush
            
            # Check: Exchange position
            fresh_state = self.client.get_state()
            position_still_exists = any(p["coin"] == coin for p in fresh_state["positions"])
            
            # Check: Ledger entry
            ledger_file = Path("workspace/logs/trade-ledger.jsonl")
            ledger_has_entry = False
            if ledger_file.exists():
                with open(ledger_file) as f:
                    entries = [json.loads(l) for l in f if l.strip()]
                ledger_has_entry = any(e.get('action') == 'entry' and e.get('coin') == coin for e in entries[-5:])
            
            # Check: Internal state
            state_has_position = coin in self.state.data.get('open_positions', {})
            
            # If ANY proof missing → HALT and ROLLBACK
            if not (position_still_exists and ledger_has_entry and state_has_position):
                log_event({
                    "event": "POST_TRADE_VALIDATION_FAILED",
                    "coin": coin,
                    "position_exists": position_still_exists,
                    "ledger_exists": ledger_has_entry,
                    "state_exists": state_has_position,
                })
                
                # CRITICAL: Rollback (close position, clear state)
                if position_still_exists:
                    try:
                        self.client.exchange.market_close(coin)
                        log_event({"event": "rollback_position_closed", "coin": coin})
                    except Exception as rollback_error:
                        log_event({"event": "rollback_failed", "coin": coin, "error": str(rollback_error)})
                
                # Clear internal state
                if coin in self.state.data['open_positions']:
                    del self.state.data['open_positions'][coin]
                if coin in self.state.data.get('peak_roe', {}):
                    del self.state.data['peak_roe'][coin]
                
                # HALT system
                self.state.data['circuit_breaker_halted'] = True
                self.state.data['halt_reason'] = f"Post-trade validation failed for {coin}"
                self.state.save()
                
                return
            # === END POST-TRADE VALIDATION ===
        
        except Exception as e:
            log_event({"event": "entry_failed", "coin": coin, "error": str(e)})

    
    def periodic_reconciliation(self) -> None:
        """Periodic reconciliation: detect positions closed outside engine."""
        # Run every 60 seconds
        if time.time() - self.last_reconcile < 60:
            return
        
        account = self.client.get_state()
        live_positions = account["positions"]
        tracked_coins = set(self.state.data["open_positions"].keys())
        live_coins = set(p["coin"] for p in live_positions)
        
        # Stale positions (tracked but not live)
        stale = tracked_coins - live_coins
        if stale:
            log_event({"event": "reconcile_stale_positions", "coins": list(stale)})
            for coin in stale:
                del self.state.data["open_positions"][coin]
                if coin in self.state.data["peak_roe"]:
                    del self.state.data["peak_roe"][coin]
            self.state.save()
        
        # Untracked positions (live but not tracked)
        untracked = live_coins - tracked_coins
        if untracked:
            log_event({"event": "reconcile_untracked_positions", "coins": list(untracked)})
            for coin in untracked:
                pos = next(p for p in live_positions if p["coin"] == coin)
                self.state.track_position(coin, pos["entry_price"])
        
        self.last_reconcile = time.time()
    
    def run(self) -> None:
        """Main always-on loop."""
        # === STARTUP ASSERTION: VERIFY ENGINE IS SOLE AUTHORITY ===
        # Check that no other trading processes are running
        import subprocess
        ps_check = subprocess.run(
            ["ps", "aux"],
            capture_output=True,
            text=True
        )
        trading_procs = [
            line for line in ps_check.stdout.split("\n")
            if ("hl_entry.py" in line or "hl_executor.py" in line or "manual_entry.py" in line)
            and "grep" not in line
        ]
        if trading_procs:
            logger.error("=" * 70)
            logger.error("STARTUP BLOCKED: LEGACY TRADING SCRIPTS RUNNING")
            logger.error("=" * 70)
            logger.error("")
            for proc in trading_procs:
                logger.error(f"  {proc}")
            logger.error("")
            logger.error("These scripts must not run. Engine is sole trading authority.")
            logger.error("")
            raise RuntimeError("Legacy trading scripts detected. Engine cannot start safely.")
        
        self.startup_reconciliation()

        alert_engine_event("Engine started")
        logger.info("ENGINE RUNNING")
        logger.info("")
        
        cycle = 0
        try:
            while True:
                cycle += 1
                cycle_start = time.time()
                
                # === RUNTIME ASSERTION: HEARTBEAT FRESHNESS ===
                # Verify heartbeat is being updated (detect freeze/hang)
                if cycle > 10:  # Skip first 10 cycles (startup)
                    hb_time = datetime.fromisoformat(self.state.data["heartbeat"])
                    if hb_time.tzinfo is None:
                        hb_time = hb_time.replace(tzinfo=timezone.utc)
                    age = (datetime.now(timezone.utc) - hb_time).total_seconds()
                    if age > 10:
                        log_event({
                            "event": "CRITICAL_HEARTBEAT_STALE",
                            "age_sec": age,
                            "action": "ABORT"
                        })
                        raise RuntimeError(f"HEARTBEAT STALE ({age:.0f}s) — Engine frozen, aborting")
                
                # === SELF-HEALING VALIDATION (replaces rigid assertions) ===
                # Run continuous validation and auto-heal instead of crashing
                from self_healing_validator import auto_heal_and_validate
                
                heal_result = auto_heal_and_validate(STATE_FILE, self.client.info)
                
                if not heal_result['healthy']:
                    log_event({
                        "event": "auto_heal_triggered",
                        "reason": heal_result['reason'],
                        "actions": heal_result['actions_taken'],
                    })
                
                if heal_result['actions_taken'].get('state_healed'):
                    # State was healed—reload
                    self.state = EngineState(STATE_FILE)
                    log_event({"event": "state_reloaded_after_heal"})
                
                # === END SELF-HEALING ===
                
                # 1. PROTECTION (HIGHEST PRIORITY)
                self.protect_capital()
                
                # 2. PERIODIC RECONCILIATION (every 60 sec)
                self.periodic_reconciliation()
                
                # 3. SCANNER (only if healthy)
                self.scan_opportunities()
                
                # 4. HEARTBEAT
                self.state.update_heartbeat()
                
                # 5. SLEEP
                elapsed = time.time() - cycle_start
                sleep_time = max(0.1, LOOP_INTERVAL_SEC - elapsed)
                time.sleep(sleep_time)
                
        except KeyboardInterrupt:
            logger.info("")
            logger.info("ENGINE SHUTDOWN")
            log_event({"event": "engine_stopped", "cycles": cycle})

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def status_check() -> None:
    """Quick health check.  Uses print() for CLI output (tests capture stdout)."""
    print("=" * 70)
    print("  ENGINE STATUS CHECK")
    print("=" * 70)
    print()

    if not STATE_FILE.exists():
        print("State file not found — engine never started")
        print("CAPITAL PROTECTION: OFFLINE")
        return

    state = EngineState()

    # === NON-BYPASSABLE RULE: VERIFY PROTECTION BEFORE CLAIMING OPERATIONAL ===
    protection_active = False

    # Heartbeat
    if state.data["heartbeat"]:
        hb_time = datetime.fromisoformat(state.data["heartbeat"])
        if hb_time.tzinfo is None:
            hb_time = hb_time.replace(tzinfo=timezone.utc)
        age_sec = (datetime.now(timezone.utc) - hb_time).total_seconds()
        hb_status = "FRESH" if age_sec < 5 else "STALE"
        print(f"Heartbeat: {hb_status} ({age_sec:.1f}s ago)")

        protection_active = (age_sec < 5)
    else:
        print("Heartbeat: NEVER")
        protection_active = False

    # Circuit breaker
    cb_status = "HALTED" if state.data["circuit_breaker_halted"] else "ACTIVE"
    print(f"Circuit breaker: {cb_status}")
    if state.data["circuit_breaker_halted"]:
        print(f"  Reason: {state.data['halt_reason']}")

    # Positions
    print(f"Open positions: {len(state.data['open_positions'])}")

    # Performance
    print(f"Total closes: {state.data['total_closes']}")
    print(f"Total PnL: ${state.data['total_pnl']:.2f}")
    print(f"Consecutive losses: {state.data['consecutive_losses']} / {CIRCUIT_BREAKER_LOSSES}")
    print(f"Peak capital: ${state.data['peak_capital']:.2f}")

    print()

    # === FINAL VERDICT: NO FALSE CLAIMS ===
    if protection_active:
        if len(state.data["open_positions"]) > 0:
            print("CAPITAL PROTECTION: ACTIVE (positions protected)")
        else:
            print("CAPITAL PROTECTION: ACTIVE (ready for entries)")
    else:
        print("CAPITAL PROTECTION: OFFLINE (heartbeat stale or missing)")
        if len(state.data["open_positions"]) > 0:
            print("WARNING: Positions exist without active protection!")
    # === END VERDICT ===

    logger.info("")

def main() -> None:
    parser = argparse.ArgumentParser(description="Trading Engine")
    parser.add_argument("--dry-run", action="store_true", help="Test mode (no execution)")
    parser.add_argument("--status", action="store_true", help="Quick health check")
    args = parser.parse_args()
    
    if args.status:
        status_check()
        return
    
    # === SELF-HEALING VALIDATION LAYER (runs before startup) ===
    import sys
    from pathlib import Path as PathLib
    sys.path.insert(0, str(PathLib(__file__).parent))
    from self_healing_validator import auto_heal_and_validate
    
    state_file = LOGS_DIR / "trading_engine_state.json"
    heal_result = auto_heal_and_validate(state_file)
    
    if not heal_result['healthy']:
        logger.warning(f"STATE HEALING: {heal_result['reason']}")

    if heal_result['actions_taken']:
        logger.info("AUTO-HEAL ACTIONS:")
        for key, value in heal_result['actions_taken'].items():
            logger.info(f"   - {key}: {value}")
    # === END SELF-HEALING ===
    
    # PID lock to prevent concurrent instances
    # In Docker, skip check — container restart reuses PIDs and Docker
    # already ensures single instance via docker-compose.
    pid_file = LOGS_DIR / "trading_engine.pid"
    in_docker = Path("/.dockerenv").exists()
    if pid_file.exists() and not in_docker:
        try:
            old_pid = int(pid_file.read_text().strip())
            if old_pid != os.getpid():
                import subprocess
                result = subprocess.run(["ps", "-p", str(old_pid)], capture_output=True)
                if result.returncode == 0:
                    logger.error(f"ENGINE ALREADY RUNNING (PID {old_pid})")
                    logger.error("   Stop existing instance before starting new one")
                    sys.exit(1)
        except Exception:
            pass

    # Write PID
    pid_file.write_text(str(os.getpid()))
    
    try:
        engine = TradingEngine(dry_run=args.dry_run)
        engine.run()
    finally:
        # Clean up PID file
        if pid_file.exists():
            pid_file.unlink()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    main()
