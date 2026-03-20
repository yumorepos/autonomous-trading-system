#!/usr/bin/env python3
"""
Trading Agency: Phase 1 Executor
Runs all Phase 1 operations (scan, signal, paper trade) as a single agency worker
Reports results back to supervisor system
"""

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path.home() / ".openclaw" / "workspace"
AGENCY_REPORT = WORKSPACE / "logs" / "agency-phase1-report.json"


def run_signal_scanner():
    """Execute signal scanner, return results"""
    print("🔍 Agency: Running signal scanner...")
    
    result = subprocess.run(
        ["python3", str(WORKSPACE / "scripts" / "phase1-signal-scanner.py")],
        capture_output=True, text=True, timeout=60
    )
    
    if result.returncode == 0:
        print("  ✅ Scanner complete")
        return {'status': 'success', 'output': result.stdout}
    else:
        print(f"  ❌ Scanner failed: {result.stderr}")
        return {'status': 'error', 'error': result.stderr}


def run_social_scanner():
    """Execute social media scanner"""
    print("🐦 Agency: Running social scanner...")
    
    result = subprocess.run(
        ["python3", str(WORKSPACE / "scripts" / "phase1-social-scanner.py")],
        capture_output=True, text=True, timeout=60
    )
    
    if result.returncode == 0:
        print("  ✅ Social scanner complete")
        return {'status': 'success', 'output': result.stdout}
    else:
        print(f"  ⚠️ Social scanner incomplete (may be expected): {result.stderr[:200]}")
        return {'status': 'partial', 'note': 'agent-reach may not be installed'}


def run_paper_trader():
    """Execute paper trader"""
    print("💼 Agency: Running paper trader...")
    
    result = subprocess.run(
        ["python3", str(WORKSPACE / "scripts" / "phase1-paper-trader.py")],
        capture_output=True, text=True, timeout=60
    )
    
    if result.returncode == 0:
        print("  ✅ Paper trader complete")
        return {'status': 'success', 'output': result.stdout}
    else:
        print(f"  ❌ Paper trader failed: {result.stderr}")
        return {'status': 'error', 'error': result.stderr}


def load_performance_data():
    """Load latest performance metrics"""
    perf_file = WORKSPACE / "logs" / "phase1-performance.json"
    
    if perf_file.exists():
        with open(perf_file) as f:
            return json.load(f)
    
    return None


def load_open_positions():
    """Load current open positions"""
    trades_file = WORKSPACE / "logs" / "phase1-paper-trades.jsonl"
    
    if not trades_file.exists():
        return []
    
    open_pos = []
    with open(trades_file) as f:
        for line in f:
            if line.strip():
                trade = json.loads(line)
                if trade['status'] == 'OPEN':
                    open_pos.append(trade)
    
    return open_pos


def load_latest_signals():
    """Load latest signals"""
    signals_file = WORKSPACE / "logs" / "phase1-signals.jsonl"
    
    if not signals_file.exists():
        return []
    
    signals = []
    with open(signals_file) as f:
        for line in f:
            if line.strip():
                signals.append(json.loads(line))
    
    # Return last 10 signals
    return signals[-10:]


def generate_agency_report(scanner_result, social_result, trader_result):
    """Generate comprehensive report for supervisor"""
    
    performance = load_performance_data()
    open_positions = load_open_positions()
    latest_signals = load_latest_signals()
    
    # Sort signals by EV
    latest_signals.sort(key=lambda x: x.get('ev_score', 0), reverse=True)
    
    report = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'agency': 'trading-phase1',
        'cycle_number': len(open_positions) + (performance.get('total_trades', 0) if performance else 0),
        
        'execution_results': {
            'signal_scanner': scanner_result['status'],
            'social_scanner': social_result['status'],
            'paper_trader': trader_result['status']
        },
        
        'current_state': {
            'open_positions': len(open_positions),
            'latest_signals_count': len(latest_signals),
            'top_signal_ev': latest_signals[0]['ev_score'] if latest_signals else 0
        },
        
        'performance_summary': performance or {
            'total_trades': 0,
            'note': 'No closed trades yet'
        },
        
        'supervisor_action_required': []
    }
    
    # Check if supervisor needs to act
    if performance:
        # Check if any strategy is ready for promotion
        for strat in performance.get('strategy_rankings', []):
            if strat['trades'] >= 30 and strat['win_rate'] >= 60 and strat['total_pnl'] > 0:
                report['supervisor_action_required'].append({
                    'type': 'strategy_promotion',
                    'strategy': strat['strategy'],
                    'reason': f"Validated: {strat['trades']} trades, {strat['win_rate']}% WR, ${strat['total_pnl']} PnL",
                    'recommendation': 'Promote to Phase 3 shortlist'
                })
        
        # Check if overall performance is poor
        if performance['total_trades'] >= 20 and performance['win_rate_pct'] < 40:
            report['supervisor_action_required'].append({
                'type': 'performance_alert',
                'reason': f"Low win rate: {performance['win_rate_pct']}% over {performance['total_trades']} trades",
                'recommendation': 'Review signal quality, adjust filters'
            })
    
    # Check for stale signals
    if not latest_signals:
        report['supervisor_action_required'].append({
            'type': 'data_issue',
            'reason': 'No signals generated in last cycle',
            'recommendation': 'Check API connectivity, review scanner logs'
        })
    
    # Save report
    AGENCY_REPORT.parent.mkdir(exist_ok=True)
    with open(AGENCY_REPORT, 'w') as f:
        json.dump(report, f, indent=2)
    
    return report


def main():
    print("=" * 80)
    print("TRADING AGENCY: PHASE 1 EXECUTION CYCLE")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S EDT')}")
    print("=" * 80)
    print()
    print("Agency Role: Execute all Phase 1 operations")
    print("Supervisor Role: Review results, make strategic decisions")
    print()
    
    # Execute all Phase 1 operations
    scanner_result = run_signal_scanner()
    social_result = run_social_scanner()
    trader_result = run_paper_trader()
    
    print()
    print("=" * 80)
    print("GENERATING REPORT FOR SUPERVISOR")
    print("=" * 80)
    
    # Generate report
    report = generate_agency_report(scanner_result, social_result, trader_result)
    
    print()
    print(f"📊 Cycle #{report['cycle_number']} Complete")
    print(f"✅ Execution: Scanner={scanner_result['status']}, Social={social_result['status']}, Trader={trader_result['status']}")
    print(f"📈 State: {report['current_state']['open_positions']} open positions, {report['current_state']['latest_signals_count']} signals")
    
    if report['performance_summary'].get('total_trades', 0) > 0:
        perf = report['performance_summary']
        print(f"💰 Performance: {perf['total_trades']} trades, {perf['win_rate_pct']}% WR, ${perf['total_pnl']:+.2f} PnL")
    else:
        print(f"⏳ Performance: No closed trades yet")
    
    print()
    
    if report['supervisor_action_required']:
        print("🚨 SUPERVISOR ACTION REQUIRED:")
        for action in report['supervisor_action_required']:
            print(f"  • {action['type'].upper()}: {action['reason']}")
            print(f"    → {action['recommendation']}")
    else:
        print("✅ No supervisor action required - agency operating normally")
    
    print()
    print(f"📄 Full report saved: {AGENCY_REPORT}")
    print("=" * 80)


if __name__ == "__main__":
    main()
