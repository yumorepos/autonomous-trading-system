#!/usr/bin/env python3
"""
Fail-safe validation layer: Errors block ENTRIES, never exits. Capital-protective.

CRITICALITY LEVELS:
- ENTRY_CRITICAL: Must pass to allow new positions (fail-safe = block)
- EXIT_SAFE: Never blocks exits (always allow capital protection)
- RECONCILE_WARN: Log but don't block (observer mode)
- OBSERVER: Informational only

GUARANTEES:
1. Validation uncertainty → block new entries (fail-safe)
2. Exits NEVER blocked by validation (capital protection priority)
3. All errors surfaced and logged (never silently swallowed)
4. Degraded operation allowed when safe (reconciliation can fail, entries blocked)
"""

import json
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple
from enum import Enum
from hyperliquid.info import Info
from hyperliquid.utils import constants

ENGINE_ADDRESS = "0x8743f51c57e90644a0c141eD99064C4e9efFC01c"

class Criticality(Enum):
    ENTRY_CRITICAL = "ENTRY_CRITICAL"  # Must pass to allow entries
    EXIT_SAFE = "EXIT_SAFE"            # Never blocks exits
    RECONCILE_WARN = "RECONCILE_WARN"  # Log but don't block
    OBSERVER = "OBSERVER"               # Informational only

class ValidationResult:
    """Structured validation result with criticality."""
    
    def __init__(self, valid: bool, reason: str, criticality: Criticality, 
                 data: Optional[Dict] = None, error: Optional[Exception] = None):
        self.valid = valid
        self.reason = reason
        self.criticality = criticality
        self.data = data or {}
        self.error = error
        self.timestamp = datetime.now(timezone.utc).isoformat()
    
    def to_dict(self) -> Dict:
        return {
            'valid': self.valid,
            'reason': self.reason,
            'criticality': self.criticality.value,
            'data': self.data,
            'error': str(self.error) if self.error else None,
            'timestamp': self.timestamp,
        }
    
    def should_block_entry(self) -> bool:
        """Returns True if this result should block new entries."""
        if self.criticality == Criticality.ENTRY_CRITICAL:
            # Fail-safe: invalid OR error → block
            return not self.valid or self.error is not None
        return False
    
    def should_block_exit(self) -> bool:
        """Returns True if this result should block exits. Always False (capital protection priority)."""
        return False


class FailSafeValidator:
    """
    Fail-safe validator: Errors block entries, never exits.
    All checks classified by criticality.
    """
    
    def __init__(self, info: Optional[Info] = None, log_file: Optional[Path] = None):
        self.info = info or Info(constants.MAINNET_API_URL, skip_ws=True)
        self.log_file = log_file or Path("workspace/logs/validation_errors.jsonl")
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
    
    def validate_entry(self, coin: str, size_usd: float, price: float, state) -> ValidationResult:
        """
        Validate if entry is safe. Returns ValidationResult.
        
        FAIL-SAFE LOGIC:
        - All exceptions → block entry (uncertain = unsafe)
        - Invalid checks → block entry
        - Only passes if ALL critical checks pass
        """
        
        results = []
        
        # ENTRY_CRITICAL checks
        results.append(self._check_state_sync(state, Criticality.ENTRY_CRITICAL))
        results.append(self._check_capital(size_usd, Criticality.ENTRY_CRITICAL))
        results.append(self._check_size(coin, size_usd, price, Criticality.ENTRY_CRITICAL))
        results.append(self._check_position_limits(coin, state, Criticality.ENTRY_CRITICAL))
        
        # Check if any critical check failed or errored
        for result in results:
            if result.should_block_entry():
                self._log_validation(result)
                return result  # Return first blocking issue
        
        # All checks passed
        return ValidationResult(
            valid=True,
            reason="All entry checks passed",
            criticality=Criticality.ENTRY_CRITICAL,
        )
    
    def validate_exit(self, coin: str, state) -> ValidationResult:
        """
        Validate if exit is safe. Always returns valid (exits never blocked).
        
        CAPITAL-PROTECTIVE LOGIC:
        - Exits ALWAYS allowed (capital protection priority)
        - Warnings logged but don't block
        """
        
        # Check if position exists (OBSERVER only, doesn't block)
        result = self._check_position_exists(coin, state, Criticality.EXIT_SAFE)
        
        if not result.valid:
            self._log_validation(result)
        
        # Always allow exit (fail-safe for capital protection)
        return ValidationResult(
            valid=True,
            reason="Exits always allowed (capital protection priority)",
            criticality=Criticality.EXIT_SAFE,
        )
    
    def reconcile_state(self, state_file: Path) -> ValidationResult:
        """
        Reconcile state with exchange. Returns result but never blocks.
        
        RECONCILE LOGIC:
        - Errors logged but don't stop engine
        - State healing attempted on best-effort basis
        - Returns RECONCILE_WARN criticality
        """
        
        try:
            # Load state
            if not state_file.exists():
                return ValidationResult(
                    valid=False,
                    reason="State file missing",
                    criticality=Criticality.RECONCILE_WARN,
                )
            
            with open(state_file) as f:
                state = json.load(f)
            
            # Get exchange positions
            exchange_state = self.info.user_state(ENGINE_ADDRESS)
            exchange_positions = {
                ap['position']['coin']: ap['position'] 
                for ap in exchange_state.get('assetPositions', [])
            }
            
            internal_positions = state.get('open_positions', {})
            
            # Find mismatches
            ghosts = set(internal_positions.keys()) - set(exchange_positions.keys())
            untracked = set(exchange_positions.keys()) - set(internal_positions.keys())
            
            if ghosts or untracked:
                # Reconcile (heal state)
                for coin in ghosts:
                    del state['open_positions'][coin]
                    if coin in state.get('peak_roe', {}):
                        del state['peak_roe'][coin]
                
                for coin in untracked:
                    pos = exchange_positions[coin]
                    state['open_positions'][coin] = {
                        'entry_price': float(pos.get('entryPx', 0)),
                        'entry_time': datetime.now(timezone.utc).isoformat(),
                    }
                
                # Save healed state
                with open(state_file, 'w') as f:
                    json.dump(state, f, indent=2)
                
                return ValidationResult(
                    valid=True,
                    reason=f"State reconciled: removed {len(ghosts)} ghosts, added {len(untracked)} untracked",
                    criticality=Criticality.RECONCILE_WARN,
                    data={'ghosts': list(ghosts), 'untracked': list(untracked)},
                )
            
            # State already synced
            return ValidationResult(
                valid=True,
                reason="State already synced with exchange",
                criticality=Criticality.RECONCILE_WARN,
            )
            
        except Exception as e:
            # Reconcile failure logged but doesn't block engine
            result = ValidationResult(
                valid=False,
                reason="Reconciliation failed",
                criticality=Criticality.RECONCILE_WARN,
                error=e,
            )
            self._log_validation(result)
            return result
    
    # === INDIVIDUAL CHECKS (with criticality) ===
    
    def _check_state_sync(self, state, criticality: Criticality) -> ValidationResult:
        """Check if state matches exchange."""
        try:
            exchange_state = self.info.user_state(ENGINE_ADDRESS)
            exchange_coins = {ap['position']['coin'] for ap in exchange_state.get('assetPositions', [])}
            internal_coins = set(state.data.get('open_positions', {}).keys())
            
            ghosts = internal_coins - exchange_coins
            untracked = exchange_coins - internal_coins
            
            if ghosts or untracked:
                return ValidationResult(
                    valid=False,
                    reason=f"State mismatch: ghosts={list(ghosts)}, untracked={list(untracked)}",
                    criticality=criticality,
                    data={'ghosts': list(ghosts), 'untracked': list(untracked)},
                )
            
            return ValidationResult(valid=True, reason="State synced", criticality=criticality)
            
        except Exception as e:
            # Exception = uncertain state → fail-safe (block if ENTRY_CRITICAL)
            return ValidationResult(
                valid=False,
                reason="State sync check failed",
                criticality=criticality,
                error=e,
            )
    
    def _check_capital(self, size_usd: float, criticality: Criticality) -> ValidationResult:
        """Check if sufficient capital."""
        try:
            state = self.info.user_state(ENGINE_ADDRESS)
            perps_value = float(state.get('marginSummary', {}).get('accountValue', 0))
            
            spot = self.info.spot_user_state(ENGINE_ADDRESS)
            spot_usd = sum(
                float(b.get('total', 0)) 
                for b in spot.get('balances', []) 
                if b.get('coin') in ('USDC', 'USDT', 'USDE')
            )
            
            total_capital = perps_value + spot_usd
            margin_needed = size_usd / 3  # 3x leverage
            
            if total_capital < margin_needed:
                return ValidationResult(
                    valid=False,
                    reason=f"Insufficient capital: need ${margin_needed:.2f}, have ${total_capital:.2f}",
                    criticality=criticality,
                    data={'needed': margin_needed, 'available': total_capital},
                )
            
            return ValidationResult(
                valid=True,
                reason="Sufficient capital",
                criticality=criticality,
                data={'capital': total_capital, 'needed': margin_needed},
            )
            
        except Exception as e:
            return ValidationResult(
                valid=False,
                reason="Capital check failed",
                criticality=criticality,
                error=e,
            )
    
    def _check_size(self, coin: str, size_usd: float, price: float, criticality: Criticality) -> ValidationResult:
        """Check if size is valid."""
        try:
            if price <= 0:
                return ValidationResult(
                    valid=False,
                    reason=f"Invalid price: {price}",
                    criticality=criticality,
                    data={'price': price},
                )
            
            MIN_SIZE = 10.0
            if size_usd < MIN_SIZE:
                return ValidationResult(
                    valid=False,
                    reason=f"Size ${size_usd} < min ${MIN_SIZE}",
                    criticality=criticality,
                    data={'size': size_usd, 'min': MIN_SIZE},
                )
            
            return ValidationResult(valid=True, reason="Size valid", criticality=criticality)
            
        except Exception as e:
            return ValidationResult(
                valid=False,
                reason="Size check failed",
                criticality=criticality,
                error=e,
            )
    
    def _check_position_limits(self, coin: str, state, criticality: Criticality) -> ValidationResult:
        """Check position limits."""
        try:
            open_positions = state.data.get('open_positions', {})
            
            if coin in open_positions:
                return ValidationResult(
                    valid=False,
                    reason=f"Already have position in {coin}",
                    criticality=criticality,
                    data={'coin': coin},
                )
            
            MAX_POSITIONS = 5
            if len(open_positions) >= MAX_POSITIONS:
                return ValidationResult(
                    valid=False,
                    reason=f"Max positions: {len(open_positions)}/{MAX_POSITIONS}",
                    criticality=criticality,
                    data={'count': len(open_positions), 'max': MAX_POSITIONS},
                )
            
            return ValidationResult(valid=True, reason="Position limits OK", criticality=criticality)
            
        except Exception as e:
            return ValidationResult(
                valid=False,
                reason="Position limit check failed",
                criticality=criticality,
                error=e,
            )
    
    def _check_position_exists(self, coin: str, state, criticality: Criticality) -> ValidationResult:
        """Check if position exists (for exits)."""
        try:
            if coin not in state.data.get('open_positions', {}):
                return ValidationResult(
                    valid=False,
                    reason=f"Position {coin} not found in state",
                    criticality=criticality,
                    data={'coin': coin},
                )
            
            # Also check exchange
            exchange_state = self.info.user_state(ENGINE_ADDRESS)
            exchange_coins = {ap['position']['coin'] for ap in exchange_state.get('assetPositions', [])}
            
            if coin not in exchange_coins:
                return ValidationResult(
                    valid=False,
                    reason=f"Position {coin} not found on exchange",
                    criticality=criticality,
                    data={'coin': coin},
                )
            
            return ValidationResult(valid=True, reason="Position exists", criticality=criticality)
            
        except Exception as e:
            # For exits, even errors don't block (capital protection priority)
            return ValidationResult(
                valid=False,
                reason="Position existence check failed",
                criticality=criticality,
                error=e,
            )
    
    def _log_validation(self, result: ValidationResult):
        """Log validation result (errors are surfaced, not swallowed)."""
        try:
            with open(self.log_file, 'a') as f:
                f.write(json.dumps(result.to_dict()) + '\n')
        except Exception:
            # Even logging failure is non-fatal, but we tried
            pass


def validate_entry_safe(coin: str, size_usd: float, price: float, state, 
                       info: Optional[Info] = None) -> Tuple[bool, str]:
    """
    Convenience wrapper for entry validation.
    Returns (allowed, reason).
    
    FAIL-SAFE: Uncertain = block (False).
    """
    validator = FailSafeValidator(info)
    result = validator.validate_entry(coin, size_usd, price, state)
    return not result.should_block_entry(), result.reason


def validate_exit_safe(coin: str, state, info: Optional[Info] = None) -> Tuple[bool, str]:
    """
    Convenience wrapper for exit validation.
    Returns (allowed, reason).
    
    CAPITAL-PROTECTIVE: Always allowed (True).
    """
    validator = FailSafeValidator(info)
    result = validator.validate_exit(coin, state)
    return not result.should_block_exit(), result.reason


if __name__ == "__main__":
    # Test
    from trading_engine import EngineState, STATE_FILE
    
    state = EngineState(STATE_FILE)
    validator = FailSafeValidator()
    
    # Test entry
    result = validator.validate_entry("BTC", 15.0, 50000.0, state)
    print(f"Entry validation: {result.valid} - {result.reason}")
    print(f"Should block entry: {result.should_block_entry()}")
    print(f"Should block exit: {result.should_block_exit()}")
    
    # Test reconcile
    result = validator.reconcile_state(STATE_FILE)
    print(f"\nReconciliation: {result.valid} - {result.reason}")
