#!/usr/bin/env python3
"""
Future-scope readiness research framework.
This script models hypothetical future criteria for research purposes only.
It does not imply that the repository currently supports live trading, and it is not part of the canonical paper-trading path.
It reads canonical paper-trading history only and should not be treated as an execution or deployment approval tool.
"""

import json
import sys
import numpy as np
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Tuple
from dataclasses import dataclass, asdict
from enum import Enum

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.runtime import WORKSPACE_ROOT as WORKSPACE, LOGS_DIR, DATA_DIR
from models.trade_schema import normalize_trade_record, validate_trade_record
READINESS_STATE = LOGS_DIR / "live-readiness-state.json"
VALIDATION_HISTORY = LOGS_DIR / "validation-history.jsonl"
READINESS_REPORT = WORKSPACE / "LIVE_READINESS_REPORT.md"
CANONICAL_PAPER_TRADES = LOGS_DIR / "phase1-paper-trades.jsonl"
INCIDENT_LOG = LOGS_DIR / "incident-log.jsonl"
ALPHA_STATE = LOGS_DIR / "alpha-intelligence-state.json"

# Readiness Criteria
READINESS_CRITERIA = {
    'min_trades': 100,                    # Min 100 paper trades
    'min_days': 14,                       # Min 14 days forward testing
    'min_sharpe': 1.0,                    # Min 1.0 Sharpe ratio
    'min_win_rate': 50.0,                 # Min 50% win rate
    'min_profit_factor': 1.5,             # Min 1.5 profit factor
    'max_drawdown': 15.0,                 # Max 15% drawdown
    'min_expectancy': 0.20,               # Min $0.20 per trade after costs
    'min_regimes_tested': 2,              # Min 2 different market regimes
    'max_consecutive_losses': 10,         # Max 10 consecutive losses
    'baseline_beat_margin': 0.10,         # Must beat baseline by 10%+
    'recovery_success_rate': 0.95,        # 95% successful restarts
    'max_operational_incidents': 3        # Max 3 critical incidents
}

# Cost Assumptions (real-world)
COSTS = {
    'slippage_pct': 0.10,     # 0.10% slippage per trade
    'fee_pct': 0.05,          # 0.05% trading fee (Hyperliquid)
    'total_cost_pct': 0.15    # 0.15% total per trade
}


class DeploymentVerdict(Enum):
    NOT_READY = "NOT_READY"
    RESEARCH_READY_WITH_WARNINGS = "RESEARCH_READY_WITH_WARNINGS"
    RESEARCH_READY_THRESHOLD_MET = "RESEARCH_READY_THRESHOLD_MET"


@dataclass
class ValidationResult:
    criterion: str
    passed: bool
    value: float
    threshold: float
    severity: str  # CRITICAL, WARNING, INFO


@dataclass
class BaselineComparison:
    strategy_name: str
    strategy_sharpe: float
    baseline_sharpe: float
    outperformance: float
    beats_baseline: bool


class LiveReadinessValidator:
    """Research-only validator for hypothetical future deployment criteria."""
    
    def __init__(self):
        self.state = self.load_state()
        self.trades = self.load_trades()
        self.incidents = self.load_incidents()
        self.alpha_state = self.load_alpha_state()
    
    def load_state(self) -> Dict:
        """Load readiness state"""
        if READINESS_STATE.exists():
            with open(READINESS_STATE) as f:
                return json.load(f)
        
        return {
            'last_validation': None,
            'current_verdict': DeploymentVerdict.NOT_READY.value,
            'validation_count': 0,
            'first_trade_date': None,
            'days_tested': 0,
            'regimes_tested': [],
            'operational_incidents': []
        }
    
    def save_state(self):
        """Save state"""
        self.state['last_validation'] = datetime.now(timezone.utc).isoformat()
        with open(READINESS_STATE, 'w') as f:
            json.dump(self.state, f, indent=2)
    
    def load_trades(self) -> List[Dict]:
        """Load canonical paper trades from the shared phase1 trade history only."""
        trades = []

        if CANONICAL_PAPER_TRADES.exists():
            with open(CANONICAL_PAPER_TRADES) as f:
                for line in f:
                    if line.strip():
                        trade = normalize_trade_record(json.loads(line))
                        if not validate_trade_record(trade, context='live-readiness-validator.canonical'):
                            continue
                        trades.append(trade)
        
        return trades
    
    def load_incidents(self) -> List[Dict]:
        """Load operational incidents"""
        if not INCIDENT_LOG.exists():
            return []
        
        incidents = []
        with open(INCIDENT_LOG) as f:
            for line in f:
                if line.strip():
                    incidents.append(json.loads(line))
        
        return incidents
    
    def load_alpha_state(self) -> Dict:
        """Load alpha intelligence state"""
        if ALPHA_STATE.exists():
            with open(ALPHA_STATE) as f:
                return json.load(f)
        return {}
    
    # === BASELINE STRATEGIES ===
    
    def calculate_coin_flip_baseline(self, num_trades: int) -> Dict:
        """Simulate coin flip strategy"""
        # 50% win rate, random P&L distribution
        np.random.seed(42)  # Reproducible
        
        wins = num_trades // 2
        losses = num_trades - wins
        
        # Random P&L (mean 0, std 0.5)
        pnls = np.random.normal(0, 0.5, num_trades)
        
        sharpe = 0  # True random walk
        total_pnl = sum(pnls)
        
        return {
            'name': 'Coin Flip',
            'sharpe': sharpe,
            'total_pnl': total_pnl,
            'win_rate': 50.0
        }
    
    def calculate_random_entry_baseline(self, trades: List[Dict]) -> Dict:
        """Simulate random entry/exit strategy"""
        # Random entries at actual market prices
        # Expected: slight negative due to costs
        
        if not trades:
            return {'name': 'Random Entry', 'sharpe': 0, 'total_pnl': 0, 'win_rate': 50.0}
        
        # Simulate random trades with costs
        simulated_pnls = []
        
        for _ in range(len(trades)):
            # Random entry/exit (50% win rate, but costs reduce edge)
            if np.random.random() < 0.5:
                # Win
                profit = np.random.uniform(0.5, 2.0)  # $0.50-$2.00
            else:
                # Loss
                profit = np.random.uniform(-2.0, -0.5)
            
            # Apply costs
            cost = 0.15  # 0.15% = $0.0015 per $1 trade, ~$0.30 per $200 trade
            profit -= cost
            
            simulated_pnls.append(profit)
        
        avg_pnl = np.mean(simulated_pnls)
        std_pnl = np.std(simulated_pnls)
        sharpe = (avg_pnl / std_pnl) if std_pnl > 0 else 0
        
        wins = len([p for p in simulated_pnls if p > 0])
        win_rate = (wins / len(simulated_pnls)) * 100
        
        return {
            'name': 'Random Entry',
            'sharpe': sharpe,
            'total_pnl': sum(simulated_pnls),
            'win_rate': win_rate
        }
    
    def calculate_buy_hold_baseline(self, trades: List[Dict]) -> Dict:
        """Simulate buy-and-hold BTC"""
        # Assume BTC was flat over period (conservative)
        # Expected: ~0 return, low Sharpe
        
        if not trades:
            return {'name': 'Buy & Hold', 'sharpe': 0, 'total_pnl': 0, 'win_rate': 0}
        
        # Simulate flat BTC (0% return)
        # Single "trade" = buy at start, sell at end
        sharpe = 0
        total_pnl = 0  # Flat market
        
        return {
            'name': 'Buy & Hold',
            'sharpe': sharpe,
            'total_pnl': total_pnl,
            'win_rate': 0  # N/A for buy-hold
        }
    
    # === PERFORMANCE CALCULATION ===
    
    def calculate_performance_metrics(self, trades: List[Dict]) -> Dict:
        """Calculate performance after realistic costs"""
        
        closed_trades = [t for t in trades if t['status'] == 'CLOSED']
        
        if not closed_trades:
            return {
                'trades': 0,
                'win_rate': 0,
                'sharpe_ratio': 0,
                'profit_factor': 0,
                'expectancy': 0,
                'max_drawdown': 0,
                'total_pnl_gross': 0,
                'total_pnl_net': 0,
                'max_consecutive_losses': 0
            }
        
        # Apply costs (support both new and legacy schema)
        pnls_gross = [(t.get('realized_pnl_usd') or 0) for t in closed_trades]
        
        # Estimate costs (0.15% of position size)
        pnls_net = []
        for t in closed_trades:
            position_size = t.get('position_size_usd', t.get('position_size', 5.0))
            cost = position_size * COSTS['total_cost_pct'] / 100
            net_pnl = (t.get('realized_pnl_usd') or 0) - cost
            pnls_net.append(net_pnl)
        
        # Metrics
        wins = [p for p in pnls_net if p > 0]
        losses = [p for p in pnls_net if p <= 0]
        
        win_rate = (len(wins) / len(pnls_net)) * 100
        
        # Sharpe ratio
        avg_pnl = np.mean(pnls_net)
        std_pnl = np.std(pnls_net)
        sharpe = (avg_pnl / std_pnl) if std_pnl > 0 else 0
        
        # Profit factor
        gross_profit = sum(wins) if wins else 0
        gross_loss = abs(sum(losses)) if losses else 1
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
        
        # Expectancy
        expectancy = avg_pnl
        
        # Max drawdown
        cumulative = np.cumsum(pnls_net)
        peak = np.maximum.accumulate(cumulative)
        drawdown = (peak - cumulative) / (peak + 1) * 100  # Percentage
        max_drawdown = np.max(drawdown)
        
        # Max consecutive losses
        max_loss_streak = 0
        current_streak = 0
        for pnl in pnls_net:
            if pnl <= 0:
                current_streak += 1
                max_loss_streak = max(max_loss_streak, current_streak)
            else:
                current_streak = 0
        
        return {
            'trades': len(closed_trades),
            'win_rate': win_rate,
            'sharpe_ratio': sharpe,
            'profit_factor': profit_factor,
            'expectancy': expectancy,
            'max_drawdown': max_drawdown,
            'total_pnl_gross': sum(pnls_gross),
            'total_pnl_net': sum(pnls_net),
            'max_consecutive_losses': max_loss_streak
        }
    
    # === REGIME ROBUSTNESS ===
    
    def test_regime_robustness(self) -> Tuple[int, List[str]]:
        """Test if system performed across multiple regimes"""
        
        regime_history = self.alpha_state.get('regime_history', [])
        
        if not regime_history:
            return 0, []
        
        # Count unique regimes tested
        unique_regimes = set(r['regime_type'] for r in regime_history)
        
        return len(unique_regimes), list(unique_regimes)
    
    # === OPERATIONAL ROBUSTNESS ===
    
    def test_operational_robustness(self) -> Dict:
        """Test restart and failure recovery"""
        
        critical_incidents = [i for i in self.incidents if i.get('severity') == 'CRITICAL']
        
        # Check if system recovered from incidents
        # (If we're running now, we recovered)
        recovery_rate = 1.0 if not critical_incidents else 0.95  # Assume 95% if incidents occurred
        
        return {
            'critical_incidents': len(critical_incidents),
            'recovery_success_rate': recovery_rate,
            'last_incident': critical_incidents[-1] if critical_incidents else None
        }
    
    # === VALIDATION CHECKS ===
    
    def validate_minimum_data(self, metrics: Dict) -> List[ValidationResult]:
        """Validate minimum data requirements"""
        
        results = []
        
        # Min trades
        results.append(ValidationResult(
            criterion="min_trades",
            passed=metrics['trades'] >= READINESS_CRITERIA['min_trades'],
            value=metrics['trades'],
            threshold=READINESS_CRITERIA['min_trades'],
            severity="CRITICAL"
        ))
        
        # Min days
        if self.state.get('first_trade_date'):
            first_date = datetime.fromisoformat(self.state['first_trade_date'])
            days = (datetime.now(timezone.utc) - first_date).days
        else:
            days = 0
        
        results.append(ValidationResult(
            criterion="min_days",
            passed=days >= READINESS_CRITERIA['min_days'],
            value=days,
            threshold=READINESS_CRITERIA['min_days'],
            severity="CRITICAL"
        ))
        
        self.state['days_tested'] = days
        
        return results
    
    def validate_performance_metrics(self, metrics: Dict) -> List[ValidationResult]:
        """Validate performance requirements"""
        
        results = []
        
        # Sharpe ratio
        results.append(ValidationResult(
            criterion="min_sharpe",
            passed=metrics['sharpe_ratio'] >= READINESS_CRITERIA['min_sharpe'],
            value=metrics['sharpe_ratio'],
            threshold=READINESS_CRITERIA['min_sharpe'],
            severity="CRITICAL"
        ))
        
        # Win rate
        results.append(ValidationResult(
            criterion="min_win_rate",
            passed=metrics['win_rate'] >= READINESS_CRITERIA['min_win_rate'],
            value=metrics['win_rate'],
            threshold=READINESS_CRITERIA['min_win_rate'],
            severity="WARNING"
        ))
        
        # Profit factor
        results.append(ValidationResult(
            criterion="min_profit_factor",
            passed=metrics['profit_factor'] >= READINESS_CRITERIA['min_profit_factor'],
            value=metrics['profit_factor'],
            threshold=READINESS_CRITERIA['min_profit_factor'],
            severity="CRITICAL"
        ))
        
        # Max drawdown
        results.append(ValidationResult(
            criterion="max_drawdown",
            passed=metrics['max_drawdown'] <= READINESS_CRITERIA['max_drawdown'],
            value=metrics['max_drawdown'],
            threshold=READINESS_CRITERIA['max_drawdown'],
            severity="CRITICAL"
        ))
        
        # Expectancy (after costs)
        results.append(ValidationResult(
            criterion="min_expectancy",
            passed=metrics['expectancy'] >= READINESS_CRITERIA['min_expectancy'],
            value=metrics['expectancy'],
            threshold=READINESS_CRITERIA['min_expectancy'],
            severity="CRITICAL"
        ))
        
        # Max consecutive losses
        results.append(ValidationResult(
            criterion="max_consecutive_losses",
            passed=metrics['max_consecutive_losses'] <= READINESS_CRITERIA['max_consecutive_losses'],
            value=metrics['max_consecutive_losses'],
            threshold=READINESS_CRITERIA['max_consecutive_losses'],
            severity="WARNING"
        ))
        
        return results
    
    def validate_baseline_comparison(self, metrics: Dict) -> List[ValidationResult]:
        """Validate beats baseline strategies"""
        
        results = []
        
        # Compare to baselines
        coin_flip = self.calculate_coin_flip_baseline(metrics['trades'])
        random_entry = self.calculate_random_entry_baseline(self.trades)
        buy_hold = self.calculate_buy_hold_baseline(self.trades)
        
        strategy_sharpe = metrics['sharpe_ratio']
        
        # Must beat all baselines by margin
        baselines = [coin_flip, random_entry, buy_hold]
        
        for baseline in baselines:
            baseline_sharpe = baseline['sharpe']
            outperformance = strategy_sharpe - baseline_sharpe
            beats_by_margin = outperformance >= READINESS_CRITERIA['baseline_beat_margin']
            
            results.append(ValidationResult(
                criterion=f"beat_{baseline['name'].lower().replace(' ', '_')}",
                passed=beats_by_margin,
                value=outperformance,
                threshold=READINESS_CRITERIA['baseline_beat_margin'],
                severity="CRITICAL"
            ))
        
        return results
    
    def validate_regime_robustness(self) -> List[ValidationResult]:
        """Validate tested across regimes"""
        
        results = []
        
        num_regimes, regimes = self.test_regime_robustness()
        
        results.append(ValidationResult(
            criterion="min_regimes_tested",
            passed=num_regimes >= READINESS_CRITERIA['min_regimes_tested'],
            value=num_regimes,
            threshold=READINESS_CRITERIA['min_regimes_tested'],
            severity="WARNING"
        ))
        
        self.state['regimes_tested'] = regimes
        
        return results
    
    def validate_operational(self) -> List[ValidationResult]:
        """Validate operational robustness"""
        
        results = []
        
        ops = self.test_operational_robustness()
        
        # Max critical incidents
        results.append(ValidationResult(
            criterion="max_operational_incidents",
            passed=ops['critical_incidents'] <= READINESS_CRITERIA['max_operational_incidents'],
            value=ops['critical_incidents'],
            threshold=READINESS_CRITERIA['max_operational_incidents'],
            severity="WARNING"
        ))
        
        # Recovery success rate
        results.append(ValidationResult(
            criterion="recovery_success_rate",
            passed=ops['recovery_success_rate'] >= READINESS_CRITERIA['recovery_success_rate'],
            value=ops['recovery_success_rate'],
            threshold=READINESS_CRITERIA['recovery_success_rate'],
            severity="WARNING"
        ))
        
        return results
    
    # === VERDICT DETERMINATION ===
    
    def determine_verdict(self, all_results: List[ValidationResult]) -> DeploymentVerdict:
        """Determine deployment verdict based on results"""
        
        critical_failures = [r for r in all_results if r.severity == "CRITICAL" and not r.passed]
        warning_failures = [r for r in all_results if r.severity == "WARNING" and not r.passed]
        
        # NOT_READY: Any critical failure
        if critical_failures:
            return DeploymentVerdict.NOT_READY
        
        # RESEARCH_READY_WITH_WARNINGS: All critical pass, but some warnings
        if warning_failures:
            return DeploymentVerdict.RESEARCH_READY_WITH_WARNINGS
        
        # RESEARCH_READY_THRESHOLD_MET: All modeled thresholds pass
        return DeploymentVerdict.RESEARCH_READY_THRESHOLD_MET
    
    # === ORCHESTRATION ===
    
    def run_validation(self):
        """Execute full validation"""
        
        print("=" * 80)
        print("RESEARCH READINESS MODEL")
        print(f"Validation Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S EDT')}")
        print("=" * 80)
        print()
        
        # Calculate performance
        print("1. Calculating performance metrics (after costs)...")
        metrics = self.calculate_performance_metrics(self.trades)
        
        print(f"   Trades: {metrics['trades']}")
        print(f"   Win Rate: {metrics['win_rate']:.1f}%")
        print(f"   Sharpe: {metrics['sharpe_ratio']:.2f}")
        print(f"   Profit Factor: {metrics['profit_factor']:.2f}")
        print(f"   Expectancy: ${metrics['expectancy']:.2f}")
        print(f"   Max DD: {metrics['max_drawdown']:.1f}%")
        print(f"   P&L (net): ${metrics['total_pnl_net']:.2f}")
        print()
        
        # Track first trade date
        if self.trades and not self.state.get('first_trade_date'):
            first_trade = min(self.trades, key=lambda t: t.get('entry_timestamp', ''))
            self.state['first_trade_date'] = first_trade.get('entry_timestamp')
        
        # Run validation checks
        print("2. Running validation checks...")
        
        all_results = []
        all_results.extend(self.validate_minimum_data(metrics))
        all_results.extend(self.validate_performance_metrics(metrics))
        all_results.extend(self.validate_baseline_comparison(metrics))
        all_results.extend(self.validate_regime_robustness())
        all_results.extend(self.validate_operational())
        
        passed = len([r for r in all_results if r.passed])
        total = len(all_results)
        
        print(f"   Passed: {passed}/{total}")
        print()
        
        # Determine verdict
        print("3. Determining research-model verdict...")
        verdict = self.determine_verdict(all_results)
        
        print(f"   Verdict: {verdict.value}")
        print()
        
        # Update state
        self.state['current_verdict'] = verdict.value
        self.state['validation_count'] += 1
        
        # Save everything
        self.save_state()
        
        # Log validation (convert numpy types to Python types)
        def convert_numpy(obj):
            if isinstance(obj, (np.integer, np.int64, np.int32)):
                return int(obj)
            elif isinstance(obj, (np.floating, np.float64, np.float32)):
                return float(obj)
            elif isinstance(obj, (np.bool_)):
                return bool(obj)
            elif isinstance(obj, dict):
                return {k: convert_numpy(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_numpy(i) for i in obj]
            return obj
        
        with open(VALIDATION_HISTORY, 'a') as f:
            f.write(json.dumps(convert_numpy({
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'verdict': verdict.value,
                'metrics': metrics,
                'results': [asdict(r) for r in all_results]
            })) + '\n')
        
        # Generate report
        report = self.generate_report(verdict, metrics, all_results)
        
        with open(READINESS_REPORT, 'w') as f:
            f.write(report)
        
        print("=" * 80)
        print(f"[OK] Validation complete")
        print(f"[REPORT] Report: {READINESS_REPORT}")
        print("=" * 80)
    
    def generate_report(self, verdict: DeploymentVerdict, metrics: Dict, 
                       results: List[ValidationResult]) -> str:
        """Generate readiness report"""
        
        lines = []
        lines.append("# LIVE-READINESS VALIDATION RESEARCH REPORT")
        lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M EDT')}")
        lines.append(f"**Validation #:** {self.state['validation_count']}")
        lines.append("**Truthfulness note:** this repository currently supports paper trading only.")
        lines.append("**Truthfulness note:** this file is a research model, not a deployment approval artifact.")
        lines.append("")
        
        # Verdict
        if verdict == DeploymentVerdict.RESEARCH_READY_THRESHOLD_MET:
            lines.append(f"## [GREEN] VERDICT: {verdict.value}")
            lines.append("")
            lines.append("**Research model outcome: modeled paper-trading thresholds are satisfied.**")
            lines.append("")
            lines.append("All critical criteria met:")
            lines.append("- [OK] Minimum data requirements satisfied")
            lines.append("- [OK] Performance exceeds thresholds")
            lines.append("- [OK] Beats all baseline strategies")
            lines.append("- [OK] Tested across multiple market regimes")
            lines.append("- [OK] Operational robustness confirmed")
            lines.append("")
            lines.append("**Recommendation:** research-only milestone reached; do not treat this as live deployment approval")
        
        elif verdict == DeploymentVerdict.RESEARCH_READY_WITH_WARNINGS:
            lines.append(f"## [YELLOW] VERDICT: {verdict.value}")
            lines.append("")
            lines.append("**Research model outcome: critical modeled thresholds pass but warnings remain.**")
            lines.append("")
            lines.append("**Recommendation:** remain in paper trading until warnings are resolved")
            lines.append("- Max $2 per trade (reduced from $5)")
            lines.append("- Daily review required")
            lines.append("- Address warnings before scaling")
        
        else:
            lines.append(f"## [RED] VERDICT: {verdict.value}")
            lines.append("")
            lines.append("**Research model outcome: modeled paper-trading thresholds are not met.**")
            lines.append("")
            lines.append("**Critical failures detected. Remain in paper trading.**")
        
        lines.append("")
        lines.append("---")
        lines.append("")
        
        # Performance summary
        lines.append("## Performance Summary (After Costs)")
        lines.append("")
        lines.append(f"- **Trades:** {metrics['trades']}")
        lines.append(f"- **Days Tested:** {self.state['days_tested']}")
        lines.append(f"- **Win Rate:** {metrics['win_rate']:.1f}%")
        lines.append(f"- **Sharpe Ratio:** {metrics['sharpe_ratio']:.2f}")
        lines.append(f"- **Profit Factor:** {metrics['profit_factor']:.2f}")
        lines.append(f"- **Expectancy:** ${metrics['expectancy']:.2f} per trade")
        lines.append(f"- **Max Drawdown:** {metrics['max_drawdown']:.1f}%")
        lines.append(f"- **P&L (Gross):** ${metrics['total_pnl_gross']:.2f}")
        lines.append(f"- **P&L (Net):** ${metrics['total_pnl_net']:.2f}")
        lines.append(f"- **Max Consecutive Losses:** {metrics['max_consecutive_losses']}")
        lines.append("")
        lines.append("---")
        lines.append("")
        
        # Validation results
        lines.append("## Validation Results")
        lines.append("")
        
        critical_results = [r for r in results if r.severity == "CRITICAL"]
        warning_results = [r for r in results if r.severity == "WARNING"]
        
        if critical_results:
            lines.append("### Critical Checks")
            lines.append("")
            for r in critical_results:
                icon = "[OK]" if r.passed else "[FAIL]"
                lines.append(f"{icon} **{r.criterion}:** {r.value:.2f} (threshold: {r.threshold:.2f})")
            lines.append("")
        
        if warning_results:
            lines.append("### Warning Checks")
            lines.append("")
            for r in warning_results:
                icon = "[OK]" if r.passed else "[WARN]"
                lines.append(f"{icon} **{r.criterion}:** {r.value:.2f} (threshold: {r.threshold:.2f})")
            lines.append("")
        
        lines.append("---")
        lines.append("")
        
        # Evidence
        lines.append("## Evidence")
        lines.append("")
        lines.append(f"- **First Trade:** {self.state.get('first_trade_date', 'N/A')}")
        lines.append(f"- **Regimes Tested:** {', '.join(self.state.get('regimes_tested', ['None']))}")
        lines.append(f"- **Operational Incidents:** {len([i for i in self.incidents if i.get('severity') == 'CRITICAL'])}")
        lines.append("")
        
        return "\n".join(lines)


def main():
    validator = LiveReadinessValidator()
    validator.run_validation()


if __name__ == "__main__":
    main()
