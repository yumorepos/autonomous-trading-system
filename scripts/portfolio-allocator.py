#!/usr/bin/env python3
"""
Portfolio Capital Allocator
Dynamically assigns position sizing and portfolio weight to PROMOTED/LIVE strategies
based on risk-adjusted performance, correlation, and portfolio-level constraints
"""

import json
import sys
import numpy as np
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple
from collections import defaultdict

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.runtime import WORKSPACE_ROOT as WORKSPACE, LOGS_DIR, DATA_DIR
from models.trade_schema import normalize_trade_record, validate_trade_record
STRATEGY_REGISTRY = LOGS_DIR / "strategy-registry.json"
PAPER_TRADES = LOGS_DIR / "phase1-paper-trades.jsonl"
ALLOCATION_CONFIG = LOGS_DIR / "portfolio-allocation.json"
ALLOCATION_HISTORY = LOGS_DIR / "allocation-history.jsonl"
ALLOCATION_REPORT = WORKSPACE / "PORTFOLIO_ALLOCATION_REPORT.md"

# Portfolio-Level Risk Limits
PORTFOLIO_LIMITS = {
    'max_total_exposure': 0.50,      # Max 50% of capital deployed
    'max_strategy_weight': 0.20,     # Max 20% per strategy
    'min_strategy_weight': 0.02,     # Min 2% if allocated
    'max_correlation': 0.70,         # Reduce allocation if correlation > 0.7
    'max_portfolio_drawdown': 0.15,  # Max 15% portfolio drawdown
    'rebalance_threshold': 0.10      # Rebalance if weights drift > 10%
}

# Risk-Adjusted Scoring Weights
SCORING_WEIGHTS = {
    'sharpe_ratio': 0.30,
    'profit_factor': 0.25,
    'expectancy': 0.20,
    'win_rate': 0.15,
    'max_drawdown': 0.10  # Inverted (lower is better)
}


class PortfolioAllocator:
    """Manages dynamic capital allocation across strategies"""
    
    def __init__(self, total_capital: float = 97.80):
        self.total_capital = total_capital
        self.registry = self.load_registry()
        self.trades_by_strategy = self.load_trades()
        self.current_allocation = self.load_allocation()
    
    def load_registry(self) -> Dict:
        if STRATEGY_REGISTRY.exists():
            with open(STRATEGY_REGISTRY) as f:
                return json.load(f)
        return {'strategies': {}}
    
    def load_trades(self) -> Dict[str, List[Dict]]:
        """Load closed trades grouped by strategy"""
        if not PAPER_TRADES.exists():
            return {}
        
        trades = defaultdict(list)
        with open(PAPER_TRADES) as f:
            for line in f:
                if line.strip():
                    trade = normalize_trade_record(json.loads(line))
                    if not validate_trade_record(trade, context='portfolio-allocator.load_trades'):
                        continue
                    if trade['status'] == 'CLOSED':
                        raw = trade.get('raw', {})
                        strategy = raw.get('signal', {}).get('signal_type', raw.get('strategy', 'unknown'))
                        trades[strategy].append(trade)
        
        return dict(trades)
    
    def load_allocation(self) -> Dict:
        """Load current allocation config"""
        if ALLOCATION_CONFIG.exists():
            with open(ALLOCATION_CONFIG) as f:
                return json.load(f)
        return {
            'timestamp': None,
            'total_capital': self.total_capital,
            'allocated_capital': 0,
            'strategies': {},
            'portfolio_metrics': {}
        }
    
    def save_allocation(self):
        """Save allocation config"""
        self.current_allocation['timestamp'] = datetime.now(timezone.utc).isoformat()
        
        with open(ALLOCATION_CONFIG, 'w') as f:
            json.dump(self.current_allocation, f, indent=2)
        
        # Log to history
        with open(ALLOCATION_HISTORY, 'a') as f:
            f.write(json.dumps(self.current_allocation) + '\n')
    
    def calculate_metrics(self, trades: List[Dict]) -> Dict:
        """Calculate risk-adjusted metrics for a strategy"""
        if not trades:
            return None
        
        returns = [(t.get('realized_pnl_usd') or 0) for t in trades]
        wins = [r for r in returns if r > 0]
        losses = [abs(r) for r in returns if r < 0]
        
        # Win rate
        win_rate = (len(wins) / len(returns)) * 100 if returns else 0
        
        # Expectancy
        expectancy = sum(returns) / len(returns)
        
        # Profit factor
        gross_profit = sum(wins) if wins else 0
        gross_loss = sum(losses) if losses else 1
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
        
        # Sharpe ratio
        avg_return = expectancy
        if len(returns) >= 5:
            variance = sum((r - avg_return) ** 2 for r in returns) / len(returns)
            std_dev = variance ** 0.5
            sharpe = (avg_return / std_dev) if std_dev > 0 else 0
        else:
            sharpe = 0
        
        # Max drawdown
        cumulative = 0
        peak = 0
        max_dd = 0
        
        for r in returns:
            cumulative += r
            peak = max(peak, cumulative)
            dd = ((peak - cumulative) / peak) if peak > 0 else 0
            max_dd = max(max_dd, dd)
        
        return {
            'trades': len(returns),
            'win_rate': win_rate,
            'expectancy': expectancy,
            'profit_factor': profit_factor,
            'sharpe_ratio': sharpe,
            'max_drawdown': max_dd * 100,
            'total_pnl': sum(returns)
        }
    
    def calculate_risk_score(self, metrics: Dict) -> float:
        """Calculate composite risk-adjusted score (0-100)"""
        if not metrics or metrics['trades'] < 10:
            return 0
        
        # Normalize each metric to 0-1 scale
        normalized = {}
        
        # Sharpe (0-3 -> 0-1)
        normalized['sharpe_ratio'] = min(metrics['sharpe_ratio'] / 3.0, 1.0)
        
        # Profit factor (0-3 -> 0-1)
        normalized['profit_factor'] = min(metrics['profit_factor'] / 3.0, 1.0)
        
        # Expectancy ($0-1 -> 0-1)
        normalized['expectancy'] = min(max(metrics['expectancy'], 0) / 1.0, 1.0)
        
        # Win rate (0-100 -> 0-1)
        normalized['win_rate'] = metrics['win_rate'] / 100.0
        
        # Max drawdown (inverted, 0-20% -> 1-0)
        normalized['max_drawdown'] = max(0, 1.0 - (metrics['max_drawdown'] / 20.0))
        
        # Weighted sum
        score = sum(normalized[k] * SCORING_WEIGHTS[k] for k in SCORING_WEIGHTS)
        
        return score * 100
    
    def calculate_correlation_matrix(self, strategies: List[str]) -> Dict[Tuple[str, str], float]:
        """Calculate pairwise correlation between strategies"""
        correlations = {}
        
        for i, strat1 in enumerate(strategies):
            for strat2 in strategies[i+1:]:
                trades1 = self.trades_by_strategy.get(strat1, [])
                trades2 = self.trades_by_strategy.get(strat2, [])
                
                if len(trades1) < 10 or len(trades2) < 10:
                    correlations[(strat1, strat2)] = 0
                    continue
                
                # Simple correlation based on trade timing and P&L
                returns1 = [(t.get('realized_pnl_usd') or 0) for t in trades1]
                returns2 = [(t.get('realized_pnl_usd') or 0) for t in trades2]
                
                # Pad shorter series
                max_len = max(len(returns1), len(returns2))
                returns1 += [0] * (max_len - len(returns1))
                returns2 += [0] * (max_len - len(returns2))
                
                # Pearson correlation
                if len(returns1) > 1 and len(returns2) > 1:
                    corr = np.corrcoef(returns1, returns2)[0, 1]
                    correlations[(strat1, strat2)] = corr if not np.isnan(corr) else 0
                else:
                    correlations[(strat1, strat2)] = 0
        
        return correlations
    
    def calculate_optimal_weights(self, eligible_strategies: Dict[str, Dict]) -> Dict[str, float]:
        """Calculate optimal portfolio weights using risk-adjusted scores and correlation"""
        
        if not eligible_strategies:
            return {}
        
        strategy_names = list(eligible_strategies.keys())
        
        # Get risk scores
        risk_scores = {name: data['risk_score'] for name, data in eligible_strategies.items()}
        
        # Get correlation matrix
        correlations = self.calculate_correlation_matrix(strategy_names)
        
        # Initial weights proportional to risk scores
        total_score = sum(risk_scores.values())
        raw_weights = {name: score / total_score for name, score in risk_scores.items()}
        
        # Adjust for correlation (reduce weight for highly correlated pairs)
        adjusted_weights = raw_weights.copy()
        
        for (strat1, strat2), corr in correlations.items():
            if abs(corr) > PORTFOLIO_LIMITS['max_correlation']:
                # Reduce weight of lower-scoring strategy
                if risk_scores[strat1] < risk_scores[strat2]:
                    penalty = abs(corr) - PORTFOLIO_LIMITS['max_correlation']
                    adjusted_weights[strat1] *= (1.0 - penalty)
                else:
                    penalty = abs(corr) - PORTFOLIO_LIMITS['max_correlation']
                    adjusted_weights[strat2] *= (1.0 - penalty)
        
        # Renormalize
        total_adjusted = sum(adjusted_weights.values())
        normalized_weights = {name: w / total_adjusted for name, w in adjusted_weights.items()}
        
        # Apply constraints
        final_weights = {}
        
        for name, weight in normalized_weights.items():
            # Min/max weight constraints
            if weight < PORTFOLIO_LIMITS['min_strategy_weight']:
                continue  # Exclude strategies below min weight
            
            final_weights[name] = min(weight, PORTFOLIO_LIMITS['max_strategy_weight'])
        
        # Renormalize after constraints
        if final_weights:
            total_final = sum(final_weights.values())
            final_weights = {name: w / total_final for name, w in final_weights.items()}
        
        return final_weights
    
    def allocate_capital(self) -> Dict:
        """Main allocation logic"""
        
        print("=" * 80)
        print("PORTFOLIO CAPITAL ALLOCATOR")
        print(f"Allocation Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S EDT')}")
        print("=" * 80)
        print()
        
        print(f"[MONEY] Total Capital: ${self.total_capital:.2f}")
        print()
        
        # Get PROMOTED and LIVE strategies
        eligible_strategies = {}
        
        for name, strategy in self.registry['strategies'].items():
            stage = strategy.get('stage', 'VALIDATE')
            
            if stage not in ['PROMOTE', 'LIVE']:
                continue
            
            # Get trades and metrics
            trades = self.trades_by_strategy.get(name, [])
            
            if len(trades) < 10:
                print(f"[SKIP]  {name}: Skipped (only {len(trades)} trades)")
                continue
            
            metrics = self.calculate_metrics(trades)
            risk_score = self.calculate_risk_score(metrics)
            
            eligible_strategies[name] = {
                'stage': stage,
                'metrics': metrics,
                'risk_score': risk_score
            }
            
            print(f"[OK] {name}: Stage={stage} | Score={risk_score:.1f} | Sharpe={metrics['sharpe_ratio']:.2f}")
        
        print()
        print(f"[STATS] Eligible Strategies: {len(eligible_strategies)}")
        print()
        
        if not eligible_strategies:
            print("[WARN] No strategies eligible for capital allocation")
            # Return empty allocation
            return {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'total_capital': self.total_capital,
                'allocated_capital': 0,
                'cash_reserve': self.total_capital,
                'strategies': {},
                'portfolio_metrics': {
                    'sharpe_ratio': 0,
                    'expectancy': 0,
                    'num_strategies': 0,
                    'diversification_ratio': 1.0
                }
            }
        
        # Calculate optimal weights
        weights = self.calculate_optimal_weights(eligible_strategies)
        
        print("[TARGET] Optimal Weights:")
        for name, weight in sorted(weights.items(), key=lambda x: x[1], reverse=True):
            print(f"   {name}: {weight*100:.1f}%")
        print()
        
        # Calculate capital allocation
        max_exposure = self.total_capital * PORTFOLIO_LIMITS['max_total_exposure']
        
        allocations = {}
        total_allocated = 0
        
        for name, weight in weights.items():
            allocated = max_exposure * weight
            allocations[name] = {
                'weight': weight,
                'capital': allocated,
                'stage': eligible_strategies[name]['stage'],
                'risk_score': eligible_strategies[name]['risk_score'],
                'metrics': eligible_strategies[name]['metrics']
            }
            total_allocated += allocated
        
        print(f"[MONEY] Total Allocated: ${total_allocated:.2f} ({total_allocated/self.total_capital*100:.1f}%)")
        print(f"[MONEY] Cash Reserve: ${self.total_capital - total_allocated:.2f}")
        print()
        
        # Calculate portfolio metrics
        portfolio_sharpe = np.average(
            [s['metrics']['sharpe_ratio'] for s in eligible_strategies.values()],
            weights=list(weights.values())
        )
        
        portfolio_expectancy = sum(
            allocations[name]['metrics']['expectancy'] * allocations[name]['weight']
            for name in allocations
        )
        
        # Update allocation
        self.current_allocation = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'total_capital': self.total_capital,
            'allocated_capital': total_allocated,
            'cash_reserve': self.total_capital - total_allocated,
            'strategies': allocations,
            'portfolio_metrics': {
                'sharpe_ratio': portfolio_sharpe,
                'expectancy': portfolio_expectancy,
                'num_strategies': len(allocations),
                'diversification_ratio': 1.0 / max(weights.values()) if weights else 1
            }
        }
        
        self.save_allocation()
        
        print("=" * 80)
        print(f"[OK] Allocation saved: {ALLOCATION_CONFIG}")
        print("=" * 80)
        
        return self.current_allocation
    
    def generate_allocation_report(self, allocation: Dict) -> str:
        """Generate human-readable allocation report"""
        
        lines = []
        lines.append("# PORTFOLIO ALLOCATION REPORT")
        lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M EDT')}")
        lines.append("")
        lines.append("---")
        lines.append("")
        
        # Portfolio summary
        lines.append("## Portfolio Summary")
        lines.append("")
        lines.append(f"- **Total Capital:** ${allocation['total_capital']:.2f}")
        lines.append(f"- **Allocated Capital:** ${allocation['allocated_capital']:.2f} ({allocation['allocated_capital']/allocation['total_capital']*100:.1f}%)")
        lines.append(f"- **Cash Reserve:** ${allocation['cash_reserve']:.2f} ({allocation['cash_reserve']/allocation['total_capital']*100:.1f}%)")
        lines.append("")
        
        pm = allocation['portfolio_metrics']
        lines.append(f"- **Portfolio Sharpe:** {pm['sharpe_ratio']:.2f}")
        lines.append(f"- **Portfolio Expectancy:** ${pm['expectancy']:.2f} per trade")
        lines.append(f"- **Active Strategies:** {pm['num_strategies']}")
        lines.append(f"- **Diversification Ratio:** {pm['diversification_ratio']:.2f}")
        lines.append("")
        lines.append("---")
        lines.append("")
        
        # Strategy allocations
        lines.append("## Strategy Allocations")
        lines.append("")
        
        strategies = allocation['strategies']
        sorted_strategies = sorted(strategies.items(), key=lambda x: x[1]['capital'], reverse=True)
        
        for name, alloc in sorted_strategies:
            lines.append(f"### {name}")
            lines.append(f"**Stage:** {alloc['stage']}")
            lines.append(f"**Allocation:** ${alloc['capital']:.2f} ({alloc['weight']*100:.1f}%)")
            lines.append(f"**Risk Score:** {alloc['risk_score']:.1f}/100")
            lines.append("")
            
            m = alloc['metrics']
            lines.append("**Performance Metrics:**")
            lines.append(f"- Trades: {m['trades']}")
            lines.append(f"- Win Rate: {m['win_rate']:.1f}%")
            lines.append(f"- Profit Factor: {m['profit_factor']:.2f}")
            lines.append(f"- Sharpe Ratio: {m['sharpe_ratio']:.2f}")
            lines.append(f"- Expectancy: ${m['expectancy']:.2f}")
            lines.append(f"- Max Drawdown: {m['max_drawdown']:.1f}%")
            lines.append(f"- Total P&L: ${m['total_pnl']:.2f}")
            lines.append("")
        
        lines.append("---")
        lines.append("")
        
        # Risk limits
        lines.append("## Portfolio Risk Limits")
        lines.append("")
        lines.append(f"- **Max Total Exposure:** {PORTFOLIO_LIMITS['max_total_exposure']*100:.0f}%")
        lines.append(f"- **Max Strategy Weight:** {PORTFOLIO_LIMITS['max_strategy_weight']*100:.0f}%")
        lines.append(f"- **Min Strategy Weight:** {PORTFOLIO_LIMITS['min_strategy_weight']*100:.0f}%")
        lines.append(f"- **Max Correlation:** {PORTFOLIO_LIMITS['max_correlation']*100:.0f}%")
        lines.append(f"- **Max Portfolio Drawdown:** {PORTFOLIO_LIMITS['max_portfolio_drawdown']*100:.0f}%")
        lines.append("")
        lines.append("---")
        lines.append("")
        
        # Scoring weights
        lines.append("## Risk-Adjusted Scoring")
        lines.append("")
        lines.append("**Metric Weights:**")
        for metric, weight in SCORING_WEIGHTS.items():
            lines.append(f"- {metric.replace('_', ' ').title()}: {weight*100:.0f}%")
        lines.append("")
        
        return "\n".join(lines)


def main():
    allocator = PortfolioAllocator()
    allocation = allocator.allocate_capital()
    
    # Generate report
    report = allocator.generate_allocation_report(allocation)
    
    with open(ALLOCATION_REPORT, 'w') as f:
        f.write(report)
    
    print()
    print(f"[REPORT] Report: {ALLOCATION_REPORT}")


if __name__ == "__main__":
    main()
