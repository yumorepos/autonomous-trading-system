#!/usr/bin/env python3
"""
Continuous system health monitor: Proactive issue detection and auto-recovery.
Runs every 5 minutes, catches issues before they compound.
"""

import json
import time
import sys
import subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta
from hyperliquid.info import Info
from hyperliquid.utils import constants

ENGINE_ADDRESS = "0x8743f51c57e90644a0c141eD99064C4e9efFC01c"
CHECK_INTERVAL = 300  # 5 minutes

class HealthMonitor:
    def __init__(self):
        self.info = Info(constants.MAINNET_API_URL, skip_ws=True)
        self.last_issues = []
        
    def check_all(self):
        """Run all health checks, return issues found."""
        issues = []
        
        # 1. Engine process health
        process_issue = self.check_engine_process()
        if process_issue:
            issues.append(process_issue)
        
        # 2. State sync (exchange vs internal)
        sync_issues = self.check_state_sync()
        issues.extend(sync_issues)
        
        # 3. Ledger consistency
        ledger_issues = self.check_ledger_consistency()
        issues.extend(ledger_issues)
        
        # 4. Loss pattern detection
        loss_issue = self.check_loss_pattern()
        if loss_issue:
            issues.append(loss_issue)
        
        # 5. Heartbeat freshness
        heartbeat_issue = self.check_heartbeat()
        if heartbeat_issue:
            issues.append(heartbeat_issue)
        
        # 6. Capital reconciliation
        capital_issue = self.check_capital()
        if capital_issue:
            issues.append(capital_issue)
        
        return issues
    
    def check_engine_process(self):
        """Check if trading engine is running."""
        result = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
        if 'trading_engine.py' not in result.stdout:
            return {
                'severity': 'CRITICAL',
                'issue': 'Engine process not running',
                'auto_fix': 'restart_engine',
            }
        return None
    
    def check_state_sync(self):
        """Check if internal state matches exchange."""
        issues = []
        
        # Get exchange positions
        state = self.info.user_state(ENGINE_ADDRESS)
        exchange_positions = {ap['position']['coin']: ap['position'] for ap in state.get('assetPositions', [])}
        
        # Get internal state
        state_file = Path('workspace/logs/trading_engine_state.json')
        if not state_file.exists():
            return [{'severity': 'CRITICAL', 'issue': 'State file missing', 'auto_fix': None}]
        
        internal_state = json.loads(state_file.read_text())
        internal_positions = internal_state.get('open_positions', {})
        
        # Check for ghost positions (in state but not on exchange)
        for coin in internal_positions:
            if coin not in exchange_positions:
                issues.append({
                    'severity': 'HIGH',
                    'issue': f'Ghost position: {coin} in state but not on exchange',
                    'auto_fix': 'remove_ghost_position',
                    'coin': coin,
                })
        
        # Check for untracked positions (on exchange but not in state)
        for coin in exchange_positions:
            if coin not in internal_positions:
                issues.append({
                    'severity': 'HIGH',
                    'issue': f'Untracked position: {coin} on exchange but not in state',
                    'auto_fix': 'track_position',
                    'coin': coin,
                    'entry_price': exchange_positions[coin].get('entryPx'),
                })
        
        return issues
    
    def check_ledger_consistency(self):
        """Check if ledger entries match (entry/exit trade_ids)."""
        issues = []
        
        ledger_file = Path('workspace/logs/trade-ledger.jsonl')
        if not ledger_file.exists():
            return []
        
        with open(ledger_file) as f:
            entries = [json.loads(l) for l in f if l.strip()]
        
        # Get recent entries (last 10)
        recent = entries[-10:]
        
        entry_events = [e for e in recent if e.get('action') == 'entry']
        exit_events = [e for e in recent if e.get('action') == 'exit']
        
        # Check for entries without exits (older than 1 hour)
        one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        
        for entry in entry_events:
            trade_id = entry.get('trade_id')
            entry_time = entry.get('timestamp', '')
            
            # Find matching exit
            matching_exit = next((e for e in exit_events if e.get('trade_id') == trade_id), None)
            
            if not matching_exit and entry_time < one_hour_ago:
                issues.append({
                    'severity': 'MEDIUM',
                    'issue': f'Orphan entry: {trade_id} has no matching exit (>1 hour old)',
                    'auto_fix': None,  # Needs manual investigation
                    'trade_id': trade_id,
                })
        
        return issues
    
    def check_loss_pattern(self):
        """Detect unusual loss patterns."""
        ledger_file = Path('workspace/logs/trade-ledger.jsonl')
        if not ledger_file.exists():
            return None
        
        with open(ledger_file) as f:
            entries = [json.loads(l) for l in f if l.strip()]
        
        # Get last 5 exits
        exits = [e for e in entries if e.get('action') == 'exit'][-5:]
        
        if len(exits) < 3:
            return None
        
        # Check if all recent trades are losses
        recent_pnls = [e.get('pnl_usd', 0) for e in exits]
        
        if all(pnl < 0 for pnl in recent_pnls):
            avg_loss = sum(recent_pnls) / len(recent_pnls)
            if avg_loss < -0.5:  # Averaging >$0.50 loss per trade
                return {
                    'severity': 'HIGH',
                    'issue': f'{len(recent_pnls)} consecutive losses, avg ${avg_loss:.2f}',
                    'auto_fix': 'halt_trading',
                }
        
        return None
    
    def check_heartbeat(self):
        """Check if heartbeat is fresh."""
        state_file = Path('workspace/logs/trading_engine_state.json')
        if not state_file.exists():
            return {'severity': 'CRITICAL', 'issue': 'State file missing', 'auto_fix': None}
        
        state = json.loads(state_file.read_text())
        heartbeat_str = state.get('heartbeat')
        
        if not heartbeat_str:
            return {'severity': 'HIGH', 'issue': 'No heartbeat in state', 'auto_fix': None}
        
        heartbeat = datetime.fromisoformat(heartbeat_str.replace('Z', '+00:00'))
        age = (datetime.now(timezone.utc) - heartbeat).total_seconds()
        
        if age > 300:  # 5 minutes
            return {
                'severity': 'HIGH',
                'issue': f'Heartbeat stale ({age:.0f}s)',
                'auto_fix': 'restart_engine',
            }
        
        return None
    
    def check_capital(self):
        """Verify capital is tracked correctly."""
        # Get total capital
        state = self.info.user_state(ENGINE_ADDRESS)
        perps_value = float(state.get('marginSummary', {}).get('accountValue', 0))
        
        spot = self.info.spot_user_state(ENGINE_ADDRESS)
        spot_usd = sum(float(b.get('total', 0)) for b in spot.get('balances', []) if b.get('coin') in ('USDC', 'USDT', 'USDE'))
        
        total_capital = perps_value + spot_usd
        
        # Check against expected range
        if total_capital < 50:  # Should be ~$100
            return {
                'severity': 'CRITICAL',
                'issue': f'Capital severely depleted: ${total_capital:.2f}',
                'auto_fix': 'halt_trading',
            }
        
        return None
    
    def auto_fix(self, issue):
        """Apply automatic fix if available."""
        fix_type = issue.get('auto_fix')
        
        if not fix_type:
            return False
        
        if fix_type == 'remove_ghost_position':
            coin = issue.get('coin')
            state_file = Path('workspace/logs/trading_engine_state.json')
            state = json.loads(state_file.read_text())
            
            if coin in state.get('open_positions', {}):
                del state['open_positions'][coin]
            if coin in state.get('peak_roe', {}):
                del state['peak_roe'][coin]
            
            state_file.write_text(json.dumps(state, indent=2))
            print(f"  → Fixed: Removed ghost position {coin}")
            return True
        
        elif fix_type == 'restart_engine':
            # Kill old process
            subprocess.run(['pkill', '-f', 'trading_engine.py'], capture_output=True)
            time.sleep(2)
            
            # Start new
            subprocess.Popen(
                ['python3', 'scripts/trading_engine.py'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print(f"  → Fixed: Restarted engine")
            return True
        
        elif fix_type == 'halt_trading':
            state_file = Path('workspace/logs/trading_engine_state.json')
            state = json.loads(state_file.read_text())
            state['circuit_breaker_halted'] = True
            state['halt_reason'] = 'Auto-halted by health monitor: ' + issue['issue']
            state_file.write_text(json.dumps(state, indent=2))
            print(f"  → Fixed: Halted trading (circuit breaker)")
            return True
        
        return False
    
    def run_forever(self):
        """Continuous monitoring loop."""
        print(f"System Health Monitor starting")
        print(f"Check interval: {CHECK_INTERVAL}s")
        print(f"Address: {ENGINE_ADDRESS}")
        print()
        
        while True:
            timestamp = datetime.now(timezone.utc).strftime('%H:%M:%S')
            
            issues = self.check_all()
            
            if issues:
                print(f"[{timestamp}] ⚠️  {len(issues)} issue(s) found:")
                
                for issue in issues:
                    severity = issue['severity']
                    emoji = '🔴' if severity == 'CRITICAL' else '🟡' if severity == 'HIGH' else '🟢'
                    print(f"  {emoji} [{severity}] {issue['issue']}")
                    
                    # Try auto-fix
                    if issue.get('auto_fix'):
                        fixed = self.auto_fix(issue)
                        if not fixed:
                            print(f"     ❌ Auto-fix failed")
                    else:
                        print(f"     ⚠️  Manual intervention required")
                
                print()
            else:
                # Only print on state change (had issues → now clear)
                if self.last_issues:
                    print(f"[{timestamp}] ✅ All issues resolved")
                    print()
            
            self.last_issues = issues
            time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    monitor = HealthMonitor()
    monitor.run_forever()
