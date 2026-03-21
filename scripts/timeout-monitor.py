#!/usr/bin/env python3
"""
Enhanced Timeout Monitor
Track positions converging toward timeout with same rigor as SL/TP exits
"""

import json
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Optional

WORKSPACE = Path.home() / ".openclaw" / "workspace"
PAPER_TRADES = WORKSPACE / "logs" / "phase1-paper-trades.jsonl"
TIMEOUT_HISTORY = WORKSPACE / "logs" / "timeout-history.jsonl"
TIMEOUT_REPORT = WORKSPACE / "TIMEOUT_MONITOR_REPORT.md"

# Thresholds
TIMEOUT_HOURS = 24.0
TAKE_PROFIT_PCT = 10.0
STOP_LOSS_PCT = -10.0

class TimeoutMonitor:
    """Enhanced monitoring for timeout-driven exits"""
    
    def __init__(self):
        self.positions = []
        self.history = self.load_history()
        
    def load_history(self) -> Dict:
        """Load historical tracking data"""
        history = {}
        
        if TIMEOUT_HISTORY.exists():
            with open(TIMEOUT_HISTORY) as f:
                for line in f:
                    if line.strip():
                        data = json.loads(line)
                        key = (data['asset'], data['entry_time'])
                        if key not in history:
                            history[key] = []
                        history[key].append(data)
        
        return history
    
    def get_current_price(self, asset: str) -> Optional[float]:
        """Get current price"""
        try:
            r = requests.post("https://api.hyperliquid.xyz/info", 
                            json={'type': 'allMids'}, timeout=5)
            if r.status_code == 200:
                prices = r.json()
                return float(prices.get(asset, 0))
        except:
            pass
        return None
    
    def load_positions(self) -> List[Dict]:
        """Load open positions"""
        positions = []
        
        if PAPER_TRADES.exists():
            with open(PAPER_TRADES) as f:
                for line in f:
                    if line.strip():
                        trade = json.loads(line)
                        if trade.get('status') == 'OPEN':
                            positions.append(trade)
        
        return positions
    
    def calculate_pnl_trend(self, asset: str, entry_time: str) -> Dict:
        """Calculate P&L trend over last 3-5 checks"""
        key = (asset, entry_time)
        checks = self.history.get(key, [])
        
        # Get last 5 checks
        recent = checks[-5:] if len(checks) > 5 else checks
        
        if len(recent) < 2:
            return {
                'trend': 'insufficient_data',
                'checks': len(recent),
                'direction': None,
                'volatility': 0
            }
        
        # Calculate trend
        pnl_values = [c['pnl_pct'] for c in recent]
        
        # Simple linear trend
        first = pnl_values[0]
        last = pnl_values[-1]
        change = last - first
        
        # Volatility (std dev)
        if len(pnl_values) > 1:
            mean = sum(pnl_values) / len(pnl_values)
            variance = sum((x - mean) ** 2 for x in pnl_values) / len(pnl_values)
            volatility = variance ** 0.5
        else:
            volatility = 0
        
        # Determine direction
        if change > 0.5:
            direction = 'improving'
        elif change < -0.5:
            direction = 'deteriorating'
        else:
            direction = 'stable'
        
        return {
            'trend': direction,
            'checks': len(recent),
            'change_pct': change,
            'volatility': volatility,
            'recent_pnl': pnl_values
        }
    
    def calculate_convergence(self, entry_price: float, current_price: float, pnl_trend: Dict) -> str:
        """Determine if position is converging or diverging from entry"""
        pnl_pct = ((current_price - entry_price) / entry_price) * 100
        
        # Check if price is moving back toward entry
        if pnl_trend['trend'] == 'insufficient_data':
            return 'unknown'
        
        # If currently at loss and improving → converging
        if pnl_pct < 0 and pnl_trend['trend'] == 'improving':
            return 'converging_to_entry'
        
        # If currently at profit and deteriorating → converging
        if pnl_pct > 0 and pnl_trend['trend'] == 'deteriorating':
            return 'converging_to_entry'
        
        # If moving away from entry
        if abs(pnl_pct) > 0.5 and pnl_trend['trend'] in ['improving', 'deteriorating']:
            if (pnl_pct > 0 and pnl_trend['trend'] == 'improving') or \
               (pnl_pct < 0 and pnl_trend['trend'] == 'deteriorating'):
                return 'diverging_from_entry'
        
        # Otherwise stable
        return 'stable_near_entry'
    
    def calculate_exit_probabilities(self, pnl_pct: float, age_hours: float, pnl_trend: Dict) -> Dict:
        """Calculate probability of each exit type"""
        time_remaining = TIMEOUT_HOURS - age_hours
        
        # Distance to exits
        distance_to_tp = abs(TAKE_PROFIT_PCT - pnl_pct)
        distance_to_sl = abs(STOP_LOSS_PCT - pnl_pct)
        
        # Volatility-adjusted time estimates
        if pnl_trend['volatility'] > 0:
            hours_to_tp = distance_to_tp / pnl_trend['volatility'] if pnl_trend['trend'] == 'improving' else 999
            hours_to_sl = distance_to_sl / pnl_trend['volatility'] if pnl_trend['trend'] == 'deteriorating' else 999
        else:
            hours_to_tp = 999
            hours_to_sl = 999
        
        # Calculate probabilities (simple heuristic)
        # Timeout is likely if time remaining < time to TP/SL
        timeout_prob = 0
        tp_prob = 0
        sl_prob = 0
        
        if time_remaining < min(hours_to_tp, hours_to_sl):
            # Timeout most likely
            timeout_prob = 70
            tp_prob = 15 if pnl_pct > 0 else 5
            sl_prob = 15 if pnl_pct < 0 else 10
        elif hours_to_tp < hours_to_sl and hours_to_tp < time_remaining:
            # TP most likely
            tp_prob = 60
            timeout_prob = 25
            sl_prob = 15
        elif hours_to_sl < hours_to_tp and hours_to_sl < time_remaining:
            # SL most likely
            sl_prob = 60
            timeout_prob = 25
            tp_prob = 15
        else:
            # Mixed
            timeout_prob = 50
            tp_prob = 25
            sl_prob = 25
        
        return {
            'take_profit_pct': tp_prob,
            'stop_loss_pct': sl_prob,
            'timeout_pct': timeout_prob,
            'most_likely': 'timeout' if timeout_prob > max(tp_prob, sl_prob) else ('take_profit' if tp_prob > sl_prob else 'stop_loss'),
            'time_estimates': {
                'hours_to_tp': hours_to_tp if hours_to_tp < 999 else None,
                'hours_to_sl': hours_to_sl if hours_to_sl < 999 else None,
                'hours_to_timeout': time_remaining
            }
        }
    
    def monitor_position(self, position: Dict) -> Dict:
        """Monitor single position with timeout focus"""
        asset = position['signal']['asset']
        entry_time = position['entry_time']
        entry_price = position['entry_price']
        
        # Get current state
        current_price = self.get_current_price(asset)
        if not current_price:
            return None
        
        entry_dt = datetime.fromisoformat(entry_time)
        now = datetime.now(timezone.utc)
        age_hours = (now - entry_dt).total_seconds() / 3600
        age_minutes = age_hours * 60
        time_to_timeout_minutes = (TIMEOUT_HOURS - age_hours) * 60
        
        # Calculate P&L
        pnl_pct = ((current_price - entry_price) / entry_price) * 100
        
        # Get P&L trend
        pnl_trend = self.calculate_pnl_trend(asset, entry_time)
        
        # Calculate convergence
        convergence = self.calculate_convergence(entry_price, current_price, pnl_trend)
        
        # Calculate exit probabilities
        exit_probs = self.calculate_exit_probabilities(pnl_pct, age_hours, pnl_trend)
        
        # Determine if timeout candidate
        timeout_candidate = exit_probs['timeout_pct'] >= 60
        
        # Build tracking record
        tracking = {
            'timestamp': now.isoformat(),
            'asset': asset,
            'entry_time': entry_time,
            'entry_price': entry_price,
            'current_price': current_price,
            'pnl_pct': pnl_pct,
            'age_hours': age_hours,
            'age_minutes': age_minutes,
            'time_to_timeout_minutes': time_to_timeout_minutes,
            'pnl_trend': pnl_trend,
            'convergence': convergence,
            'exit_probabilities': exit_probs,
            'timeout_candidate': timeout_candidate,
            'priority': 'HIGH' if timeout_candidate and time_to_timeout_minutes < 120 else 'NORMAL'
        }
        
        # Save to history
        with open(TIMEOUT_HISTORY, 'a') as f:
            f.write(json.dumps(tracking) + '\n')
        
        return tracking
    
    def generate_report(self, tracked: List[Dict]):
        """Generate timeout monitoring report"""
        timeout_candidates = [t for t in tracked if t and t['timeout_candidate']]
        
        report = f"""# Timeout Monitor Report
**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S EDT')}
**Purpose:** Enhanced monitoring for timeout-driven exits

---

## TIMEOUT CANDIDATES: {len(timeout_candidates)}

"""
        
        for i, track in enumerate(timeout_candidates, 1):
            priority_emoji = "🔴" if track['priority'] == 'HIGH' else "🟡"
            
            report += f"""### {priority_emoji} Position {i}: {track['asset']} (TIMEOUT LIKELY)

**Time to Timeout:** {track['time_to_timeout_minutes']:.0f} minutes ({track['time_to_timeout_minutes']/60:.1f} hours)

**Current State:**
- P&L: {track['pnl_pct']:+.2f}%
- Age: {track['age_hours']:.1f} hours
- Entry: ${track['entry_price']:.4f}
- Current: ${track['current_price']:.4f}

**P&L Trend (last {track['pnl_trend']['checks']} checks):**
- Direction: {track['pnl_trend']['trend']}
- Change: {track['pnl_trend'].get('change_pct', 0):+.2f}%
- Volatility: {track['pnl_trend']['volatility']:.2f}%

**Convergence:**
- Pattern: {track['convergence']}

**Exit Probabilities:**
- Timeout: {track['exit_probabilities']['timeout_pct']}%
- Take Profit: {track['exit_probabilities']['take_profit_pct']}%
- Stop Loss: {track['exit_probabilities']['stop_loss_pct']}%
- **Most Likely:** {track['exit_probabilities']['most_likely'].upper()}

**Priority:** {track['priority']}

---

"""
        
        # All positions
        report += f"""
## ALL OPEN POSITIONS: {len([t for t in tracked if t])}

"""
        
        for i, track in enumerate(tracked, 1):
            if not track:
                continue
            
            likely = track['exit_probabilities']['most_likely']
            emoji = "⏱️" if likely == 'timeout' else "✅" if likely == 'take_profit' else "❌"
            
            report += f"{emoji} **{track['asset']}** → {likely.upper()} ({track['exit_probabilities'][f'{likely}_pct']}%) in {track['time_to_timeout_minutes']:.0f}min\n"
        
        report += """

---

## MONITORING SCHEDULE

- Runs: Every 15 minutes (exit-monitor)
- Timeout threshold: 24 hours
- High priority: < 2 hours remaining

---

*Enhanced timeout monitoring active. Rigorous lifecycle capture ready for timeout exits.*
"""
        
        with open(TIMEOUT_REPORT, 'w') as f:
            f.write(report)
    
    def run(self):
        """Run timeout monitoring"""
        print("="*80)
        print("TIMEOUT MONITOR")
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S EDT')}")
        print("="*80)
        print()
        
        self.positions = self.load_positions()
        
        if not self.positions:
            print("⚠️  No open positions")
            return
        
        print(f"Monitoring {len(self.positions)} positions...")
        print()
        
        tracked = []
        timeout_candidates = []
        
        for position in self.positions:
            track = self.monitor_position(position)
            tracked.append(track)
            
            if track and track['timeout_candidate']:
                timeout_candidates.append(track)
                
                priority_emoji = "🔴" if track['priority'] == 'HIGH' else "🟡"
                print(f"{priority_emoji} {track['asset']}: TIMEOUT CANDIDATE")
                print(f"   Time remaining: {track['time_to_timeout_minutes']:.0f} minutes")
                print(f"   Probability: {track['exit_probabilities']['timeout_pct']}%")
                print(f"   P&L: {track['pnl_pct']:+.2f}% ({track['pnl_trend']['trend']})")
                print()
        
        if timeout_candidates:
            print(f"⏱️  {len(timeout_candidates)} TIMEOUT CANDIDATES identified")
        else:
            print("ℹ️  No timeout candidates (all positions more likely SL/TP)")
        
        print()
        print(f"📊 Report: {TIMEOUT_REPORT}")
        
        self.generate_report(tracked)


def main():
    """Run timeout monitor"""
    monitor = TimeoutMonitor()
    monitor.run()


if __name__ == "__main__":
    main()
