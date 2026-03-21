#!/usr/bin/env python3
"""
Three-Stage Governance Supervisor
VALIDATE → QUARANTINE → PROMOTE → [Human Approval] → LIVE

Enforces strict lifecycle management with quarantine buffer and human approval gate
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.runtime import WORKSPACE_ROOT as WORKSPACE, LOGS_DIR, DATA_DIR
AGENCY_REPORT = LOGS_DIR / "agency-phase1-report.json"
STRATEGY_REGISTRY = LOGS_DIR / "strategy-registry.json"
SUPERVISOR_DECISIONS = LOGS_DIR / "supervisor-decisions.jsonl"
DECISION_REPORT = WORKSPACE / "SUPERVISOR_GOVERNANCE_REPORT.md"
HUMAN_APPROVAL_QUEUE = LOGS_DIR / "human-approval-queue.json"

# Three-Stage Governance Criteria
VALIDATION_CRITERIA = {
    'min_trades': 30,
    'min_win_rate': 60.0,
    'min_profit_factor': 1.5,
    'max_drawdown': 15.0,
    'min_sharpe': 1.0,
    'min_expectancy': 0.5
}

QUARANTINE_TRIGGERS = {
    'win_rate_warning': 50.0,      # Below 50% → quarantine
    'profit_factor_warning': 1.2,  # Below 1.2 → quarantine
    'loss_streak_warning': 3,      # 3 losses → quarantine
    'degradation_warning': 0.15    # 15% degradation → quarantine
}

DEMOTION_TRIGGERS = {
    'win_rate_critical': 45.0,
    'profit_factor_critical': 1.0,
    'loss_streak_critical': 5,
    'degradation_critical': 0.25,
    'quarantine_cycles': 3  # 3 cycles in quarantine → demote
}


class StrategyGovernance:
    """Manages three-stage strategy lifecycle"""
    
    VALIDATE = 'VALIDATE'      # Paper trading, collecting data
    QUARANTINE = 'QUARANTINE'  # Performance warning, monitoring closely
    PROMOTE = 'PROMOTE'        # Validated, ready for live (needs approval)
    LIVE = 'LIVE'             # Human approved, live capital allowed
    DEMOTE = 'DEMOTE'         # Failed, removed from consideration
    
    def __init__(self):
        self.registry = self.load_registry()
    
    def load_registry(self) -> Dict:
        if STRATEGY_REGISTRY.exists():
            with open(STRATEGY_REGISTRY) as f:
                return json.load(f)
        return {
            'strategies': {},
            'last_updated': None,
            'governance_version': '3-stage-v1'
        }
    
    def save_registry(self):
        self.registry['last_updated'] = datetime.now(timezone.utc).isoformat()
        with open(STRATEGY_REGISTRY, 'w') as f:
            json.dump(self.registry, f, indent=2)
    
    def get_strategy(self, name: str) -> Dict:
        if name in self.registry['strategies']:
            return self.registry['strategies'][name]
        
        return {
            'name': name,
            'stage': self.VALIDATE,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'promoted_at': None,
            'quarantined_at': None,
            'live_approved_at': None,
            'live_approved_by': None,
            'peak_performance': {},
            'current_performance': {},
            'quarantine_cycles': 0,
            'lifecycle_events': [],
            'regime_performance': {}
        }
    
    def update_strategy(self, name: str, updates: Dict):
        if name not in self.registry['strategies']:
            self.registry['strategies'][name] = self.get_strategy(name)
        self.registry['strategies'][name].update(updates)
    
    def add_event(self, name: str, event_type: str, reason: str, data: Dict = None):
        if name not in self.registry['strategies']:
            self.registry['strategies'][name] = self.get_strategy(name)
        
        event = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'type': event_type,
            'reason': reason,
            'data': data or {}
        }
        
        self.registry['strategies'][name]['lifecycle_events'].append(event)


def calculate_expectancy(trades: List[Dict]) -> float:
    """Calculate expectancy (average P&L per trade)"""
    if not trades:
        return 0
    return sum(t['pnl'] for t in trades) / len(trades)


def calculate_profit_factor(trades: List[Dict]) -> float:
    """Profit factor = gross profit / gross loss"""
    wins = [t['pnl'] for t in trades if t['pnl'] > 0]
    losses = [abs(t['pnl']) for t in trades if t['pnl'] < 0]
    
    gross_profit = sum(wins) if wins else 0
    gross_loss = sum(losses) if losses else 1
    
    return gross_profit / gross_loss if gross_loss > 0 else 0


def calculate_max_drawdown(trades: List[Dict]) -> float:
    """Maximum drawdown percentage"""
    if not trades:
        return 0
    
    cumulative = 0
    peak = 0
    max_dd = 0
    
    for trade in trades:
        cumulative += trade['pnl']
        peak = max(peak, cumulative)
        dd = ((peak - cumulative) / peak * 100) if peak > 0 else 0
        max_dd = max(max_dd, dd)
    
    return max_dd


def calculate_sharpe_ratio(trades: List[Dict]) -> float:
    """Sharpe ratio (simplified)"""
    if len(trades) < 5:
        return 0
    
    returns = [t['pnl'] for t in trades]
    avg_return = sum(returns) / len(returns)
    variance = sum((r - avg_return) ** 2 for r in returns) / len(returns)
    std_dev = variance ** 0.5
    
    return (avg_return / std_dev) if std_dev > 0 else 0


def calculate_win_rate(trades: List[Dict]) -> float:
    """Win rate percentage"""
    if not trades:
        return 0
    wins = [t for t in trades if t['pnl'] > 0]
    return (len(wins) / len(trades)) * 100


def detect_loss_streak(trades: List[Dict]) -> int:
    """Count current losing streak"""
    streak = 0
    for trade in reversed(trades):
        if trade['pnl'] <= 0:
            streak += 1
        else:
            break
    return streak


def calculate_degradation(current_metrics: Dict, peak_metrics: Dict) -> float:
    """Performance degradation from peak"""
    if not peak_metrics or 'win_rate' not in peak_metrics:
        return 0
    
    peak_wr = peak_metrics['win_rate']
    current_wr = current_metrics.get('win_rate', 0)
    
    return ((peak_wr - current_wr) / peak_wr) if peak_wr > 0 else 0


def calculate_all_metrics(trades: List[Dict]) -> Dict:
    """Calculate all governance metrics"""
    return {
        'trades': len(trades),
        'win_rate': round(calculate_win_rate(trades), 1),
        'profit_factor': round(calculate_profit_factor(trades), 2),
        'sharpe_ratio': round(calculate_sharpe_ratio(trades), 2),
        'max_drawdown': round(calculate_max_drawdown(trades), 1),
        'expectancy': round(calculate_expectancy(trades), 2),
        'loss_streak': detect_loss_streak(trades),
        'total_pnl': round(sum(t['pnl'] for t in trades), 2)
    }


def evaluate_validation(strategy_name: str, metrics: Dict, gov: StrategyGovernance) -> Tuple[str, str, Dict]:
    """Evaluate if strategy should be promoted from VALIDATE"""
    
    checks = {
        'min_trades': metrics['trades'] >= VALIDATION_CRITERIA['min_trades'],
        'min_win_rate': metrics['win_rate'] >= VALIDATION_CRITERIA['min_win_rate'],
        'min_profit_factor': metrics['profit_factor'] >= VALIDATION_CRITERIA['min_profit_factor'],
        'max_drawdown': metrics['max_drawdown'] <= VALIDATION_CRITERIA['max_drawdown'],
        'min_sharpe': metrics['sharpe_ratio'] >= VALIDATION_CRITERIA['min_sharpe'],
        'min_expectancy': metrics['expectancy'] >= VALIDATION_CRITERIA['min_expectancy'],
        'positive_pnl': metrics['total_pnl'] > 0
    }
    
    all_passed = all(checks.values())
    
    if all_passed:
        return ('PROMOTE', 'All validation criteria met', checks)
    else:
        failed = [k for k, v in checks.items() if not v]
        return ('VALIDATE', f"Validation incomplete: {', '.join(failed)}", checks)


def evaluate_quarantine(strategy_name: str, metrics: Dict, gov: StrategyGovernance) -> Tuple[str, str]:
    """Evaluate if PROMOTED/QUARANTINE strategy should be quarantined/demoted"""
    
    strategy = gov.get_strategy(strategy_name)
    current_stage = strategy.get('stage', 'VALIDATE')
    quarantine_cycles = strategy.get('quarantine_cycles', 0)
    peak_perf = strategy.get('peak_performance', {})
    
    degradation = calculate_degradation(metrics, peak_perf)
    
    # Check critical triggers (immediate demotion)
    if metrics['win_rate'] < DEMOTION_TRIGGERS['win_rate_critical']:
        return ('DEMOTE', f"Critical: Win rate {metrics['win_rate']}% < {DEMOTION_TRIGGERS['win_rate_critical']}%")
    
    if metrics['profit_factor'] < DEMOTION_TRIGGERS['profit_factor_critical']:
        return ('DEMOTE', f"Critical: Profit factor {metrics['profit_factor']} < {DEMOTION_TRIGGERS['profit_factor_critical']}")
    
    if metrics['loss_streak'] >= DEMOTION_TRIGGERS['loss_streak_critical']:
        return ('DEMOTE', f"Critical: Loss streak {metrics['loss_streak']} consecutive losses")
    
    if degradation >= DEMOTION_TRIGGERS['degradation_critical']:
        return ('DEMOTE', f"Critical: Performance degraded {degradation*100:.1f}% from peak")
    
    # Check if stuck in quarantine too long
    if current_stage == 'QUARANTINE' and quarantine_cycles >= DEMOTION_TRIGGERS['quarantine_cycles']:
        return ('DEMOTE', f"Failed to recover after {quarantine_cycles} quarantine cycles")
    
    # Check warning triggers (quarantine)
    warnings = []
    
    if metrics['win_rate'] < QUARANTINE_TRIGGERS['win_rate_warning']:
        warnings.append(f"Win rate {metrics['win_rate']}% < {QUARANTINE_TRIGGERS['win_rate_warning']}%")
    
    if metrics['profit_factor'] < QUARANTINE_TRIGGERS['profit_factor_warning']:
        warnings.append(f"Profit factor {metrics['profit_factor']} < {QUARANTINE_TRIGGERS['profit_factor_warning']}")
    
    if metrics['loss_streak'] >= QUARANTINE_TRIGGERS['loss_streak_warning']:
        warnings.append(f"Loss streak {metrics['loss_streak']} trades")
    
    if degradation >= QUARANTINE_TRIGGERS['degradation_warning']:
        warnings.append(f"Degradation {degradation*100:.1f}% from peak")
    
    if warnings and current_stage != 'QUARANTINE':
        return ('QUARANTINE', ' | '.join(warnings))
    
    # Check if recovered from quarantine
    if current_stage == 'QUARANTINE' and not warnings:
        return ('PROMOTE', 'Performance recovered, exiting quarantine')
    
    return ('HOLD', 'Performance stable')


def load_paper_trades() -> Dict[str, List[Dict]]:
    """Load paper trades grouped by strategy"""
    trades_file = LOGS_DIR / "phase1-paper-trades.jsonl"
    
    if not trades_file.exists():
        return {}
    
    trades_by_strategy = {}
    
    with open(trades_file) as f:
        for line in f:
            if line.strip():
                trade = json.loads(line)
                if trade['status'] != 'OPEN':
                    strategy = trade['signal'].get('signal_type', 'unknown')
                    
                    if strategy not in trades_by_strategy:
                        trades_by_strategy[strategy] = []
                    
                    trades_by_strategy[strategy].append(trade)
    
    return trades_by_strategy


def add_to_approval_queue(strategy_name: str, metrics: Dict):
    """Add promoted strategy to human approval queue"""
    if HUMAN_APPROVAL_QUEUE.exists():
        with open(HUMAN_APPROVAL_QUEUE) as f:
            queue = json.load(f)
    else:
        queue = {'pending': []}
    
    # Check if already in queue
    existing = [s for s in queue['pending'] if s['strategy'] == strategy_name]
    if existing:
        return
    
    queue['pending'].append({
        'strategy': strategy_name,
        'submitted_at': datetime.now(timezone.utc).isoformat(),
        'metrics': metrics,
        'status': 'AWAITING_APPROVAL',
        'approved_by': None,
        'approved_at': None
    })
    
    with open(HUMAN_APPROVAL_QUEUE, 'w') as f:
        json.dump(queue, f, indent=2)


def generate_governance_report(decisions: Dict, gov: StrategyGovernance) -> str:
    """Generate three-stage governance report"""
    
    lines = []
    lines.append("# SUPERVISOR GOVERNANCE REPORT")
    lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M EDT')}")
    lines.append("**Model:** Three-Stage Governance (VALIDATE → QUARANTINE → PROMOTE → LIVE)")
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # Summary by stage
    stages = {}
    for name, strategy in gov.registry['strategies'].items():
        stage = strategy.get('stage', 'VALIDATE')
        if stage not in stages:
            stages[stage] = []
        stages[stage].append(name)
    
    lines.append("## Current Stage Distribution")
    lines.append("")
    lines.append(f"- **VALIDATE:** {len(stages.get('VALIDATE', []))} (paper trading)")
    lines.append(f"- **QUARANTINE:** {len(stages.get('QUARANTINE', []))} (performance warning)")
    lines.append(f"- **PROMOTE:** {len(stages.get('PROMOTE', []))} (awaiting human approval)")
    lines.append(f"- **LIVE:** {len(stages.get('LIVE', []))} (human approved, live capital)")
    lines.append(f"- **DEMOTE:** {len(stages.get('DEMOTE', []))} (failed validation)")
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # Decisions this cycle
    transition_counts = {}
    for decision in decisions.values():
        action = decision['transition']
        transition_counts[action] = transition_counts.get(action, 0) + 1
    
    lines.append("## This Cycle Transitions")
    lines.append("")
    for action, count in sorted(transition_counts.items()):
        lines.append(f"- **{action}:** {count}")
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # Details by transition
    for transition in ['VALIDATE→PROMOTE', 'PROMOTE→QUARANTINE', 'QUARANTINE→DEMOTE', 'QUARANTINE→PROMOTE', 'PROMOTE→DEMOTE']:
        strategies = {name: d for name, d in decisions.items() if d['transition'] == transition}
        
        if not strategies:
            continue
        
        lines.append(f"## {transition}")
        lines.append("")
        
        for name, decision in strategies.items():
            lines.append(f"### {name}")
            lines.append(f"**Transition:** {transition}")
            lines.append(f"**Reason:** {decision['reason']}")
            
            if 'metrics' in decision:
                lines.append("")
                lines.append("**Metrics:**")
                for key, value in decision['metrics'].items():
                    lines.append(f"- {key.replace('_', ' ').title()}: {value}")
            
            if 'validation_checks' in decision:
                lines.append("")
                lines.append("**Validation:**")
                for check, passed in decision['validation_checks'].items():
                    status = "✅" if passed else "❌"
                    lines.append(f"- {status} {check.replace('_', ' ').title()}")
            
            if transition == 'VALIDATE→PROMOTE':
                lines.append("")
                lines.append("**⚠️ REQUIRES HUMAN APPROVAL FOR LIVE CAPITAL**")
                lines.append("Review metrics, approve via approval queue if satisfied")
            
            lines.append("")
        
        lines.append("---")
        lines.append("")
    
    # Approval queue status
    if HUMAN_APPROVAL_QUEUE.exists():
        with open(HUMAN_APPROVAL_QUEUE) as f:
            queue = json.load(f)
        
        pending = queue.get('pending', [])
        
        if pending:
            lines.append("## 🚨 HUMAN APPROVAL REQUIRED")
            lines.append("")
            lines.append(f"**{len(pending)} strategies awaiting approval for live capital**")
            lines.append("")
            
            for item in pending:
                if item['status'] == 'AWAITING_APPROVAL':
                    lines.append(f"### {item['strategy']}")
                    lines.append(f"**Submitted:** {item['submitted_at']}")
                    lines.append("**Action Required:** Review performance, approve for Phase 3 if satisfied")
                    lines.append("")
            
            lines.append("---")
            lines.append("")
    
    return "\n".join(lines)


def main():
    print("=" * 80)
    print("THREE-STAGE GOVERNANCE SUPERVISOR")
    print(f"Review Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S EDT')}")
    print("=" * 80)
    print()
    
    gov = StrategyGovernance()
    
    if not AGENCY_REPORT.exists():
        print("⚠️ No agency report available")
        return
    
    # Load paper trades
    trades_by_strategy = load_paper_trades()
    
    print(f"📊 Strategies: {len(trades_by_strategy)}")
    print()
    
    decisions = {}
    
    for strategy_name, trades in trades_by_strategy.items():
        print(f"🔍 Evaluating: {strategy_name}")
        
        closed_trades = [t for t in trades if t['status'] != 'OPEN']
        
        if not closed_trades:
            decisions[strategy_name] = {
                'transition': 'HOLD',
                'reason': 'No closed trades yet',
                'metrics': {'trades': 0}
            }
            print(f"   → HOLD (collecting data)")
            continue
        
        # Calculate all metrics
        metrics = calculate_all_metrics(closed_trades)
        
        strategy = gov.get_strategy(strategy_name)
        current_stage = strategy.get('stage', 'VALIDATE')
        
        print(f"   Current: {current_stage} | Trades: {metrics['trades']} | WR: {metrics['win_rate']}% | PF: {metrics['profit_factor']}")
        
        # Evaluate based on current stage
        if current_stage == 'VALIDATE':
            action, reason, checks = evaluate_validation(strategy_name, metrics, gov)
            
            if action == 'PROMOTE':
                # Promote to PROMOTE stage (awaiting human approval)
                gov.update_strategy(strategy_name, {
                    'stage': gov.PROMOTE,
                    'promoted_at': datetime.now(timezone.utc).isoformat(),
                    'peak_performance': metrics,
                    'current_performance': metrics
                })
                gov.add_event(strategy_name, 'VALIDATION_COMPLETE', reason, metrics)
                
                # Add to approval queue
                add_to_approval_queue(strategy_name, metrics)
                
                decisions[strategy_name] = {
                    'transition': 'VALIDATE→PROMOTE',
                    'reason': reason,
                    'metrics': metrics,
                    'validation_checks': checks
                }
                
                print(f"   → ✅ PROMOTED (awaiting human approval)")
            else:
                decisions[strategy_name] = {
                    'transition': 'HOLD',
                    'reason': reason,
                    'metrics': metrics,
                    'validation_checks': checks
                }
                print(f"   → HOLD (validation incomplete)")
        
        elif current_stage in ['PROMOTE', 'QUARANTINE']:
            action, reason = evaluate_quarantine(strategy_name, metrics, gov)
            
            if action == 'QUARANTINE' and current_stage != 'QUARANTINE':
                # Move to quarantine
                gov.update_strategy(strategy_name, {
                    'stage': gov.QUARANTINE,
                    'quarantined_at': datetime.now(timezone.utc).isoformat(),
                    'quarantine_cycles': strategy.get('quarantine_cycles', 0) + 1,
                    'current_performance': metrics
                })
                gov.add_event(strategy_name, 'QUARANTINED', reason, metrics)
                
                decisions[strategy_name] = {
                    'transition': 'PROMOTE→QUARANTINE',
                    'reason': reason,
                    'metrics': metrics
                }
                
                print(f"   → ⚠️ QUARANTINED ({reason})")
            
            elif action == 'PROMOTE' and current_stage == 'QUARANTINE':
                # Recovered from quarantine
                gov.update_strategy(strategy_name, {
                    'stage': gov.PROMOTE,
                    'quarantine_cycles': 0,
                    'current_performance': metrics
                })
                gov.add_event(strategy_name, 'QUARANTINE_RECOVERY', reason, metrics)
                
                decisions[strategy_name] = {
                    'transition': 'QUARANTINE→PROMOTE',
                    'reason': reason,
                    'metrics': metrics
                }
                
                print(f"   → ✅ RECOVERED (back to PROMOTE)")
            
            elif action == 'DEMOTE':
                # Failed, demote
                gov.update_strategy(strategy_name, {
                    'stage': gov.DEMOTE,
                    'demoted_at': datetime.now(timezone.utc).isoformat(),
                    'current_performance': metrics
                })
                gov.add_event(strategy_name, 'DEMOTED', reason, metrics)
                
                from_stage = 'QUARANTINE' if current_stage == 'QUARANTINE' else 'PROMOTE'
                decisions[strategy_name] = {
                    'transition': f'{from_stage}→DEMOTE',
                    'reason': reason,
                    'metrics': metrics
                }
                
                print(f"   → ❌ DEMOTED ({reason})")
            
            else:
                decisions[strategy_name] = {
                    'transition': 'HOLD',
                    'reason': reason,
                    'metrics': metrics
                }
                print(f"   → HOLD (stable)")
                
                # Update quarantine cycles if in quarantine
                if current_stage == 'QUARANTINE':
                    gov.update_strategy(strategy_name, {
                        'quarantine_cycles': strategy.get('quarantine_cycles', 0) + 1
                    })
    
    print()
    
    # Save registry
    gov.save_registry()
    
    # Log decisions
    SUPERVISOR_DECISIONS.parent.mkdir(exist_ok=True)
    with open(SUPERVISOR_DECISIONS, 'a') as f:
        f.write(json.dumps({
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'decisions': decisions
        }) + '\n')
    
    # Generate report
    report = generate_governance_report(decisions, gov)
    
    with open(DECISION_REPORT, 'w') as f:
        f.write(report)
    
    print("=" * 80)
    print(f"📄 Governance report: {DECISION_REPORT}")
    print(f"📊 Strategy registry: {STRATEGY_REGISTRY}")
    
    if HUMAN_APPROVAL_QUEUE.exists():
        with open(HUMAN_APPROVAL_QUEUE) as f:
            queue = json.load(f)
        pending = len([s for s in queue.get('pending', []) if s['status'] == 'AWAITING_APPROVAL'])
        if pending > 0:
            print(f"🚨 Human approval required: {pending} strategies")
            print(f"   Review: {HUMAN_APPROVAL_QUEUE}")
    
    print("=" * 80)


if __name__ == "__main__":
    main()
