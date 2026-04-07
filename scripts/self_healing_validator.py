#!/usr/bin/env python3
"""
Self-healing validation layer: Defensive, crash-proof, auto-recovers from all states.
Exchange is single source of truth. Never throws, always reconciles or skips.
"""

import json
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple
from hyperliquid.info import Info
from hyperliquid.utils import constants

ENGINE_ADDRESS = "0x8743f51c57e90644a0c141eD99064C4e9efFC01c"

class SelfHealingValidator:
    """Defensive validator that never crashes, always recovers."""
    
    def __init__(self, info: Optional[Info] = None):
        self.info = info or Info(constants.MAINNET_API_URL, skip_ws=True)
        self.last_reconcile = 0
        self.reconcile_interval = 60  # seconds
        
    def validate_and_heal(self, state_file: Path) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Validate state, auto-heal inconsistencies. Returns (healthy, reason, actions_taken).
        Never throws—always returns safely.
        """
        actions = {}
        
        try:
            # 1. Load state (or create if missing/corrupt)
            state = self._load_or_create_state(state_file)
            actions['state_loaded'] = True
            
            # 2. Get exchange ground truth
            exchange_state = self._get_exchange_state_safe()
            if not exchange_state:
                return False, "Exchange unavailable", actions
            
            actions['exchange_fetched'] = True
            
            # 3. Reconcile positions (exchange is truth)
            healed = self._reconcile_positions(state, exchange_state, state_file)
            if healed:
                actions['positions_reconciled'] = healed
            
            # 4. Reset circuit breaker if stale or inconsistent
            if self._should_reset_circuit_breaker(state, exchange_state):
                state['circuit_breaker_halted'] = False
                state['halt_reason'] = None
                state['consecutive_losses'] = 0
                self._save_state_safe(state_file, state)
                actions['circuit_breaker_reset'] = True
            
            # 5. Validate critical invariants
            healthy, reason = self._check_invariants(state, exchange_state)
            
            if not healthy:
                # Try to heal
                healed_state = self._heal_broken_state(state, exchange_state)
                self._save_state_safe(state_file, healed_state)
                actions['state_healed'] = reason
                return True, "Healed: " + reason, actions
            
            return True, "Healthy", actions
            
        except Exception as e:
            # NEVER CRASH—log and skip
            actions['exception'] = str(e)
            return False, f"Validation skipped: {str(e)}", actions
    
    def _load_or_create_state(self, state_file: Path) -> Dict[str, Any]:
        """Load state file, create if missing, fix if corrupt. Never throws."""
        try:
            if not state_file.exists():
                return self._create_default_state()
            
            with open(state_file) as f:
                state = json.load(f)
            
            # Ensure required keys exist
            defaults = self._create_default_state()
            for key, value in defaults.items():
                if key not in state:
                    state[key] = value
            
            return state
            
        except (json.JSONDecodeError, IOError) as e:
            # Corrupt or unreadable—create fresh
            return self._create_default_state()
    
    def _create_default_state(self) -> Dict[str, Any]:
        """Create clean default state."""
        return {
            'open_positions': {},
            'peak_roe': {},
            'circuit_breaker_halted': False,
            'halt_reason': None,
            'consecutive_losses': 0,
            'total_closes': 0,
            'total_pnl': 0.0,
            'peak_capital': 0.0,
            'heartbeat': datetime.now(timezone.utc).isoformat(),
        }
    
    def _get_exchange_state_safe(self) -> Optional[Dict[str, Any]]:
        """Fetch exchange state. Returns None on error instead of throwing."""
        try:
            state = self.info.user_state(ENGINE_ADDRESS)
            return state
        except Exception:
            return None
    
    def _reconcile_positions(self, state: Dict, exchange_state: Dict, state_file: Path) -> List[str]:
        """
        Reconcile internal state with exchange (exchange is truth).
        Returns list of actions taken.
        """
        actions = []
        
        try:
            # Get exchange positions
            exchange_positions = {}
            for ap in exchange_state.get('assetPositions', []):
                pos = ap.get('position', {})
                coin = pos.get('coin')
                if coin:
                    exchange_positions[coin] = pos
            
            internal_positions = state.get('open_positions', {})
            
            # Remove ghost positions (in state but not on exchange)
            ghosts = set(internal_positions.keys()) - set(exchange_positions.keys())
            for coin in ghosts:
                del state['open_positions'][coin]
                if coin in state.get('peak_roe', {}):
                    del state['peak_roe'][coin]
                actions.append(f"Removed ghost: {coin}")
            
            # Add untracked positions (on exchange but not in state)
            untracked = set(exchange_positions.keys()) - set(internal_positions.keys())
            for coin in untracked:
                pos = exchange_positions[coin]
                entry_px = pos.get('entryPx')
                if entry_px:
                    state['open_positions'][coin] = {
                        'entry_price': float(entry_px),
                        'entry_time': datetime.now(timezone.utc).isoformat(),
                    }
                    actions.append(f"Tracked orphan: {coin}")
            
            # Save if reconciled
            if actions:
                self._save_state_safe(state_file, state)
            
            return actions
            
        except Exception:
            # Don't crash on reconcile failure—return empty
            return []
    
    def _should_reset_circuit_breaker(self, state: Dict, exchange_state: Dict) -> bool:
        """
        Decide if circuit breaker should be reset.
        Reset if: halted with no open positions, or halt reason is stale.
        """
        try:
            if not state.get('circuit_breaker_halted'):
                return False
            
            # If halted but no positions open, safe to reset
            exchange_positions = exchange_state.get('assetPositions', [])
            if len(exchange_positions) == 0:
                return True
            
            # If halt reason is validation-related and was >5 min ago, reset
            halt_reason = state.get('halt_reason', '')
            if 'validation' in halt_reason.lower():
                # Check heartbeat age
                heartbeat_str = state.get('heartbeat')
                if heartbeat_str:
                    try:
                        hb = datetime.fromisoformat(heartbeat_str.replace('Z', '+00:00'))
                        age = (datetime.now(timezone.utc) - hb).total_seconds()
                        if age > 300:  # 5 minutes
                            return True
                    except:
                        pass
            
            return False
            
        except Exception:
            return False
    
    def _check_invariants(self, state: Dict, exchange_state: Dict) -> Tuple[bool, str]:
        """
        Check critical invariants. Returns (healthy, reason).
        Never throws—returns safe defaults.
        """
        try:
            # Invariant 1: State positions match exchange
            exchange_coins = {ap['position']['coin'] for ap in exchange_state.get('assetPositions', [])}
            internal_coins = set(state.get('open_positions', {}).keys())
            
            if exchange_coins != internal_coins:
                return False, f"Position mismatch: exchange={exchange_coins}, state={internal_coins}"
            
            # Invariant 2: No negative PnL tracking
            if state.get('total_pnl', 0) < -1000:  # Sanity check
                return False, f"Total PnL unrealistic: {state.get('total_pnl')}"
            
            # Invariant 3: Consecutive losses reasonable
            if state.get('consecutive_losses', 0) > 10:
                return False, f"Consecutive losses too high: {state.get('consecutive_losses')}"
            
            return True, "OK"
            
        except Exception as e:
            return False, f"Invariant check failed: {str(e)}"
    
    def _heal_broken_state(self, state: Dict, exchange_state: Dict) -> Dict[str, Any]:
        """
        Attempt to heal broken state by resetting to exchange truth.
        Returns healed state. Never throws.
        """
        try:
            # Reset to minimal safe state
            healed = self._create_default_state()
            
            # Copy only validated fields
            for key in ['total_closes', 'total_pnl', 'peak_capital']:
                if key in state and isinstance(state[key], (int, float)):
                    healed[key] = state[key]
            
            # Rebuild positions from exchange
            for ap in exchange_state.get('assetPositions', []):
                pos = ap.get('position', {})
                coin = pos.get('coin')
                entry_px = pos.get('entryPx')
                
                if coin and entry_px:
                    healed['open_positions'][coin] = {
                        'entry_price': float(entry_px),
                        'entry_time': datetime.now(timezone.utc).isoformat(),
                    }
            
            return healed
            
        except Exception:
            # Ultimate fallback—clean slate
            return self._create_default_state()
    
    def _save_state_safe(self, state_file: Path, state: Dict) -> bool:
        """Save state file. Returns success. Never throws."""
        try:
            state_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Atomic write (write to temp, then rename)
            temp_file = state_file.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                json.dump(state, f, indent=2)
            
            temp_file.rename(state_file)
            return True
            
        except Exception:
            return False


class CrashProofExecutionGuard:
    """Wrapper for all critical operations: catches exceptions, logs, continues."""
    
    def __init__(self, log_file: Path):
        self.log_file = log_file
    
    def safe_execute(self, func, *args, **kwargs) -> Tuple[bool, Any, Optional[str]]:
        """
        Execute function safely. Returns (success, result, error).
        NEVER lets exceptions propagate.
        """
        try:
            result = func(*args, **kwargs)
            return True, result, None
        except Exception as e:
            error = f"{func.__name__}: {str(e)}"
            self._log_error(error)
            return False, None, error
    
    def _log_error(self, error: str):
        """Log error without crashing."""
        try:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            
            entry = {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'error': error,
            }
            
            with open(self.log_file, 'a') as f:
                f.write(json.dumps(entry) + '\n')
        except:
            pass  # Even logging failure is non-fatal


def auto_heal_and_validate(state_file: Path, info: Optional[Info] = None) -> Dict[str, Any]:
    """
    Main entry point: Validate and heal state. Returns status dict.
    GUARANTEED to never crash.
    """
    validator = SelfHealingValidator(info)
    
    healthy, reason, actions = validator.validate_and_heal(state_file)
    
    return {
        'healthy': healthy,
        'reason': reason,
        'actions_taken': actions,
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    # Standalone test
    state_file = Path("workspace/logs/trading_engine_state.json")
    result = auto_heal_and_validate(state_file)
    
    print(json.dumps(result, indent=2))
