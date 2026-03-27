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
    
    def get_rolling_performance(self, window=5):
        """Get performance for last N trades (early warning)."""
        if not Path(TRADE_LOGGER).exists():
            return None
        
        trades = []
        with Path(TRADE_LOGGER).open("r") as f:
            for line in f:
                if line.strip():
                    trades.append(json.loads(line))
        
        closed = [t for t in trades if t.get("exit_timestamp")]
        
        if len(closed) < 3:  # Need minimum 3 trades
            return None
        
        # Get last N trades
        recent = closed[-window:]
        
        wins = [t for t in recent if t.get("total_pnl_usd", 0) > 0]
        losses = [t for t in recent if t.get("total_pnl_usd", 0) <= 0]
        
        win_rate = len(wins) / len(recent) if recent else 0
        
        total_pnl = sum(t.get("total_pnl_usd", 0) for t in recent)
        expectancy = total_pnl / len(recent)
        
        return {
            "trades": len(recent),
            "win_rate": win_rate,
            "expectancy": expectancy,
            "wins": len(wins),
            "losses": len(losses),
        }
    
    def get_trend_analysis(self):
        """Analyze trend direction over consecutive trades."""
        if not Path(TRADE_LOGGER).exists():
            return None
        
        trades = []
        with Path(TRADE_LOGGER).open("r") as f:
            for line in f:
                if line.strip():
                    trades.append(json.loads(line))
        
        closed = [t for t in trades if t.get("exit_timestamp")]
        
        if len(closed) < 5:  # Need at least 5 for trend
            return None
        
        # Get last 3 windows (3-trade rolling)
        windows = []
        for i in range(3, min(len(closed) + 1, 8)):  # Up to 7 trades back
            window = closed[-i:][:3]  # Last 3 trades
            if len(window) == 3:
                wins = [t for t in window if t.get("total_pnl_usd", 0) > 0]
                total_pnl = sum(t.get("total_pnl_usd", 0) for t in window)
                windows.append({
                    'expectancy': total_pnl / 3,
                    'win_rate': len(wins) / 3,
                })
        
        if len(windows) < 2:
            return None
        
        # Calculate trends
        exp_trend = windows[-1]['expectancy'] - windows[0]['expectancy']
        wr_trend = windows[-1]['win_rate'] - windows[0]['win_rate']
        
        # Classify trends
        def classify_trend(value, threshold=0.1):
            if value > threshold:
                return 'IMPROVING'
            elif value < -threshold:
                return 'DETERIORATING'
            else:
                return 'STABLE'
        
        return {
            'expectancy_trend': classify_trend(exp_trend, 0.15),
            'win_rate_trend': classify_trend(wr_trend, 0.10),
            'exp_change': exp_trend,
            'wr_change': wr_trend,
            'windows': len(windows),
        }
    
    def check_early_warning(self):
        """Check if recent performance shows deterioration (before full revert)."""
        
        # Get rolling 5-trade performance
        rolling = self.get_rolling_performance(window=5)
        
        if rolling is None:
            return None
        
        # Get trend analysis
        trend = self.get_trend_analysis()
        
        # Early warning thresholds (more lenient than revert)
        WARNING_EXPECTANCY = 0.30  # $0.30 vs $0.50 for revert
        WARNING_WIN_RATE = 0.40    # 40% vs 50% for revert
        
        warnings = []
        
        if rolling['expectancy'] < WARNING_EXPECTANCY:
            warnings.append(f"Low expectancy in last {rolling['trades']} trades: ${rolling['expectancy']:.2f}")
        
        if rolling['win_rate'] < WARNING_WIN_RATE:
            warnings.append(f"Low win rate in last {rolling['trades']} trades: {rolling['win_rate']*100:.0f}%")
        
        # Add trend-based warnings
        if trend:
            if trend['expectancy_trend'] == 'DETERIORATING':
                warnings.append(f"Expectancy deteriorating (Δ${trend['exp_change']:.2f} over {trend['windows']} windows)")
            
            if trend['win_rate_trend'] == 'DETERIORATING':
                warnings.append(f"Win rate deteriorating (Δ{trend['wr_change']*100:.0f}% over {trend['windows']} windows)")
        
        if warnings:
            return {
                'status': 'WARNING',
                'rolling': rolling,
                'trend': trend,
                'warnings': warnings,
                'action': 'MONITOR',
                'reason': 'Recent performance or trend below threshold',
            }
        
        return {
            'status': 'HEALTHY',
            'rolling': rolling,
            'trend': trend,
            'action': 'CONTINUE',
        }
    
    def assess_edge_integrity(self):
        """Check if edge is still valid after velocity changes."""
        
        closed = self.stats['closed']
        expectancy = self.stats['expectancy']
        win_rate = self.stats['win_rate']
        
        # Early warning check (3-5 trades)
        if closed >= 3 and closed < MIN_SAMPLE_SIZE:
            early_warning = self.check_early_warning()
            if early_warning and early_warning['status'] == 'WARNING':
                return early_warning
            
            return {
                'status': 'INSUFFICIENT_DATA',
                'closed': closed,
                'needed': MIN_SAMPLE_SIZE,
                'action': 'HOLD',
                'reason': f'Need {MIN_SAMPLE_SIZE - closed} more trades to assess edge',
                'early_check': early_warning,
            }
        
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
            
            # Show early warning if available
            if 'early_check' in assessment and assessment['early_check']:
                early = assessment['early_check']
                if early['status'] == 'HEALTHY':
                    print()
                    print("EARLY INDICATOR (Last 5 trades):")
                    print(f"  ✅ Rolling expectancy: ${early['rolling']['expectancy']:+.2f}")
                    print(f"  ✅ Rolling win rate: {early['rolling']['win_rate']*100:.0f}%")
                    
                    # Show trend if available
                    if early.get('trend'):
                        trend = early['trend']
                        exp_emoji = '📈' if trend['expectancy_trend'] == 'IMPROVING' else '📉' if trend['expectancy_trend'] == 'DETERIORATING' else '➡️'
                        wr_emoji = '📈' if trend['win_rate_trend'] == 'IMPROVING' else '📉' if trend['win_rate_trend'] == 'DETERIORATING' else '➡️'
                        
                        print(f"  {exp_emoji} Expectancy trend: {trend['expectancy_trend']}")
                        print(f"  {wr_emoji} Win rate trend: {trend['win_rate_trend']}")
                    
                    print(f"  Status: HEALTHY")
        
        elif assessment['status'] == 'WARNING':
            print("⚠️  EARLY WARNING DETECTED")
            print()
            print(f"RECENT PERFORMANCE (Last {assessment['rolling']['trades']} trades):")
            print(f"  Expectancy: ${assessment['rolling']['expectancy']:+.2f} (warning: <$0.30)")
            print(f"  Win rate: {assessment['rolling']['win_rate']*100:.0f}% (warning: <40%)")
            print(f"  Record: {assessment['rolling']['wins']}W / {assessment['rolling']['losses']}L")
            
            # Show trend analysis
            if assessment.get('trend'):
                trend = assessment['trend']
                print()
                print(f"TREND ANALYSIS (Over {trend['windows']} consecutive windows):")
                
                exp_emoji = '📈' if trend['expectancy_trend'] == 'IMPROVING' else '📉' if trend['expectancy_trend'] == 'DETERIORATING' else '➡️'
                wr_emoji = '📈' if trend['win_rate_trend'] == 'IMPROVING' else '📉' if trend['win_rate_trend'] == 'DETERIORATING' else '➡️'
                
                print(f"  {exp_emoji} Expectancy: {trend['expectancy_trend']} (Δ${trend['exp_change']:+.2f})")
                print(f"  {wr_emoji} Win rate: {trend['win_rate_trend']} (Δ{trend['wr_change']*100:+.0f}%)")
                
                if trend['expectancy_trend'] == 'DETERIORATING' and trend['win_rate_trend'] == 'DETERIORATING':
                    print()
                    print("  🔴 BOTH metrics deteriorating — High priority monitoring")
                elif trend['expectancy_trend'] == 'IMPROVING' or trend['win_rate_trend'] == 'IMPROVING':
                    print()
                    print("  🟢 Recovery signs detected — Continue monitoring")
            
            print()
            print("WARNINGS:")
            for w in assessment['warnings']:
                print(f"  ⚠️  {w}")
            print()
            print("ACTION: CONTINUE MONITORING")
            print("Velocity optimizations remain active")
            print("Full revert will trigger at 10 trades if trend continues")
        
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
