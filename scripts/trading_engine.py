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

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LOOP_INTERVAL_SEC = 1.0          # Main loop interval (1-sec protection checks)
SCAN_INTERVAL_SEC = 300          # Scanner runs every 5 minutes
STOP_LOSS_ROE = -0.07            # -7% ROE
TAKE_PROFIT_ROE = 0.10           # +10% ROE
TIMEOUT_HOURS = 8                # 8-hour max hold
TRAILING_STOP_ACTIVATE = 0.02    # Activate at +2% ROE
TRAILING_STOP_DISTANCE = 0.02    # Trail 2% behind peak
MAX_EXPOSURE_PER_TRADE = 20.0    # $20 per trade
CIRCUIT_BREAKER_LOSSES = 3       # Halt after 3 consecutive losses
DRAWDOWN_PCT = 0.15              # 15% from peak

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
        if STATE_FILE.exists():
            try:
                return json.loads(STATE_FILE.read_text())
            except Exception:
                pass
        
        return {
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
        
        return {
            "account_value": total_value,
            "spot_usd": spot_usd,
            "perp_value": perp_value,
            "positions": positions,
        }
    
    def market_close(self, coin: str) -> dict:
        """Close position via market order."""
        try:
            response = self.exchange.market_close(coin)
            return {"status": "ok", "response": response}
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
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
        from trade_logger import TradeLogger
        logger = TradeLogger()
        
        if action == "entry":
            logger.log_entry(
                signal=kwargs.get("signal", {}),
                size=kwargs.get("size", 0),
                entry_price=kwargs.get("entry_price", 0),
                trade_id=trade_id,
            )
        elif action == "exit":
            logger.log_exit(
                trade_id=trade_id,
                exit_price=kwargs.get("exit_price", 0),
                exit_reason=kwargs.get("exit_reason", "UNKNOWN"),
                # Note: TradeLogger calculates PnL internally
            )
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
        
        # Log to ledger
        trade_id = f"hl-{coin.lower()}-{state.data['open_positions'].get(coin, {}).get('entry_time', 'unknown')[:10]}"
        log_to_ledger(
            trade_id=trade_id,
            action="exit",
            exit_price=mid,
            exit_reason=triggers[0] if triggers else "MANUAL",
            # Note: TradeLogger calculates PnL internally, doesn't accept pnl_usd param
        )
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
        
        print("=" * 70)
        print(f"  TRADING ENGINE {'[DRY RUN]' if dry_run else '[LIVE]'}")
        print(f"  Started: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print("=" * 70)
        print()
        
        log_event({"event": "engine_started", "dry_run": dry_run, "pid": os.getpid()})
    
    def startup_reconciliation(self) -> None:
        """Reconcile state on startup."""
        print("🔍 RECONCILIATION")
        
        account = self.client.get_state()
        live_positions = account["positions"]
        tracked_coins = set(self.state.data["open_positions"].keys())
        live_coins = set(p["coin"] for p in live_positions)
        
        # Untracked positions
        untracked = live_coins - tracked_coins
        if untracked:
            print(f"  ⚠️  Untracked: {untracked}")
            for coin in untracked:
                pos = next(p for p in live_positions if p["coin"] == coin)
                self.state.track_position(coin, pos["entry_price"])
        
        # Stale positions
        stale = tracked_coins - live_coins
        if stale:
            print(f"  🧹 Cleaning stale: {stale}")
            for coin in stale:
                del self.state.data["open_positions"][coin]
            self.state.save()
        
        # Update peak capital
        self.state.update_peak_capital(account["account_value"])
        
        print(f"  ✅ Complete: {len(live_positions)} live positions")
        print()
    
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
            
            execute_exit(self.client, pos, triggers, self.state, force=force, dry_run=self.dry_run)
    
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
        
        self.last_scan = time.time()
    
    def run_scanner(self) -> list[dict]:
        """Run tiered scanner and return qualifying signals."""
        import urllib.request
        
        resp = json.loads(urllib.request.urlopen(
            urllib.request.Request('https://api.hyperliquid.xyz/info',
                data=json.dumps({'type': 'metaAndAssetCtxs'}).encode(),
                headers={'Content-Type': 'application/json'}),
            timeout=10
        ).read())
        
        signals = []
        
        # Tiered thresholds
        TIER1_MIN_FUNDING = 1.00
        TIER1_MIN_PREMIUM = -0.01
        TIER1_MIN_VOLUME = 1_000_000
        TIER1_POSITION_SIZE = 15.0
        
        TIER2_MIN_FUNDING = 0.75
        TIER2_MIN_PREMIUM = -0.005
        TIER2_MIN_VOLUME = 500_000
        TIER2_POSITION_SIZE = 8.0
        
        for u, ctx in zip(resp[0]['universe'], resp[1]):
            asset = u['name']
            premium = float(ctx.get('premium', 0) or 0)
            funding = float(ctx.get('funding', 0) or 0)
            volume = float(ctx.get('dayNtlVlm', 0) or 0)
            mid = float(ctx.get('midPx', 0) or 0)
            funding_annual = abs(funding) * 3 * 365
            
            # Skip if funding is positive
            if funding >= 0:
                continue
            
            # Tier 1
            if funding_annual >= TIER1_MIN_FUNDING and premium < TIER1_MIN_PREMIUM and volume >= TIER1_MIN_VOLUME:
                tier = 1
                position_size = TIER1_POSITION_SIZE
                score = 7.5
            # Tier 2
            elif funding_annual >= TIER2_MIN_FUNDING and premium < TIER2_MIN_PREMIUM and volume >= TIER2_MIN_VOLUME:
                tier = 2
                position_size = TIER2_POSITION_SIZE
                score = 5.5
            else:
                continue
            
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
        
        # Sort by tier, then score
        signals.sort(key=lambda x: (x['tier'], -x['score']))
        
        return signals
    
    def execute_entry(self, signal: dict) -> None:
        """Execute entry for a signal."""
        coin = signal["asset"]
        size_usd = signal["position_size_usd"]
        
        # === NON-BYPASSABLE RULE: NO PROTECTION → NO TRADING ===
        # Verify engine is protecting capital before allowing new exposure
        heartbeat_age = (time.time() - self.last_reconcile)  # Use reconcile time as proxy
        if heartbeat_age > 120:  # 2 minutes
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
        # === END PROTECTION CHECK ===
        
        # Pre-entry validation
        if coin in self.state.data["open_positions"]:
            log_event({"event": "entry_skipped", "coin": coin, "reason": "already_open"})
            return
        
        if len(self.state.data["open_positions"]) >= 5:
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
            leverage = 1  # 1x leverage for funding arb
            size_coins = (size_usd * leverage) / price
            
            # Execute market order
            response = self.client.exchange.market_open(coin, True, size_coins)  # True = long
            
            if response.get("status") != "ok":
                log_event({"event": "entry_rejected", "coin": coin, "response": response})
                return
            
            # Track position
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
                "event": "entry_executed",
                "coin": coin,
                "price": price,
                "size_usd": size_usd,
                "tier": signal["tier"],
            })
        
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
            print("=" * 70)
            print("❌ STARTUP BLOCKED: LEGACY TRADING SCRIPTS RUNNING")
            print("=" * 70)
            print()
            for proc in trading_procs:
                print(f"  {proc}")
            print()
            print("These scripts must not run. Engine is sole trading authority.")
            print()
            raise RuntimeError("Legacy trading scripts detected. Engine cannot start safely.")
        
        self.startup_reconciliation()
        
        print("🚀 ENGINE RUNNING")
        print()
        
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
                
                # === RUNTIME ASSERTION: STATE CONSISTENCY ===
                # Verify state file is valid and consistent
                if not STATE_FILE.exists():
                    raise RuntimeError("STATE FILE DELETED — Engine cannot operate without state")
                
                try:
                    test_state = json.loads(STATE_FILE.read_text())
                    assert "heartbeat" in test_state
                    assert "open_positions" in test_state
                except (json.JSONDecodeError, AssertionError) as e:
                    log_event({"event": "CRITICAL_STATE_CORRUPTED", "error": str(e), "action": "ABORT"})
                    raise RuntimeError(f"STATE FILE CORRUPTED — {e}")
                
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
            print()
            print("🛑 ENGINE SHUTDOWN")
            log_event({"event": "engine_stopped", "cycles": cycle})

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def status_check() -> None:
    """Quick health check."""
    print("=" * 70)
    print("  ENGINE STATUS CHECK")
    print("=" * 70)
    print()
    
    if not STATE_FILE.exists():
        print("❌ State file not found — engine never started")
        print("⚠️  CAPITAL PROTECTION: OFFLINE")
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
        hb_status = "✅ FRESH" if age_sec < 5 else "⚠️  STALE"
        print(f"Heartbeat: {hb_status} ({age_sec:.1f}s ago)")
        
        protection_active = (age_sec < 5)
    else:
        print("Heartbeat: ❌ NEVER")
        protection_active = False
    
    # Circuit breaker
    cb_status = "🔴 HALTED" if state.data["circuit_breaker_halted"] else "✅ ACTIVE"
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
            print("✅ CAPITAL PROTECTION: ACTIVE (positions protected)")
        else:
            print("✅ CAPITAL PROTECTION: ACTIVE (ready for entries)")
    else:
        print("🚨 CAPITAL PROTECTION: OFFLINE (heartbeat stale or missing)")
        if len(state.data["open_positions"]) > 0:
            print("⚠️  WARNING: Positions exist without active protection!")
    # === END VERDICT ===
    
    print()

def main() -> None:
    parser = argparse.ArgumentParser(description="Trading Engine")
    parser.add_argument("--dry-run", action="store_true", help="Test mode (no execution)")
    parser.add_argument("--status", action="store_true", help="Quick health check")
    args = parser.parse_args()
    
    if args.status:
        status_check()
        return
    
    engine = TradingEngine(dry_run=args.dry_run)
    engine.run()

if __name__ == "__main__":
    main()
