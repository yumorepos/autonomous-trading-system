#!/usr/bin/env python3
"""
Enhanced Timeout Monitor
Track positions converging toward timeout with same rigor as SL/TP exits
"""

import json
import sys
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.runtime import WORKSPACE_ROOT as WORKSPACE, LOGS_DIR, DATA_DIR
from models.position_state import get_open_positions
from models.trade_schema import validate_trade_record
from utils.json_utils import safe_read_json, safe_read_jsonl
from utils.system_health import SystemHealthManager
PAPER_TRADES = LOGS_DIR / "phase1-paper-trades.jsonl"
TIMEOUT_HISTORY = LOGS_DIR / "timeout-history.jsonl"
TIMEOUT_REPORT = WORKSPACE / "TIMEOUT_MONITOR_REPORT.md"

# Thresholds
TIMEOUT_HOURS = 24.0
TAKE_PROFIT_PCT = 10.0
STOP_LOSS_PCT = -10.0
EXCHANGE_THRESHOLDS = {
    'Hyperliquid': {
        'timeout_hours': 24.0,
        'take_profit_pct': 10.0,
        'stop_loss_pct': -10.0,
    },
    'Polymarket': {
        'timeout_hours': 24.0,
        'take_profit_pct': 8.0,
        'stop_loss_pct': -8.0,
    },
}

class TimeoutMonitor:
    """Enhanced monitoring for timeout-driven exits"""
    
    def __init__(self):
        self.positions = []
        self.health_manager = SystemHealthManager()
        
    def load_history(self) -> Dict:
        """Load historical tracking data"""
        history = {}

        for data in safe_read_jsonl(TIMEOUT_HISTORY):
            key = (data['asset'], data['entry_time'])
            if key not in history:
                history[key] = []
            history[key].append(data)
        
        return history
    
    def get_current_price(self, position: Dict) -> Optional[float]:
        """Get current price for Hyperliquid or Polymarket open positions."""
        exchange = position.get('exchange', position.get('signal', {}).get('exchange', position.get('signal', {}).get('source', 'Hyperliquid')))
        if exchange == 'Polymarket':
            market_id = position.get('market_id') or position.get('symbol')
            side = position.get('side', 'YES')
            token_id = position.get('token_id')
            try:
                r = requests.get(
                    "https://gamma-api.polymarket.com/markets",
                    params={'condition_id': market_id},
                    timeout=5,
                )
                if r.status_code == 200:
                    for market in r.json():
                        for token in market.get('tokens', []):
                            outcome = str(token.get('outcome') or '').upper()
                            candidate_token_id = str(token.get('token_id') or token.get('tokenId') or token.get('id') or '')
                            if outcome == side or (token_id and candidate_token_id == token_id):
                                return float(token.get('price') or token.get('bestAsk') or token.get('ask') or token.get('bestBid') or token.get('bid') or 0)
            except Exception:
                pass
            return None

        asset = position['symbol']
        try:
            r = requests.post("https://api.hyperliquid.xyz/info", 
                            json={'type': 'allMids'}, timeout=5)
            if r.status_code == 200:
                prices = r.json()
                price = float(prices.get(asset, 0))
                if price > 0:
                    self.health_manager.resolve_incident(
                        incident_type='timeout_monitor_missing_price',
                        source='timeout-monitor',
                        affected_trade=asset,
                        resolution_reason='Price became available again for timeout monitoring',
                    )
                    self.health_manager.resolve_incident(
                        incident_type='timeout_monitor_api_instability',
                        source='timeout-monitor',
                        affected_trade=asset,
                        resolution_reason='Timeout monitor API recovered and price lookups succeeded',
                    )
                    self.health_manager.resolve_incident(
                        incident_type='timeout_monitor_failure',
                        source='timeout-monitor',
                        affected_trade=asset,
                        resolution_reason='Timeout monitor recovered after successful price lookup',
                    )
                return price
            self.health_manager.record_incident(
                incident_type='timeout_monitor_api_instability',
                severity='MEDIUM',
                source='timeout-monitor',
                message=f"Timeout monitor price lookup failed for {asset}: HTTP {r.status_code}",
                affected_trade=asset,
                affected_system='timeout-monitoring',
                affected_components=['timeout_monitor', 'hyperliquid_api'],
                metadata={'asset': asset, 'status_code': r.status_code},
            )
        except:
            self.health_manager.record_incident(
                incident_type='timeout_monitor_failure',
                severity='MEDIUM',
                source='timeout-monitor',
                message=f"Timeout monitor price lookup raised for {asset}",
                affected_trade=asset,
                affected_system='timeout-monitoring',
                affected_components=['timeout_monitor', 'hyperliquid_api'],
                metadata={'asset': asset},
            )
        return None
    
    def load_positions(self) -> List[Dict]:
        """Load open positions from authoritative position-state.json only."""
        positions = []
        for position in get_open_positions(LOGS_DIR / "position-state.json"):
            if not validate_trade_record(position, context=f"timeout-monitor[{position.get('trade_id', 'unknown')}]"):
                continue
            positions.append(position)
        return positions
    
    def calculate_pnl_trend(self, asset: str, entry_time: str) -> Dict:
        """Calculate P&L trend over last 3-5 checks"""
        history = self.load_history()
        key = (asset, entry_time)
        checks = history.get(key, [])
        
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
    
    def calculate_convergence(self, entry_price: float, current_price: float, pnl_trend: Dict, side: str = 'LONG') -> str:
        """Determine if position is converging or diverging from entry"""
        if side == 'SHORT':
            pnl_pct = ((entry_price - current_price) / entry_price) * 100
        else:
            pnl_pct = ((current_price - entry_price) / entry_price) * 100
        
        # Check if price is moving back toward entry
        if pnl_trend['trend'] == 'insufficient_data':
            return 'unknown'
        
        # If currently at loss and improving -> converging
        if pnl_pct < 0 and pnl_trend['trend'] == 'improving':
            return 'converging_to_entry'
        
        # If currently at profit and deteriorating -> converging
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
        return self.calculate_exit_probabilities_with_thresholds(
            pnl_pct=pnl_pct,
            age_hours=age_hours,
            pnl_trend=pnl_trend,
            timeout_hours=TIMEOUT_HOURS,
            take_profit_pct=TAKE_PROFIT_PCT,
            stop_loss_pct=STOP_LOSS_PCT,
        )

    def calculate_exit_probabilities_with_thresholds(
        self,
        pnl_pct: float,
        age_hours: float,
        pnl_trend: Dict,
        timeout_hours: float,
        take_profit_pct: float,
        stop_loss_pct: float,
    ) -> Dict:
        """Calculate exit probabilities using exchange-specific thresholds."""
        time_remaining = timeout_hours - age_hours

        # Distance to exits
        distance_to_tp = abs(take_profit_pct - pnl_pct)
        distance_to_sl = abs(stop_loss_pct - pnl_pct)
        
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
        asset = position['symbol']
        entry_time = position['entry_timestamp']
        entry_price = position['entry_price']
        
        # Get current state
        current_price = self.get_current_price(position)
        if not current_price:
            self.health_manager.record_incident(
                incident_type='timeout_monitor_missing_price',
                severity='LOW',
                source='timeout-monitor',
                message=f"Timeout monitor skipped {asset}: current price unavailable",
                affected_trade=asset,
                affected_system='timeout-monitoring',
                affected_components=['timeout_monitor'],
                metadata={'asset': asset, 'entry_time': entry_time},
            )
            return None
        
        entry_dt = datetime.fromisoformat(entry_time)
        now = datetime.now(timezone.utc)
        age_hours = (now - entry_dt).total_seconds() / 3600
        age_minutes = age_hours * 60
        exchange = position.get('exchange', position.get('signal', {}).get('exchange', 'Hyperliquid'))
        thresholds = EXCHANGE_THRESHOLDS.get(exchange, EXCHANGE_THRESHOLDS['Hyperliquid'])
        time_to_timeout_minutes = (thresholds['timeout_hours'] - age_hours) * 60
        
        # Calculate P&L
        side = position.get('side', position.get('direction', 'LONG'))
        if side == 'SHORT':
            pnl_pct = ((entry_price - current_price) / entry_price) * 100
        else:
            pnl_pct = ((current_price - entry_price) / entry_price) * 100
        
        # Get P&L trend
        pnl_trend = self.calculate_pnl_trend(asset, entry_time)
        
        # Calculate convergence
        convergence = self.calculate_convergence(entry_price, current_price, pnl_trend, side=side)
        
        # Calculate exit probabilities
        exit_probs = self.calculate_exit_probabilities_with_thresholds(
            pnl_pct=pnl_pct,
            age_hours=age_hours,
            pnl_trend=pnl_trend,
            timeout_hours=thresholds['timeout_hours'],
            take_profit_pct=thresholds['take_profit_pct'],
            stop_loss_pct=thresholds['stop_loss_pct'],
        )
        
        # Determine if timeout candidate
        timeout_candidate = exit_probs['timeout_pct'] >= 60
        
        # Build tracking record
        tracking = {
            'timestamp': now.isoformat(),
            'asset': asset,
            'exchange': exchange,
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
**Purpose:** Non-authoritative monitoring for timeout-driven paper exits

---

## TIMEOUT CANDIDATES: {len(timeout_candidates)}

"""
        
        for i, track in enumerate(timeout_candidates, 1):
            priority_emoji = "[RED]" if track['priority'] == 'HIGH' else "[YELLOW]"
            
            report += f"""### {priority_emoji} Position {i}: [{track['exchange']}] {track['asset']} (TIMEOUT LIKELY)

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
            emoji = "[TIME]" if likely == 'timeout' else "[OK]" if likely == 'take_profit' else "[FAIL]"
            
            report += f"{emoji} **{track['asset']}** -> {likely.upper()} ({track['exit_probabilities'][f'{likely}_pct']}%) in {track['time_to_timeout_minutes']:.0f}min\n"
        
        report += """

---

## MONITORING SCHEDULE

- Runs: Every 15 minutes (timeout-monitor)
- Timeout threshold: exchange-specific (currently 24 hours in both paper modes)
- High priority: < 2 hours remaining

---

*Monitoring only: this report does not authoritatively close positions or prove that an exit was executed.*
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
            print("[WARN]  No open positions")
            # Generate empty report
            report = f"""# Timeout Monitor Report
**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S EDT')}
**Purpose:** Enhanced monitoring for timeout-driven exits

---

## TIMEOUT CANDIDATES: 0

No open positions to monitor.
"""
            with open(TIMEOUT_REPORT, 'w') as f:
                f.write(report)
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
                
                priority_emoji = "[RED]" if track['priority'] == 'HIGH' else "[YELLOW]"
                print(f"{priority_emoji} {track['asset']}: TIMEOUT CANDIDATE")
                print(f"   Time remaining: {track['time_to_timeout_minutes']:.0f} minutes")
                print(f"   Probability: {track['exit_probabilities']['timeout_pct']}%")
                print(f"   P&L: {track['pnl_pct']:+.2f}% ({track['pnl_trend']['trend']})")
                print()
        
        if timeout_candidates:
            print(f"[TIME]  {len(timeout_candidates)} TIMEOUT CANDIDATES identified")
        else:
            print("[INFO]  No timeout candidates (all positions more likely SL/TP)")
        
        print()
        print(f"[STATS] Report: {TIMEOUT_REPORT}")
        
        self.generate_report(tracked)


def main():
    """Run timeout monitor"""
    monitor = TimeoutMonitor()
    monitor.run()


if __name__ == "__main__":
    main()
