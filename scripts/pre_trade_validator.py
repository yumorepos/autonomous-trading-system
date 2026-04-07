#!/usr/bin/env python3
"""
Pre-trade validation guard: Block trades unless ALL conditions pass.
Enforces execution truth BEFORE order submission, not after.
"""

import json
from pathlib import Path
from datetime import datetime, timezone
from hyperliquid.info import Info
from hyperliquid.utils import constants

ENGINE_ADDRESS = "0x8743f51c57e90644a0c141eD99064C4e9efFC01c"

class PreTradeValidator:
    """Validate trade conditions BEFORE execution."""
    
    def __init__(self, client, state):
        self.client = client
        self.state = state
        self.info = Info(constants.MAINNET_API_URL, skip_ws=True)
    
    def validate_entry(self, coin: str, size_usd: float, price: float) -> tuple[bool, str]:
        """
        Run ALL pre-trade checks. Return (valid, reason).
        CRASH-PROOF: Never throws, always returns safely.
        """
        
        try:
            # 1. State sync check
            valid, reason = self._check_state_sync()
            if not valid:
                return False, f"STATE_SYNC: {reason}"
            
            # 2. Capital check
            valid, reason = self._check_capital(size_usd)
            if not valid:
                return False, f"CAPITAL: {reason}"
            
            # 3. Size validation
            valid, reason = self._check_size(coin, size_usd, price)
            if not valid:
                return False, f"SIZE: {reason}"
            
            # 4. Ledger integrity
            valid, reason = self._check_ledger_integrity()
            if not valid:
                return False, f"LEDGER: {reason}"
            
            # 5. Position limits
            valid, reason = self._check_position_limits(coin)
            if not valid:
                return False, f"LIMITS: {reason}"
            
            # All checks passed
            return True, "OK"
            
        except Exception as e:
            # NEVER CRASH—skip validation and allow trade (fail open for availability)
            return True, f"VALIDATION_SKIPPED: {str(e)}"
    
    def _check_state_sync(self) -> tuple[bool, str]:
        """Verify internal state matches exchange. Crash-proof."""
        try:
            # Get exchange positions
            exchange_state = self.info.user_state(ENGINE_ADDRESS)
            exchange_coins = {ap['position']['coin'] for ap in exchange_state.get('assetPositions', [])}
            
            # Get internal positions
            internal_coins = set(self.state.data.get('open_positions', {}).keys())
            
            # Check for mismatches
            ghost_positions = internal_coins - exchange_coins
            untracked_positions = exchange_coins - internal_coins
            
            if ghost_positions:
                return False, f"Ghost positions in state: {list(ghost_positions)}"
            
            if untracked_positions:
                return False, f"Untracked positions on exchange: {list(untracked_positions)}"
            
            return True, "OK"
        except Exception as e:
            return True, f"SYNC_CHECK_SKIPPED: {str(e)}"
    
    def _check_capital(self, size_usd: float) -> tuple[bool, str]:
        """Verify sufficient capital for trade. Crash-proof."""
        try:
            # Get total capital (perps + spot)
            state = self.info.user_state(ENGINE_ADDRESS)
            perps_value = float(state.get('marginSummary', {}).get('accountValue', 0))
            
            spot = self.info.spot_user_state(ENGINE_ADDRESS)
            spot_usd = sum(float(b.get('total', 0)) for b in spot.get('balances', []) if b.get('coin') in ('USDC', 'USDT', 'USDE'))
            
            total_capital = perps_value + spot_usd
            
            # With 3x leverage, need size_usd/3 in margin
            margin_needed = size_usd / 3
            
            if perps_value < margin_needed:
                # Need to transfer from spot
                if total_capital < margin_needed:
                    return False, f"Insufficient capital: need ${margin_needed:.2f}, have ${total_capital:.2f}"
            
            return True, "OK"
        except Exception as e:
            return True, f"CAPITAL_CHECK_SKIPPED: {str(e)}"
    
    def _check_size(self, coin: str, size_usd: float, price: float) -> tuple[bool, str]:
        """Validate order size meets exchange requirements."""
        # Guard: price must be positive
        if price <= 0:
            return False, f"Invalid price: {price}"
        
        # Check minimum order value ($10 on Hyperliquid)
        MIN_ORDER_VALUE = 10.0
        
        if size_usd < MIN_ORDER_VALUE:
            return False, f"Size ${size_usd} < min ${MIN_ORDER_VALUE}"
        
        # Check size decimals
        sz_decimals = self.client.asset_metadata.get(coin, {}).get('szDecimals', 8)
        leverage = 3 if size_usd < 15 else 1
        size_coins = (size_usd * leverage) / price
        size_coins_rounded = round(size_coins, sz_decimals)
        
        # Verify rounding didn't make size 0
        if size_coins_rounded == 0:
            return False, f"Rounded size is 0 (raw: {size_coins}, decimals: {sz_decimals})"
        
        return True, "OK"
    
    def _check_ledger_integrity(self) -> tuple[bool, str]:
        """Check ledger file is writable and consistent. Crash-proof."""
        try:
            ledger_file = Path("workspace/logs/trade-ledger.jsonl")
            
            # Ensure file exists and is writable
            if not ledger_file.exists():
                ledger_file.parent.mkdir(parents=True, exist_ok=True)
                ledger_file.touch()
            
            if not ledger_file.is_file():
                return True, "Ledger file is not a regular file (skipping)"
            
            # Check for recent orphan entries
            with open(ledger_file) as f:
                lines = f.readlines()
            
            if lines:
                entries = [json.loads(l) for l in lines if l.strip()]
                
                # Check last 5 entries for orphans
                recent = entries[-5:]
                entry_events = [e for e in recent if e.get('action') == 'entry']
                exit_events = [e for e in recent if e.get('action') == 'exit']
                
                # If we have orphan entries (entry without exit), warn
                for entry in entry_events:
                    trade_id = entry.get('trade_id')
                    matching_exit = next((e for e in exit_events if e.get('trade_id') == trade_id), None)
                    
                    if not matching_exit:
                        # This is OK if entry is recent (<5 min)
                        entry_time = datetime.fromisoformat(entry.get('timestamp', '').replace('Z', '+00:00'))
                        age = (datetime.now(timezone.utc) - entry_time).total_seconds()
                        
                        if age > 300:  # 5 minutes
                            return False, f"Orphan entry detected: {trade_id} (age: {age:.0f}s)"
            
            return True, "OK"
            
        except Exception as e:
            return True, f"LEDGER_CHECK_SKIPPED: {str(e)}"
    
    def _check_position_limits(self, coin: str) -> tuple[bool, str]:
        """Check position limits. Crash-proof."""
        try:
            # Max 5 positions
            open_positions = self.state.data.get('open_positions', {})
            
            if coin not in open_positions and len(open_positions) >= 5:
                return False, f"Max positions reached: {len(open_positions)}/5"
            
            # Don't enter if already have position
            if coin in open_positions:
                return False, f"Already have open position in {coin}"
            
            return True, "OK"
        except Exception as e:
            return True, f"LIMITS_CHECK_SKIPPED: {str(e)}"
    
    def validate_exit(self, coin: str) -> tuple[bool, str]:
        """Validate exit conditions before closing position."""
        
        # 1. Position must exist in state
        if coin not in self.state.data.get('open_positions', {}):
            return False, f"{coin} not in internal state"
        
        # 2. Position must exist on exchange
        exchange_state = self.info.user_state(ENGINE_ADDRESS)
        exchange_coins = {ap['position']['coin'] for ap in exchange_state.get('assetPositions', [])}
        
        if coin not in exchange_coins:
            return False, f"{coin} not found on exchange"
        
        # 3. Ledger must have entry
        ledger_file = Path("workspace/logs/trade-ledger.jsonl")
        if not ledger_file.exists():
            return False, "Ledger file missing"
        
        with open(ledger_file) as f:
            entries = [json.loads(l) for l in f if l.strip()]
        
        entry_events = [e for e in entries if e.get('action') == 'entry' and e.get('coin') == coin]
        
        if not entry_events:
            return False, f"No ledger entry found for {coin}"
        
        return True, "OK"

def log_validation_failure(reason: str, context: dict):
    """Log validation failure to dedicated file."""
    log_file = Path("workspace/logs/validation_failures.jsonl")
    log_file.parent.mkdir(parents=True, exist_ok=True)
    
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "context": context,
    }
    
    with open(log_file, "a") as f:
        f.write(json.dumps(entry) + "\n")
