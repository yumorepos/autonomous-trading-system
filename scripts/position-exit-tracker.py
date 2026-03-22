#!/usr/bin/env python3
"""
Position Exit Distance Tracker
Support-only analytics script.
Compute and rank all open positions by proximity to any exit condition.
This script is not part of the canonical paper-trading execution path.
"""

import json
import sys
import requests
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.runtime import WORKSPACE_ROOT as WORKSPACE, LOGS_DIR, DATA_DIR
from models.position_state import get_open_positions
from models.trade_schema import validate_trade_record
PAPER_TRADES = LOGS_DIR / "phase1-paper-trades.jsonl"
EXIT_TRACKER_LOG = LOGS_DIR / "exit-tracker.jsonl"
EXIT_TRACKER_REPORT = WORKSPACE / "EXIT_TRACKER_REPORT.md"

# Exit thresholds
TAKE_PROFIT_PCT = 10.0
STOP_LOSS_PCT = -10.0
TIMEOUT_HOURS = 24.0

class ExitTracker:
    """Track distance to exit for all open positions"""
    
    def __init__(self):
        self.positions = []
        self.tracking_data = []
        
    def load_positions(self) -> List[Dict]:
        """Load open positions from authoritative position-state.json only."""
        positions = []
        for trade in get_open_positions(LOGS_DIR / 'position-state.json'):
            if not validate_trade_record(trade, context=f"position-exit-tracker[{trade.get('trade_id', 'unknown')}]"):
                continue
            positions.append(trade)
        return positions
    
    def get_current_price(self, asset: str) -> float:
        """Get current price from Hyperliquid"""
        try:
            r = requests.post("https://api.hyperliquid.xyz/info", 
                            json={'type': 'allMids'}, timeout=5)
            prices = r.json()
            return float(prices.get(asset, 0))
        except:
            return 0
    
    def calculate_volatility_estimate(self, asset: str, entry_price: float, current_price: float, age_hours: float) -> float:
        """Estimate volatility (simple: % change per hour)"""
        if age_hours == 0:
            return 0
        
        pct_change = abs((current_price - entry_price) / entry_price * 100)
        volatility_per_hour = pct_change / age_hours
        
        return volatility_per_hour
    
    def track_position(self, position: Dict) -> Dict:
        """Compute all exit distances for a position"""
        asset = position['symbol']
        entry_price = position['entry_price']
        entry_time = datetime.fromisoformat(position['entry_timestamp'])
        age_hours = (datetime.now(timezone.utc) - entry_time).total_seconds() / 3600
        
        # Get current price
        current_price = self.get_current_price(asset)
        
        if current_price == 0:
            return None
        
        # Current P&L
        side = position.get('side', position.get('direction', 'LONG'))
        pnl_pct = ((entry_price - current_price) / entry_price) * 100 if side == 'SHORT' else ((current_price - entry_price) / entry_price) * 100
        
        # Distance to take profit
        distance_to_tp_pct = TAKE_PROFIT_PCT - pnl_pct
        
        # Distance to stop loss (negative = already past stop loss)
        distance_to_sl_pct = pnl_pct - STOP_LOSS_PCT
        
        # Time to timeout
        time_to_timeout_hours = TIMEOUT_HOURS - age_hours
        
        # Volatility estimate
        volatility_per_hour = self.calculate_volatility_estimate(asset, entry_price, current_price, age_hours)
        
        # Estimate time to TP/SL based on volatility (if non-zero)
        if volatility_per_hour > 0:
            hours_to_tp = abs(distance_to_tp_pct) / volatility_per_hour if distance_to_tp_pct > 0 else 0
            hours_to_sl = abs(distance_to_sl_pct) / volatility_per_hour if distance_to_sl_pct > 0 else 0
        else:
            hours_to_tp = 999
            hours_to_sl = 999
        
        # Determine closest exit
        exits = [
            ('take_profit', distance_to_tp_pct, hours_to_tp, 'TP'),
            ('stop_loss', distance_to_sl_pct, hours_to_sl, 'SL'),
            ('timeout', time_to_timeout_hours, time_to_timeout_hours, 'TO')
        ]
        
        # Sort by time estimate (soonest first)
        exits.sort(key=lambda x: x[2])
        closest = exits[0]
        
        tracking = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'asset': asset,
            'entry_price': entry_price,
            'current_price': current_price,
            'pnl_pct': pnl_pct,
            'age_hours': age_hours,
            
            # Exit distances
            'distance_to_tp_pct': distance_to_tp_pct,
            'distance_to_sl_pct': distance_to_sl_pct,
            'time_to_timeout_hours': time_to_timeout_hours,
            
            # Volatility
            'volatility_per_hour': volatility_per_hour,
            'estimated_hours_to_tp': hours_to_tp,
            'estimated_hours_to_sl': hours_to_sl,
            
            # Closest exit
            'closest_exit': closest[0],
            'closest_distance': closest[1],
            'closest_time_estimate': closest[2],
            'closest_label': closest[3]
        }
        
        # Log to tracking file
        with open(EXIT_TRACKER_LOG, 'a') as f:
            f.write(json.dumps(tracking) + '\n')
        
        return tracking
    
    def rank_by_proximity(self) -> List[Tuple[int, Dict, str]]:
        """Rank positions by proximity to ANY exit"""
        ranked = []
        
        for i, track in enumerate(self.tracking_data, 1):
            if track is None:
                continue
            
            # Composite score: soonest exit (lower = sooner)
            score = track['closest_time_estimate']
            
            ranked.append((i, track, score))
        
        # Sort by score (ascending = soonest)
        ranked.sort(key=lambda x: x[2])
        
        return ranked
    
    def generate_report(self):
        """Generate comprehensive exit tracking report"""
        ranked = self.rank_by_proximity()
        
        report = f"""# Exit Tracker Report
**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S EDT')}
**Purpose:** Rank positions by proximity to ANY exit condition

---

## HARD CAP ACTIVE

**Max Open Positions:** 3 (HARD CAP)
**Current Open:** {len(self.tracking_data)}
**Status:** {"[RED] AT CAPACITY - NEW ENTRIES BLOCKED" if len(self.tracking_data) >= 3 else "[GREEN] CAPACITY AVAILABLE"}

**Policy:**
- Do NOT increase max until 3 real trades fully closed and validated
- If at capacity: block ALL new entries
- System focus: monitoring + exit validation ONLY

---

## POSITION TRACKING

"""
        
        for i, track in enumerate(self.tracking_data, 1):
            if track is None:
                report += f"### Position #{i}: PRICE FETCH FAILED\n\n"
                continue
            
            profit_emoji = "[OK]" if track['pnl_pct'] > 0 else "[FAIL]"
            
            report += f"""### Position #{i}: {track['asset']}

{profit_emoji} **Current P&L:** {track['pnl_pct']:+.2f}%

**Entry:** ${track['entry_price']:.4f}  
**Current:** ${track['current_price']:.4f}  
**Age:** {track['age_hours']:.1f} hours

**Distance to Exit:**
- Take Profit: {track['distance_to_tp_pct']:+.2f}% needed
- Stop Loss: {track['distance_to_sl_pct']:+.2f}% buffer remaining
- Timeout: {track['time_to_timeout_hours']:.1f} hours remaining

**Volatility Analysis:**
- Estimated volatility: {track['volatility_per_hour']:.2f}%/hour
- Est. time to TP: {track['estimated_hours_to_tp']:.1f}h
- Est. time to SL: {track['estimated_hours_to_sl']:.1f}h

**[NEXT] Closest Exit:** {track['closest_exit'].upper().replace('_', ' ')} (est. {track['closest_time_estimate']:.1f}h)

---

"""
        
        report += """## RANKED BY PROXIMITY TO EXIT

(Most likely to exit first -> last)

"""
        
        for rank, (pos_num, track, score) in enumerate(ranked, 1):
            report += f"{rank}. **{track['asset']} (Pos #{pos_num})** -> {track['closest_label']} in ~{score:.1f}h\n"
        
        report += f"""

---

## NEXT LIKELY EXIT

"""
        
        if ranked:
            first = ranked[0]
            track = first[1]
            
            report += f"""**Position #{first[0]}: {track['asset']}**

- Exit type: {track['closest_exit'].replace('_', ' ').upper()}
- Estimated time: ~{track['closest_time_estimate']:.1f} hours
- Current P&L: {track['pnl_pct']:+.2f}%
- Volatility: {track['volatility_per_hour']:.2f}%/hour

**This position is most likely to produce the first real lifecycle proof.**

"""
        
        report += f"""---

## MONITORING SCHEDULE

- Exit monitor: Every 15 minutes
- Exit safeguards: Every 30 minutes
- Next check: {(datetime.now() + pd.Timedelta(minutes=15)).strftime('%H:%M EDT') if 'pd' in dir() else 'Next 15-min mark'}

---

*Tracking active. Prioritizing exits over new entries.*
"""
        
        with open(EXIT_TRACKER_REPORT, 'w') as f:
            f.write(report)
    
    def run(self):
        """Run complete exit tracking"""
        print("="*80)
        print("POSITION EXIT TRACKER")
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S EDT')}")
        print("="*80)
        print()
        
        self.positions = self.load_positions()
        
        if not self.positions:
            print("[WARN]  No open positions to track")
            return
        
        print(f"Tracking {len(self.positions)} open positions...")
        print()
        
        for i, position in enumerate(self.positions, 1):
            track = self.track_position(position)
            self.tracking_data.append(track)
            
            if track:
                print(f"Position #{i}: {track['asset']}")
                print(f"  P&L: {track['pnl_pct']:+.2f}% | Age: {track['age_hours']:.1f}h")
                print(f"  Closest exit: {track['closest_exit'].upper()} in ~{track['closest_time_estimate']:.1f}h")
                print()
        
        # Rank positions
        ranked = self.rank_by_proximity()
        
        print("="*80)
        print("RANKED BY PROXIMITY (most likely to exit first)")
        print("="*80)
        print()
        
        for rank, (pos_num, track, score) in enumerate(ranked, 1):
            print(f"{rank}. Position #{pos_num} ({track['asset']}): {track['closest_label']} in ~{score:.1f}h")
        
        print()
        
        if ranked:
            first = ranked[0]
            print(f"[NEXT] MOST LIKELY NEXT EXIT: Position #{first[0]} ({first[1]['asset']}) -> {first[1]['closest_label']} in ~{first[2]:.1f}h")
        
        print()
        print(f"[STATS] Report: {EXIT_TRACKER_REPORT}")
        print(f"[NOTE] Log: {EXIT_TRACKER_LOG}")
        
        self.generate_report()


def main():
    """Run exit tracker"""
    tracker = ExitTracker()
    tracker.run()


if __name__ == "__main__":
    main()
