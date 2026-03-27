#!/usr/bin/env python3
"""
Edge Monitor: Continuously verify velocity changes aren't degrading edge.
Reverts to conservative thresholds if expectancy/win rate drops.
"""

import json
from pathlib import Path
from datetime import datetime, timezone

# Import trade logger
import sys
sys.path.insert(0, str(Path(__file__).parent))
from daily_update import get_trade_stats

# Edge protection thresholds
MIN_EXPECTANCY = 0.50  # $0.50 per trade minimum
MIN_WIN_RATE = 0.50    # 50% win rate minimum
MIN_SAMPLE_SIZE = 10   # Need 10 trades before checking

# Conservative fallback parameters (pre-velocity optimization)
CONSERVATIVE_SL = 0.10
CONSERVATIVE_TP = 0.15
CONSERVATIVE_TIMEOUT = 12
CONSERVATIVE_TIER1_FUNDING = 1.50

# Current parameters (post-velocity optimization)
OPTIMIZED_SL = 0.07
OPTIMIZED_TP = 0.10
OPTIMIZED_TIMEOUT = 8
OPTIMIZED_TIER1_FUNDING = 1.00

class EdgeMonitor:
    """Monitor edge integrity after velocity changes."""
    
    def __init__(self):
        self.stats = get_trade_stats()
        self.repo_root = Path(__file__).parent.parent
    
    def assess_edge_integrity(self):
        """Check if edge is still valid after velocity changes."""
        
        closed = self.stats['closed']
        expectancy = self.stats['expectancy']
        win_rate = self.stats['win_rate']
        
        if closed < MIN_SAMPLE_SIZE:
            return {
                'status': 'INSUFFICIENT_DATA',
                'closed': closed,
                'needed': MIN_SAMPLE_SIZE,
                'action': 'HOLD',
                'reason': f'Need {MIN_SAMPLE_SIZE - closed} more trades to assess edge',
            }
        
        # Check if edge has degraded
        edge_degraded = (expectancy < MIN_EXPECTANCY) or (win_rate < MIN_WIN_RATE)
        
        if edge_degraded:
            return {
                'status': 'EDGE_DEGRADED',
                'expectancy': expectancy,
                'win_rate': win_rate,
                'action': 'REVERT',
                'reason': f'Edge below threshold (exp=${expectancy:.2f}, WR={win_rate*100:.1f}%)',
                'recommendation': 'Revert to conservative parameters',
            }
        else:
            return {
                'status': 'EDGE_INTACT',
                'expectancy': expectancy,
                'win_rate': win_rate,
                'action': 'CONTINUE',
                'reason': f'Edge still valid (exp=${expectancy:.2f}, WR={win_rate*100:.1f}%)',
            }
    
    def revert_to_conservative(self):
        """Revert risk-guardian and tiered_scanner to pre-velocity parameters."""
        
        # Revert risk-guardian.py
        guardian = self.repo_root / "scripts/risk-guardian.py"
        content = guardian.read_text()
        
        content = content.replace(
            f'STOP_LOSS_ROE = -{OPTIMIZED_SL}',
            f'STOP_LOSS_ROE = -{CONSERVATIVE_SL}'
        )
        content = content.replace(
            f'TAKE_PROFIT_ROE = {OPTIMIZED_TP}',
            f'TAKE_PROFIT_ROE = {CONSERVATIVE_TP}'
        )
        content = content.replace(
            f'TIMEOUT_HOURS = {OPTIMIZED_TIMEOUT}',
            f'TIMEOUT_HOURS = {CONSERVATIVE_TIMEOUT}'
        )
        
        guardian.write_text(content)
        
        # Revert tiered_scanner.py
        scanner = self.repo_root / "scripts/tiered_scanner.py"
        content = scanner.read_text()
        
        content = content.replace(
            f'TIER1_MIN_FUNDING = {OPTIMIZED_TIER1_FUNDING}',
            f'TIER1_MIN_FUNDING = {CONSERVATIVE_TIER1_FUNDING}'
        )
        
        scanner.write_text(content)
        
        return {
            'guardian': 'reverted',
            'scanner': 'reverted',
            'parameters': {
                'SL': f'{CONSERVATIVE_SL:.0%}',
                'TP': f'{CONSERVATIVE_TP:.0%}',
                'Timeout': f'{CONSERVATIVE_TIMEOUT}h',
                'Tier1': f'{CONSERVATIVE_TIER1_FUNDING:.0%}',
            }
        }
    
    def generate_report(self):
        """Generate edge protection report."""
        
        assessment = self.assess_edge_integrity()
        
        print("=" * 70)
        print("  EDGE PROTECTION MONITOR")
        print("  " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
        print("=" * 70)
        print()
        
        # Current State
        print("CURRENT STATE:")
        print(f"  Closed trades: {self.stats['closed']}")
        
        if self.stats['closed'] > 0:
            print(f"  Win rate: {self.stats['win_rate']*100:.1f}%")
            print(f"  Expectancy: ${self.stats['expectancy']:+.2f}/trade")
        
        print()
        
        # Edge Assessment
        print(f"EDGE STATUS: {assessment['status']}")
        print()
        
        if assessment['status'] == 'INSUFFICIENT_DATA':
            print(f"Need {assessment['needed'] - assessment['closed']} more trades to assess edge")
            print("Velocity optimizations remain active")
        
        elif assessment['status'] == 'EDGE_DEGRADED':
            print("⚠️  EDGE DEGRADATION DETECTED")
            print(f"  Expectancy: ${assessment['expectancy']:.2f} (min: ${MIN_EXPECTANCY})")
            print(f"  Win rate: {assessment['win_rate']*100:.1f}% (min: {MIN_WIN_RATE*100:.0f}%)")
            print()
            print("RECOMMENDED ACTION: REVERT TO CONSERVATIVE PARAMETERS")
            print()
            
            # Execute revert
            print("EXECUTING REVERT...")
            result = self.revert_to_conservative()
            print(f"  ✅ risk-guardian.py: Reverted")
            print(f"  ✅ tiered_scanner.py: Reverted")
            print()
            print("REVERTED PARAMETERS:")
            for k, v in result['parameters'].items():
                print(f"  {k}: {v}")
            print()
            print("⚠️  VELOCITY OPTIMIZATIONS DISABLED")
            print("Edge preservation takes priority over trade frequency")
        
        elif assessment['status'] == 'EDGE_INTACT':
            print("✅ EDGE STILL VALID")
            print(f"  Expectancy: ${assessment['expectancy']:.2f} (min: ${MIN_EXPECTANCY})")
            print(f"  Win rate: {assessment['win_rate']*100:.1f}% (min: {MIN_WIN_RATE*100:.0f}%)")
            print()
            print("ACTION: CONTINUE WITH VELOCITY OPTIMIZATIONS")
            print("Edge integrity maintained, faster validation on track")
        
        print()
        print("=" * 70)
        
        return assessment

if __name__ == "__main__":
    monitor = EdgeMonitor()
    monitor.generate_report()
