#!/usr/bin/env python3
"""
Real Exit Validation Monitor
Hardened version - works with actual position schema
Captures complete lifecycle proof for every real close
"""

import json
import sys
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.runtime import WORKSPACE_ROOT as WORKSPACE, LOGS_DIR, DATA_DIR
from models.position_state import get_open_positions
from models.trade_schema import validate_trade_record
from utils.json_utils import safe_read_json, safe_read_jsonl
from utils.system_health import SystemHealthManager
PAPER_TRADES = LOGS_DIR / "phase1-paper-trades.jsonl"
EXIT_PROOF_LOG = LOGS_DIR / "exit-proof.jsonl"
EXIT_MONITOR_LOG = LOGS_DIR / "exit-monitor.log"
EXIT_MONITOR_REPORT = WORKSPACE / "EXIT_MONITOR_REPORT.md"

# Exit conditions
TAKE_PROFIT_PCT = 10.0
STOP_LOSS_PCT = -10.0
TIME_LIMIT_HOURS = 24.0


class ExitMonitor:
    """Monitor open positions for real exits - production-hardened"""
    
    def __init__(self):
        self.health_manager = SystemHealthManager()
        self.open_positions = self.load_open_positions()
        self.monitoring_checkpoints = []
        
    def log(self, message: str, level: str = "INFO"):
        """Log to file"""
        timestamp = datetime.now(timezone.utc).isoformat()
        log_entry = f"[{timestamp}] [{level}] {message}\n"
        
        with open(EXIT_MONITOR_LOG, 'a') as f:
            f.write(log_entry)
        
        print(f"[{level}] {message}")
    
    def load_open_positions(self) -> List[Dict]:
        """Load current open positions from authoritative position-state.json only."""
        try:
            positions = []
            for position in get_open_positions(LOGS_DIR / "position-state.json"):
                if not validate_trade_record(position, context=f"exit-monitor[{position.get('trade_id', 'unknown')}]"):
                    continue
                positions.append(position)
        except Exception as e:
            self.log(f"Failed to load positions: {e}", "ERROR")
            self.health_manager.record_incident(
                incident_type='exit_monitor_failure',
                severity='HIGH',
                source='exit-monitor',
                message=f"Failed to load open positions: {e}",
                affected_system='position-monitoring',
                affected_components=['exit_monitor', 'position_state'],
                metadata={'error': str(e)},
            )
            return []

        self.log(f"Loaded {len(positions)} open positions")
        return positions
    
    def get_current_price(self, asset: str) -> Optional[float]:
        """Get current price from Hyperliquid API"""
        try:
            url = "https://api.hyperliquid.xyz/info"
            r = requests.post(url, json={'type': 'allMids'}, timeout=5)
            
            if r.status_code != 200:
                self.log(f"API returned status {r.status_code}", "ERROR")
                self.health_manager.record_incident(
                    incident_type='exit_monitor_api_instability',
                    severity='MEDIUM',
                    source='exit-monitor',
                    message=f"Price lookup failed for {asset}: HTTP {r.status_code}",
                    affected_system='position-monitoring',
                    affected_components=['exit_monitor', 'hyperliquid_api'],
                    metadata={'asset': asset, 'status_code': r.status_code},
                )
                return None
            
            mids = r.json()
            
            if asset not in mids:
                self.log(f"Asset {asset} not in API response", "ERROR")
                self.health_manager.record_incident(
                    incident_type='exit_monitor_state_mismatch',
                    severity='HIGH',
                    source='exit-monitor',
                    message=f"Asset {asset} missing from Hyperliquid mids response",
                    affected_trade=asset,
                    affected_system='position-monitoring',
                    affected_components=['exit_monitor', 'hyperliquid_api'],
                    metadata={'asset': asset},
                )
                return None
            
            price = float(mids[asset])
            return price
            
        except requests.Timeout:
            self.log(f"API timeout for {asset}", "ERROR")
            self.health_manager.record_incident(
                incident_type='exit_monitor_api_instability',
                severity='MEDIUM',
                source='exit-monitor',
                message=f"Price lookup timeout for {asset}",
                affected_trade=asset,
                affected_system='position-monitoring',
                affected_components=['exit_monitor', 'hyperliquid_api'],
                metadata={'asset': asset},
            )
            return None
        except Exception as e:
            self.log(f"Failed to get price for {asset}: {e}", "ERROR")
            self.health_manager.record_incident(
                incident_type='exit_monitor_failure',
                severity='HIGH',
                source='exit-monitor',
                message=f"Price lookup failed for {asset}: {e}",
                affected_trade=asset,
                affected_system='position-monitoring',
                affected_components=['exit_monitor', 'hyperliquid_api'],
                metadata={'asset': asset, 'error': str(e)},
            )
            return None
    
    def calculate_pnl(self, entry_price: float, current_price: float, position_size: float, direction: str) -> Tuple[float, float]:
        """Calculate P&L in USD and percentage"""
        if direction == 'LONG':
            pnl_usd = (current_price - entry_price) * position_size
        else:  # SHORT
            pnl_usd = (entry_price - current_price) * position_size
        
        entry_value = entry_price * position_size
        pnl_pct = (pnl_usd / entry_value) * 100 if entry_value > 0 else 0
        
        return pnl_usd, pnl_pct
    
    def check_exit_conditions(self, position: Dict, current_price: float) -> Tuple[bool, Optional[str]]:
        """Check if position should exit - returns (should_exit, reason)"""
        entry_price = position['entry_price']
        direction = position.get('side', position.get('direction', 'LONG'))
        
        # Calculate P&L
        _, pnl_pct = self.calculate_pnl(entry_price, current_price, position['position_size'], direction)
        
        # Check take profit
        if pnl_pct >= TAKE_PROFIT_PCT:
            return True, 'take_profit'
        
        # Check stop loss
        if pnl_pct <= STOP_LOSS_PCT:
            return True, 'stop_loss'
        
        # Check time limit
        entry_time = datetime.fromisoformat(position['entry_timestamp'])
        now = datetime.now(timezone.utc)
        age_hours = (now - entry_time).total_seconds() / 3600
        
        if age_hours >= TIME_LIMIT_HOURS:
            return True, 'time_limit'
        
        return False, None
    
    def create_monitoring_checkpoint(self, position: Dict, current_price: float, pnl_pct: float) -> Dict:
        """Create monitoring checkpoint for lifecycle proof"""
        checkpoint = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'asset': position['symbol'],
            'entry_price': position['entry_price'],
            'current_price': current_price,
            'pnl_pct': pnl_pct,
            'status': 'OPEN',
            'age_hours': (datetime.now(timezone.utc) - datetime.fromisoformat(position['entry_timestamp'])).total_seconds() / 3600
        }
        
        return checkpoint
    
    def capture_exit_proof(self, position: Dict, exit_reason: str, exit_price: float) -> Dict:
        """Capture complete lifecycle proof for a real closed trade"""
        entry_time = datetime.fromisoformat(position['entry_timestamp'])
        exit_time = datetime.now(timezone.utc)
        
        asset = position['symbol']
        entry_price = position['entry_price']
        position_size = position['position_size']
        direction = position.get('side', position.get('direction', 'LONG'))
        
        # Calculate final P&L
        pnl_usd, pnl_pct = self.calculate_pnl(entry_price, exit_price, position_size, direction)
        
        hold_duration_seconds = (exit_time - entry_time).total_seconds()
        
        # Generate trade ID if not present
        trade_id = position.get('trade_id') or f"HL_{asset}_{entry_time.strftime('%Y%m%d_%H%M%S')}"
        
        # Build complete lifecycle proof
        proof = {
            'proof_captured_at': exit_time.isoformat(),
            'trade_id': trade_id,
            
            # 1. Entry proof
            'entry': {
                'timestamp': position['entry_timestamp'],
                'asset': asset,
                'side': direction,
                'entry_price': entry_price,
                'position_size': position_size,
                'entry_value_usd': entry_price * position_size,
                'source': position.get('signal', {}).get('source', 'unknown'),
                'signal_type': position.get('signal', {}).get('signal_type', position.get('strategy', 'unknown')),
                'ev_score': position.get('signal', {}).get('ev_score', 0),
                'conviction': position.get('signal', {}).get('conviction', 'UNKNOWN')
            },
            
            # 2. Monitoring history
            'monitoring': {
                'checkpoints_recorded': len([c for c in self.monitoring_checkpoints if c['asset'] == asset]),
                'hold_duration_seconds': hold_duration_seconds,
                'hold_duration_hours': hold_duration_seconds / 3600,
                'status_throughout': 'OPEN'
            },
            
            # 3. Exit trigger
            'exit_trigger': {
                'reason': exit_reason,
                'triggered_at': exit_time.isoformat(),
                'exit_price': exit_price,
                'price_verified_source': 'Hyperliquid API',
                'price_fetch_successful': True
            },
            
            # 4. Exit execution result
            'execution': {
                'executed_at': exit_time.isoformat(),
                'execution_method': 'paper_trading',
                'execution_successful': True,
                'slippage_pct': 0.0  # Paper trading has no slippage
            },
            
            # 5. Realized P&L
            'realized_pnl': {
                'pnl_usd': pnl_usd,
                'pnl_pct': pnl_pct,
                'entry_value': entry_price * position_size,
                'exit_value': exit_price * position_size,
                'winner': pnl_usd > 0,
                'return_on_capital': pnl_pct
            },
            
            # 6. Source log/state files
            'source_files': {
                'positions_log': str(PAPER_TRADES),
                'exit_proof_log': str(EXIT_PROOF_LOG),
                'monitoring_log': str(EXIT_MONITOR_LOG),
                'position_line_number': 'unknown'  # Would need to track this
            },
            
            # 7. Readiness validator impact
            'validator_impact': {
                'contributes_to_closed_trades': True,
                'closed_trades_required': 100,
                'closed_trades_after_this': self.count_closed_trades() + 1,
                'progress_toward_validation': ((self.count_closed_trades() + 1) / 100) * 100
            }
        }
        
        # Save proof to dedicated log
        with open(EXIT_PROOF_LOG, 'a') as f:
            f.write(json.dumps(proof) + '\n')
        
        self.log(f"Exit proof captured for {trade_id}: {exit_reason} @ ${exit_price:.4f}, P&L ${pnl_usd:+.2f} ({pnl_pct:+.1f}%)", "INFO")
        
        return proof
    
    def count_closed_trades(self) -> int:
        """Count total closed trades from proof log"""
        if not EXIT_PROOF_LOG.exists():
            return 0
        
        count = 0
        with open(EXIT_PROOF_LOG) as f:
            for line in f:
                if line.strip():
                    count += 1
        
        return count
    
    def monitor(self):
        """Monitor all open positions for exit conditions"""
        print("="*80)
        print("REAL EXIT VALIDATION MONITOR")
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S EDT')}")
        print("="*80)
        print()
        
        if not self.open_positions:
            self.log("No open positions to monitor", "INFO")
            print("⚠️  No open positions to monitor")
            return
        
        self.log(f"Monitoring {len(self.open_positions)} open positions", "INFO")
        print(f"Monitoring {len(self.open_positions)} open positions...")
        print()
        
        exits_captured = 0
        
        for position in self.open_positions:
            asset = position['symbol']
            entry_price = position['entry_price']
            direction = position.get('side', position.get('direction', 'LONG'))
            
            # Get current price
            current_price = self.get_current_price(asset)
            
            if current_price is None:
                print(f"⚠️  {asset}: Failed to fetch price, skipping")
                continue
            
            # Calculate P&L
            pnl_usd, pnl_pct = self.calculate_pnl(entry_price, current_price, position['position_size'], direction)
            
            # Create monitoring checkpoint
            checkpoint = self.create_monitoring_checkpoint(position, current_price, pnl_pct)
            self.monitoring_checkpoints.append(checkpoint)
            
            # Check exit conditions
            should_exit, exit_reason = self.check_exit_conditions(position, current_price)
            
            entry_time = datetime.fromisoformat(position['entry_timestamp'])
            age_hours = (datetime.now(timezone.utc) - entry_time).total_seconds() / 3600
            
            if should_exit:
                print(f"🔴 EXIT TRIGGERED: {asset}")
                print(f"   Reason: {exit_reason}")
                print(f"   Entry: ${entry_price:.4f}")
                print(f"   Exit: ${current_price:.4f}")
                print(f"   P&L: ${pnl_usd:+.2f} ({pnl_pct:+.1f}%)")
                print(f"   Hold: {age_hours:.1f}h")
                print()
                print("   📝 Capturing complete lifecycle proof...")
                
                # Capture proof
                proof = self.capture_exit_proof(position, exit_reason, current_price)
                
                print(f"   ✅ Proof saved to {EXIT_PROOF_LOG}")
                print()
                
                exits_captured += 1
            else:
                # Show monitoring status
                status_emoji = "✅" if pnl_usd > 0 else "❌" if pnl_usd < 0 else "➖"
                print(f"{status_emoji} {asset}: ${entry_price:.4f} → ${current_price:.4f} (P&L: ${pnl_usd:+.2f}, {pnl_pct:+.1f}%) | {age_hours:.1f}h old")
        
        print()
        print(f"Summary: {exits_captured} exits captured this check")
        print(f"Total exits captured: {self.count_closed_trades()}/10")
        print()
        
        if exits_captured > 0:
            self.generate_report()
    
    def generate_report(self):
        """Generate exit monitor report"""
        total_proofs = self.count_closed_trades()
        
        report = f"""# Real Exit Validation Report
**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S EDT')}
**Total Real Exits Captured:** {total_proofs}
**Target:** 10 real closed trades with full proof

---

## Progress Toward 10 Real Closes

- **Captured:** {total_proofs}/10
- **Progress:** {(total_proofs/10)*100:.0f}%
- **Remaining:** {max(0, 10 - total_proofs)}

---

## Latest Exit Proofs

"""
        
        # Read last 5 proofs
        if EXIT_PROOF_LOG.exists():
            proofs = []
            with open(EXIT_PROOF_LOG) as f:
                for line in f:
                    if line.strip():
                        proofs.append(json.loads(line))
            
            recent = proofs[-5:] if len(proofs) > 5 else proofs
            
            for i, proof in enumerate(reversed(recent), 1):
                entry = proof['entry']
                exit_trigger = proof['exit_trigger']
                pnl = proof['realized_pnl']
                
                profit_emoji = "✅" if pnl['winner'] else "❌"
                
                report += f"""
### Exit #{total_proofs - i + 1} - {entry['asset']}

**{profit_emoji} {exit_trigger['reason'].upper().replace('_', ' ')}**

- Entry: ${entry['entry_price']:.4f} @ {entry['timestamp']}
- Exit: ${exit_trigger['exit_price']:.4f} @ {exit_trigger['triggered_at']}
- Hold: {proof['monitoring']['hold_duration_hours']:.1f} hours
- P&L: ${pnl['pnl_usd']:+.2f} ({pnl['pnl_pct']:+.1f}%)
- Result: {"WIN" if pnl['winner'] else "LOSS"}

---
"""
        
        report += f"""
## Next Check

Runs every 15 minutes. Next check: {(datetime.now() + timedelta(minutes=15)).strftime('%H:%M EDT')}

---

*Real exit validation active. Evidence only, no assumptions.*
"""
        
        with open(EXIT_MONITOR_REPORT, 'w') as f:
            f.write(report)


def main():
    """Run exit monitor"""
    monitor = ExitMonitor()
    monitor.monitor()


if __name__ == "__main__":
    main()
