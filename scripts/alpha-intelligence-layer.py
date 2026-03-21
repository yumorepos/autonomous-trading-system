#!/usr/bin/env python3
"""
Alpha Intelligence Layer
Learns which strategies, sources, and market conditions produce highest risk-adjusted returns
Dynamically reweights signal scoring based on historical edge
Evolves toward higher-quality, more predictive trading opportunities
"""

import json
import sys
import numpy as np
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
from dataclasses import dataclass, asdict

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.runtime import WORKSPACE_ROOT as WORKSPACE, LOGS_DIR, DATA_DIR
from models.trade_schema import normalize_trade_record, validate_trade_record
ALPHA_STATE = LOGS_DIR / "alpha-intelligence-state.json"
PERFORMANCE_DB = LOGS_DIR / "alpha-performance-db.json"
SIGNAL_WEIGHTS = LOGS_DIR / "dynamic-signal-weights.json"
ALPHA_REPORT = WORKSPACE / "ALPHA_INTELLIGENCE_REPORT.md"
PAPER_TRADES = LOGS_DIR / "phase1-paper-trades.jsonl"

# Performance Tracking Windows
WINDOWS = {
    'short': 7,      # 7 days
    'medium': 30,    # 30 days
    'long': 90       # 90 days
}

# Market Regime Thresholds
REGIME_THRESHOLDS = {
    'volatility_high': 0.03,    # 3% daily vol = high
    'volatility_low': 0.01,     # 1% daily vol = low
    'trend_strong': 0.02,       # 2% daily move = trending
    'trend_weak': 0.005         # 0.5% daily move = ranging
}

# Multi-Factor Confirmation
CONFIRMATION_BONUS = {
    '2_sources': 1.2,    # 20% bonus for 2 sources
    '3_sources': 1.5,    # 50% bonus for 3+ sources
    'cross_strategy': 1.3,  # 30% bonus for cross-strategy confirmation
    'regime_fit': 1.4    # 40% bonus if strategy fits regime
}

# Signal Quality Thresholds
QUALITY_THRESHOLDS = {
    'min_trades': 10,           # Min trades for evaluation
    'min_sharpe': 0.5,          # Min Sharpe to keep
    'min_win_rate': 45.0,       # Min 45% WR to keep
    'min_profit_factor': 1.0,   # Min PF to keep
    'elimination_cycles': 3     # 3 cycles below threshold → eliminate
}


@dataclass
class MarketRegime:
    regime_type: str  # TREND_UP, TREND_DOWN, RANGE, HIGH_VOL, LOW_VOL
    volatility: float
    trend_strength: float
    timestamp: str


@dataclass
class SignalPerformance:
    source: str
    strategy_type: str
    regime: str
    trades: int
    wins: int
    losses: int
    total_pnl: float
    sharpe_ratio: float
    profit_factor: float
    avg_duration_hours: float
    last_updated: str


class AlphaIntelligenceLayer:
    """Adaptive learning system for signal quality optimization"""
    
    def __init__(self):
        self.state = self.load_state()
        self.performance_db = self.load_performance_db()
        self.weights = self.load_weights()
        self.trades = self.load_trades()
    
    def load_state(self) -> Dict:
        """Load current alpha intelligence state"""
        if ALPHA_STATE.exists():
            with open(ALPHA_STATE) as f:
                return json.load(f)
        
        return {
            'last_update': None,
            'current_regime': None,
            'regime_history': [],
            'signal_types_eliminated': [],
            'learning_cycles': 0,
            'total_signals_evaluated': 0,
            'adaptations_made': []
        }
    
    def save_state(self):
        """Save current state"""
        self.state['last_update'] = datetime.now(timezone.utc).isoformat()
        with open(ALPHA_STATE, 'w') as f:
            json.dump(self.state, f, indent=2)
    
    def load_performance_db(self) -> Dict:
        """Load performance database"""
        if PERFORMANCE_DB.exists():
            with open(PERFORMANCE_DB) as f:
                return json.load(f)
        
        return {
            'by_source': {},
            'by_strategy': {},
            'by_regime': {},
            'by_source_strategy': {},
            'by_source_regime': {},
            'by_strategy_regime': {}
        }
    
    def save_performance_db(self):
        """Save performance database"""
        with open(PERFORMANCE_DB, 'w') as f:
            json.dump(self.performance_db, f, indent=2)
    
    def load_weights(self) -> Dict:
        """Load dynamic signal weights"""
        if SIGNAL_WEIGHTS.exists():
            with open(SIGNAL_WEIGHTS) as f:
                return json.load(f)
        
        # Default weights (will be learned)
        return {
            'sources': {
                'hyperliquid': 1.0,
                'polymarket': 1.0,
                'social': 0.8  # Lower initial weight
            },
            'strategies': {
                'funding_arbitrage': 1.0,
                'polymarket_arbitrage': 1.0,
                'social_sentiment': 0.7
            },
            'regimes': {
                'TREND_UP': 1.0,
                'TREND_DOWN': 1.0,
                'RANGE': 1.0,
                'HIGH_VOL': 1.0,
                'LOW_VOL': 1.0
            },
            'last_updated': None
        }
    
    def save_weights(self):
        """Save dynamic weights"""
        self.weights['last_updated'] = datetime.now(timezone.utc).isoformat()
        with open(SIGNAL_WEIGHTS, 'w') as f:
            json.dump(self.weights, f, indent=2)
    
    def load_trades(self) -> List[Dict]:
        """Load all paper trades"""
        if not PAPER_TRADES.exists():
            return []
        
        trades = []
        with open(PAPER_TRADES) as f:
            for line in f:
                if line.strip():
                    trade = normalize_trade_record(json.loads(line))
                    if not validate_trade_record(trade, context='alpha-intelligence.load_trades'):
                        continue
                    trades.append(trade)

        return trades
    
    # === MARKET REGIME DETECTION ===
    
    def detect_market_regime(self) -> MarketRegime:
        """Detect current market regime"""
        
        # For now, use simple heuristics
        # TODO: Enhance with real market data (BTC price, VIX, etc.)
        
        # Get recent trades to estimate volatility
        recent_trades = [t for t in self.trades if t['status'] == 'CLOSED']
        
        if len(recent_trades) < 5:
            # Not enough data, assume RANGE/LOW_VOL
            return MarketRegime(
                regime_type='RANGE',
                volatility=0.015,  # Medium vol
                trend_strength=0.003,  # Weak trend
                timestamp=datetime.now(timezone.utc).isoformat()
            )
        
        # Calculate volatility from P&L
        pnls = [((t.get('realized_pnl_pct') or 0) / 100) for t in recent_trades[-20:]]  # Last 20 trades
        volatility = np.std(pnls) if len(pnls) > 1 else 0.015
        
        # Calculate trend from cumulative P&L
        cumulative = np.cumsum(pnls)
        trend_strength = abs(cumulative[-1] - cumulative[0]) / len(pnls) if len(pnls) > 0 else 0
        
        # Classify regime
        if volatility > REGIME_THRESHOLDS['volatility_high']:
            regime_type = 'HIGH_VOL'
        elif volatility < REGIME_THRESHOLDS['volatility_low']:
            regime_type = 'LOW_VOL'
        elif trend_strength > REGIME_THRESHOLDS['trend_strong']:
            if cumulative[-1] > cumulative[0]:
                regime_type = 'TREND_UP'
            else:
                regime_type = 'TREND_DOWN'
        else:
            regime_type = 'RANGE'
        
        return MarketRegime(
            regime_type=regime_type,
            volatility=volatility,
            trend_strength=trend_strength,
            timestamp=datetime.now(timezone.utc).isoformat()
        )
    
    # === PERFORMANCE TRACKING ===
    
    def update_performance_metrics(self):
        """Update all performance metrics from trade history"""
        
        closed_trades = [t for t in self.trades if t['status'] == 'CLOSED']
        
        if not closed_trades:
            return
        
        # Group trades by dimensions
        by_source = defaultdict(list)
        by_strategy = defaultdict(list)
        by_regime = defaultdict(list)
        
        for trade in closed_trades:
            raw = trade.get('raw', {})
            source = raw.get('signal', {}).get('source', raw.get('exchange', 'unknown'))
            strategy = raw.get('signal', {}).get('signal_type', raw.get('strategy', 'unknown'))
            # Regime at trade time (TODO: track this in trades)
            regime = 'RANGE'  # Default for now
            
            by_source[source].append(trade)
            by_strategy[strategy].append(trade)
            by_regime[regime].append(trade)
        
        # Calculate metrics per dimension
        self.performance_db['by_source'] = {
            source: self.calculate_metrics(trades)
            for source, trades in by_source.items()
        }
        
        self.performance_db['by_strategy'] = {
            strategy: self.calculate_metrics(trades)
            for strategy, trades in by_strategy.items()
        }
        
        self.performance_db['by_regime'] = {
            regime: self.calculate_metrics(trades)
            for regime, trades in by_regime.items()
        }
    
    def calculate_metrics(self, trades: List[Dict]) -> Dict:
        """Calculate performance metrics for a trade set"""
        if not trades:
            return {
                'trades': 0,
                'wins': 0,
                'losses': 0,
                'win_rate': 0,
                'total_pnl': 0,
                'avg_pnl': 0,
                'sharpe_ratio': 0,
                'profit_factor': 0,
                'avg_duration_hours': 0
            }
        
        wins = [t for t in trades if (t.get('realized_pnl_usd') or 0) > 0]
        losses = [t for t in trades if (t.get('realized_pnl_usd') or 0) <= 0]
        
        pnls = [(t.get('realized_pnl_usd') or 0) for t in trades]
        avg_pnl = sum(pnls) / len(pnls)
        
        # Sharpe ratio
        if len(pnls) > 1:
            std_pnl = np.std(pnls)
            sharpe = (avg_pnl / std_pnl) if std_pnl > 0 else 0
        else:
            sharpe = 0
        
        # Profit factor
        gross_profit = sum((t.get('realized_pnl_usd') or 0) for t in wins) if wins else 0
        gross_loss = abs(sum((t.get('realized_pnl_usd') or 0) for t in losses)) if losses else 1
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
        
        # Average duration
        durations = []
        for t in trades:
            if t.get('entry_timestamp') and t.get('exit_timestamp'):
                entry = datetime.fromisoformat(t['entry_timestamp'].replace('Z', '+00:00'))
                exit = datetime.fromisoformat(t['exit_timestamp'].replace('Z', '+00:00'))
                duration = (exit - entry).total_seconds() / 3600  # hours
                durations.append(duration)
        
        avg_duration = sum(durations) / len(durations) if durations else 0
        
        return {
            'trades': len(trades),
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': (len(wins) / len(trades)) * 100,
            'total_pnl': sum(pnls),
            'avg_pnl': avg_pnl,
            'sharpe_ratio': sharpe,
            'profit_factor': profit_factor,
            'avg_duration_hours': avg_duration
        }
    
    # === DYNAMIC WEIGHT LEARNING ===
    
    def learn_source_weights(self):
        """Learn optimal weights for each data source"""
        
        by_source = self.performance_db.get('by_source', {})
        
        if not by_source:
            return
        
        # Calculate relative performance
        sharpe_scores = {source: metrics['sharpe_ratio'] 
                        for source, metrics in by_source.items()
                        if metrics['trades'] >= QUALITY_THRESHOLDS['min_trades']}
        
        if not sharpe_scores:
            return
        
        # Normalize to weights (softmax-like)
        max_sharpe = max(sharpe_scores.values()) if sharpe_scores else 1
        min_sharpe = min(sharpe_scores.values()) if sharpe_scores else 0
        range_sharpe = max_sharpe - min_sharpe if max_sharpe > min_sharpe else 1
        
        for source, sharpe in sharpe_scores.items():
            # Normalize to 0.5-1.5 range
            normalized = 0.5 + (sharpe - min_sharpe) / range_sharpe
            self.weights['sources'][source] = normalized
        
        self.state['adaptations_made'].append({
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'type': 'source_weights',
            'weights': self.weights['sources'].copy()
        })
    
    def learn_strategy_weights(self):
        """Learn optimal weights for each strategy type"""
        
        by_strategy = self.performance_db.get('by_strategy', {})
        
        if not by_strategy:
            return
        
        # Calculate relative performance
        sharpe_scores = {strategy: metrics['sharpe_ratio']
                        for strategy, metrics in by_strategy.items()
                        if metrics['trades'] >= QUALITY_THRESHOLDS['min_trades']}
        
        if not sharpe_scores:
            return
        
        # Normalize to weights
        max_sharpe = max(sharpe_scores.values()) if sharpe_scores else 1
        min_sharpe = min(sharpe_scores.values()) if sharpe_scores else 0
        range_sharpe = max_sharpe - min_sharpe if max_sharpe > min_sharpe else 1
        
        for strategy, sharpe in sharpe_scores.items():
            normalized = 0.5 + (sharpe - min_sharpe) / range_sharpe
            self.weights['strategies'][strategy] = normalized
        
        self.state['adaptations_made'].append({
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'type': 'strategy_weights',
            'weights': self.weights['strategies'].copy()
        })
    
    def learn_regime_weights(self):
        """Learn optimal weights for each market regime"""
        
        by_regime = self.performance_db.get('by_regime', {})
        
        if not by_regime:
            return
        
        # Similar to above, learn regime-specific weights
        sharpe_scores = {regime: metrics['sharpe_ratio']
                        for regime, metrics in by_regime.items()
                        if metrics['trades'] >= QUALITY_THRESHOLDS['min_trades']}
        
        if not sharpe_scores:
            return
        
        max_sharpe = max(sharpe_scores.values()) if sharpe_scores else 1
        min_sharpe = min(sharpe_scores.values()) if sharpe_scores else 0
        range_sharpe = max_sharpe - min_sharpe if max_sharpe > min_sharpe else 1
        
        for regime, sharpe in sharpe_scores.items():
            normalized = 0.5 + (sharpe - min_sharpe) / range_sharpe
            self.weights['regimes'][regime] = normalized
    
    # === SIGNAL QUALITY EVOLUTION ===
    
    def identify_low_performers(self) -> List[Dict]:
        """Identify signal types to eliminate"""
        
        candidates = []
        
        # Check strategies
        for strategy, metrics in self.performance_db.get('by_strategy', {}).items():
            if metrics['trades'] < QUALITY_THRESHOLDS['min_trades']:
                continue
            
            failures = []
            
            if metrics['sharpe_ratio'] < QUALITY_THRESHOLDS['min_sharpe']:
                failures.append(f"Sharpe {metrics['sharpe_ratio']:.2f} < {QUALITY_THRESHOLDS['min_sharpe']}")
            
            if metrics['win_rate'] < QUALITY_THRESHOLDS['min_win_rate']:
                failures.append(f"WR {metrics['win_rate']:.1f}% < {QUALITY_THRESHOLDS['min_win_rate']}%")
            
            if metrics['profit_factor'] < QUALITY_THRESHOLDS['min_profit_factor']:
                failures.append(f"PF {metrics['profit_factor']:.2f} < {QUALITY_THRESHOLDS['min_profit_factor']}")
            
            if failures:
                candidates.append({
                    'type': 'strategy',
                    'name': strategy,
                    'failures': failures,
                    'metrics': metrics
                })
        
        return candidates
    
    def eliminate_signal_types(self, candidates: List[Dict]):
        """Eliminate low-performing signal types"""
        
        for candidate in candidates:
            # Check if already flagged
            existing = [e for e in self.state.get('signal_types_eliminated', [])
                       if e['name'] == candidate['name']]
            
            if existing:
                # Already eliminated, skip
                continue
            
            # Add to elimination list
            self.state['signal_types_eliminated'].append({
                'name': candidate['name'],
                'type': candidate['type'],
                'eliminated_at': datetime.now(timezone.utc).isoformat(),
                'reason': ' | '.join(candidate['failures']),
                'final_metrics': candidate['metrics']
            })
            
            # Set weight to 0
            if candidate['type'] == 'strategy':
                self.weights['strategies'][candidate['name']] = 0
    
    # === MULTI-FACTOR CONFIRMATION ===
    
    def apply_multifactor_bonus(self, signal: Dict, other_signals: List[Dict]) -> float:
        """Apply bonus for multi-factor confirmation"""
        
        bonuses = []
        
        # Count unique sources confirming
        signal_source = signal.get('source', '')
        signal_asset = signal.get('asset', '')
        signal_direction = signal.get('direction', '')
        
        confirming_sources = set()
        confirming_strategies = set()
        
        for other in other_signals:
            if (other.get('asset') == signal_asset and
                other.get('direction') == signal_direction):
                
                confirming_sources.add(other.get('source', ''))
                confirming_strategies.add(other.get('signal_type', ''))
        
        # Source confirmation bonus
        unique_sources = len(confirming_sources)
        if unique_sources >= 3:
            bonuses.append(('3+ sources', CONFIRMATION_BONUS['3_sources']))
        elif unique_sources == 2:
            bonuses.append(('2 sources', CONFIRMATION_BONUS['2_sources']))
        
        # Cross-strategy confirmation
        if len(confirming_strategies) > 1:
            bonuses.append(('cross-strategy', CONFIRMATION_BONUS['cross_strategy']))
        
        # Regime fit bonus
        current_regime = self.state.get('current_regime', {})
        if current_regime:
            strategy_type = signal.get('signal_type', '')
            regime_type = current_regime.get('regime_type', '')
            
            # Example: funding arbitrage works well in RANGE markets
            if strategy_type == 'funding_arbitrage' and regime_type == 'RANGE':
                bonuses.append(('regime-fit', CONFIRMATION_BONUS['regime_fit']))
        
        # Multiply bonuses
        total_bonus = 1.0
        for name, bonus in bonuses:
            total_bonus *= bonus
        
        return total_bonus
    
    # === SIGNAL REWEIGHTING ===
    
    def reweight_signal(self, signal: Dict, other_signals: List[Dict] = None) -> Dict:
        """Apply learned weights to signal score"""
        
        original_score = signal.get('ev_score', 0)
        
        # Get base weights
        source_weight = self.weights['sources'].get(signal.get('source', ''), 1.0)
        strategy_weight = self.weights['strategies'].get(signal.get('signal_type', ''), 1.0)
        
        # Current regime weight
        current_regime = self.state.get('current_regime', {})
        regime_weight = 1.0
        if current_regime:
            regime_weight = self.weights['regimes'].get(current_regime.get('regime_type', ''), 1.0)
        
        # Multi-factor bonus
        multifactor_bonus = 1.0
        if other_signals:
            multifactor_bonus = self.apply_multifactor_bonus(signal, other_signals)
        
        # Final adjusted score
        adjusted_score = original_score * source_weight * strategy_weight * regime_weight * multifactor_bonus
        
        signal['ev_score_adjusted'] = adjusted_score
        signal['adjustments'] = {
            'source_weight': source_weight,
            'strategy_weight': strategy_weight,
            'regime_weight': regime_weight,
            'multifactor_bonus': multifactor_bonus,
            'total_multiplier': source_weight * strategy_weight * regime_weight * multifactor_bonus
        }
        
        return signal
    
    # === ORCHESTRATION ===
    
    def run_learning_cycle(self):
        """Execute one learning cycle"""
        
        print("=" * 80)
        print("ALPHA INTELLIGENCE LEARNING CYCLE")
        print(f"Cycle Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S EDT')}")
        print("=" * 80)
        print()
        
        # Detect current regime
        print("1. Detecting market regime...")
        regime = self.detect_market_regime()
        self.state['current_regime'] = asdict(regime)
        self.state['regime_history'].append(asdict(regime))
        print(f"   Regime: {regime.regime_type} (vol: {regime.volatility:.3f}, trend: {regime.trend_strength:.3f})")
        print()
        
        # Update performance metrics
        print("2. Updating performance metrics...")
        self.update_performance_metrics()
        
        by_source = self.performance_db.get('by_source', {})
        by_strategy = self.performance_db.get('by_strategy', {})
        
        print(f"   Sources tracked: {len(by_source)}")
        print(f"   Strategies tracked: {len(by_strategy)}")
        print()
        
        # Learn optimal weights
        print("3. Learning optimal weights...")
        self.learn_source_weights()
        self.learn_strategy_weights()
        self.learn_regime_weights()
        print("   ✅ Weights updated")
        print()
        
        # Identify low performers
        print("4. Identifying low performers...")
        candidates = self.identify_low_performers()
        print(f"   Found {len(candidates)} candidates for elimination")
        
        if candidates:
            for c in candidates:
                print(f"   ⚠️ {c['name']}: {' | '.join(c['failures'])}")
            
            self.eliminate_signal_types(candidates)
        print()
        
        # Update state
        self.state['learning_cycles'] += 1
        
        # Save everything
        self.save_state()
        self.save_performance_db()
        self.save_weights()
        
        # Generate report
        report = self.generate_report()
        with open(ALPHA_REPORT, 'w') as f:
            f.write(report)
        
        print("=" * 80)
        print(f"✅ Learning cycle complete")
        print(f"📄 Report: {ALPHA_REPORT}")
        print("=" * 80)
    
    def generate_report(self) -> str:
        """Generate alpha intelligence report"""
        
        lines = []
        lines.append("# ALPHA INTELLIGENCE REPORT")
        lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M EDT')}")
        lines.append(f"**Learning Cycles:** {self.state['learning_cycles']}")
        lines.append("")
        
        # Current regime
        regime = self.state.get('current_regime', {})
        if regime:
            lines.append("## Current Market Regime")
            lines.append("")
            lines.append(f"**Type:** {regime.get('regime_type', 'UNKNOWN')}")
            lines.append(f"**Volatility:** {regime.get('volatility', 0):.3f}")
            lines.append(f"**Trend Strength:** {regime.get('trend_strength', 0):.3f}")
            lines.append("")
            lines.append("---")
            lines.append("")
        
        # Learned weights
        lines.append("## Learned Weights")
        lines.append("")
        
        lines.append("### Source Weights")
        for source, weight in sorted(self.weights['sources'].items(), key=lambda x: x[1], reverse=True):
            lines.append(f"- **{source}:** {weight:.2f}")
        lines.append("")
        
        lines.append("### Strategy Weights")
        for strategy, weight in sorted(self.weights['strategies'].items(), key=lambda x: x[1], reverse=True):
            lines.append(f"- **{strategy}:** {weight:.2f}")
        lines.append("")
        
        lines.append("---")
        lines.append("")
        
        # Performance by source
        lines.append("## Performance by Source")
        lines.append("")
        
        for source, metrics in self.performance_db.get('by_source', {}).items():
            lines.append(f"### {source}")
            lines.append(f"**Trades:** {metrics['trades']}")
            lines.append(f"**Win Rate:** {metrics['win_rate']:.1f}%")
            lines.append(f"**Sharpe Ratio:** {metrics['sharpe_ratio']:.2f}")
            lines.append(f"**Profit Factor:** {metrics['profit_factor']:.2f}")
            lines.append(f"**Total P&L:** ${metrics['total_pnl']:.2f}")
            lines.append("")
        
        lines.append("---")
        lines.append("")
        
        # Eliminated signal types
        eliminated = self.state.get('signal_types_eliminated', [])
        if eliminated:
            lines.append("## Eliminated Signal Types")
            lines.append("")
            for item in eliminated:
                lines.append(f"### {item['name']}")
                lines.append(f"**Eliminated:** {item['eliminated_at']}")
                lines.append(f"**Reason:** {item['reason']}")
                lines.append("")
        
        return "\n".join(lines)


def main():
    alpha = AlphaIntelligenceLayer()
    alpha.run_learning_cycle()


if __name__ == "__main__":
    main()
