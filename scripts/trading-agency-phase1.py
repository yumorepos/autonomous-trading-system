#!/usr/bin/env python3
"""
Trading Agency: Phase 1 Executor
Runs the enforced Phase 1 execution path as a single agency worker:
orchestrator -> data integrity -> signal scanner -> safety validation ->
trader -> authoritative state update -> monitors.
"""

import json
import sys
import os
import subprocess
import importlib.util
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.runtime import WORKSPACE_ROOT as WORKSPACE, LOGS_DIR, DATA_DIR
from models.position_state import get_open_positions
from utils.system_health import SystemHealthManager
from utils.json_utils import safe_read_json, safe_read_jsonl, write_json_atomic
AGENCY_REPORT = LOGS_DIR / "agency-phase1-report.json"


class StageStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"


@dataclass
class StageResult:
    stage: str
    status: str
    reason: str
    data: dict | None = None


def load_script_module(script_name: str, module_name: str):
    """Load a local script with a hyphenated filename as a Python module."""
    script_path = REPO_ROOT / "scripts" / script_name
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stage_result(stage: str, status: StageStatus, reason: str, data: dict | None = None) -> StageResult:
    result = StageResult(stage=stage, status=status.value, reason=reason, data=data)
    print(f"[{result.stage}] {result.status} - {result.reason}")
    return result


def detect_optional_components() -> dict:
    """Detect optional modules explicitly so missing components are visible."""
    social_scanner = REPO_ROOT / "scripts" / "phase1-social-scanner.py"
    polymarket_executor = REPO_ROOT / "scripts" / "polymarket-executor.py"
    return {
        'social_scanner': {
            'status': 'ENABLED' if social_scanner.exists() else 'MISSING',
            'reason': 'Script detected' if social_scanner.exists() else 'phase1-social-scanner.py not present',
        },
        'polymarket_execution': {
            'status': 'DISABLED' if polymarket_executor.exists() else 'MISSING',
            'reason': (
                'Polymarket executor exists but is not active in Phase 1 paper trading'
                if polymarket_executor.exists()
                else 'polymarket-executor.py not present'
            ),
        },
    }


def run_data_integrity_gate(optional_components: dict) -> StageResult:
    """Run the enforced pre-scan data integrity gate."""
    integrity_module = load_script_module("data-integrity-layer.py", "phase1_data_integrity")
    integrity = integrity_module.DataIntegrityLayer()
    gate = integrity.run_pre_scan_gate(
        include_polymarket=optional_components['polymarket_execution']['status'] == 'ENABLED'
    )
    status = StageStatus.SUCCESS if gate['passed'] else StageStatus.FAIL
    return stage_result("data_integrity", status, gate['reason'], gate)


def run_signal_scanner():
    """Execute signal scanner as the only scanner in the canonical path."""
    print("🔍 Agency: Running signal scanner...")
    
    result = subprocess.run(
        ["python3", str(REPO_ROOT / "scripts" / "phase1-signal-scanner.py")],
        capture_output=True, text=True, timeout=60
    )
    
    if result.returncode == 0:
        signals = load_latest_signals()
        return stage_result(
            "signal_scanner",
            StageStatus.SUCCESS,
            f"Scanner completed with {len(signals)} recent signals available",
            {'stdout': result.stdout, 'signals_count': len(signals)},
        )

    error = result.stderr.strip() or result.stdout.strip() or "Signal scanner exited non-zero"
    return stage_result("signal_scanner", StageStatus.FAIL, error, {'stderr': result.stderr, 'stdout': result.stdout})


def run_safety_validation() -> StageResult:
    """Validate the next candidate entry before the trader can place it."""
    trader_module = load_script_module("phase1-paper-trader.py", "phase1_paper_trader")
    safety_module = load_script_module("execution-safety-layer.py", "phase1_execution_safety")

    open_positions = trader_module.load_open_positions()
    signals = trader_module.load_latest_signals()
    candidate_signal, selection_reason = trader_module.select_trade_candidate(signals, open_positions)

    if candidate_signal is None:
        return stage_result(
            "safety_validation",
            StageStatus.SKIPPED,
            selection_reason,
            {'candidate_signal': None},
        )

    proposal = safety_module.TradeProposal(
        strategy='funding_arbitrage',
        asset=candidate_signal['asset'],
        direction=candidate_signal['direction'],
        entry_price=float(candidate_signal['entry_price']),
        position_size_usd=trader_module.PAPER_BALANCE * 0.02,
        signal_timestamp=candidate_signal['timestamp'],
        allocation_weight=0.02,
    )
    safety = safety_module.ExecutionSafetyLayer()
    passed, validations = safety.validate_trade(proposal)
    summary = safety.summarize_validation_results(validations)

    if passed:
        return stage_result(
            "safety_validation",
            StageStatus.SUCCESS,
            f"{selection_reason}; {summary['reason']}",
            {
                'candidate_signal': candidate_signal,
                'proposal': proposal.to_dict(),
                'validations': [asdict(result) for result in validations],
            },
        )

    safety.log_blocked_action(proposal, summary['reason'], validations)
    return stage_result(
        "safety_validation",
        StageStatus.FAIL,
        summary['reason'],
        {
            'candidate_signal': candidate_signal,
            'proposal': proposal.to_dict(),
            'validations': [asdict(result) for result in validations],
        },
    )


def run_trader(safety_stage: StageResult, trading_response: dict) -> StageResult:
    """Build the trader execution plan without updating authoritative state yet."""
    trader_module = load_script_module("phase1-paper-trader.py", "phase1_paper_trader")
    try:
        candidate_signal = (safety_stage.data or {}).get('candidate_signal')
        allow_new_entries = (
            safety_stage.status == StageStatus.SUCCESS.value
            and candidate_signal is not None
            and trading_response.get('allow_new_trades', True)
        )
        allowed_signal_timestamp = candidate_signal.get('timestamp') if allow_new_entries else None
        plan = trader_module.build_execution_plan(
            allowed_signal_timestamp=allowed_signal_timestamp,
            allow_new_entries=allow_new_entries,
        )
    except Exception as exc:
        return stage_result("trader", StageStatus.FAIL, f"Trader planning failed: {exc}")

    planned_trades = plan.get('planned_trades', [])
    if not planned_trades:
        reason = plan.get('entry_reason', 'No trade records generated')
        if not trading_response.get('allow_new_trades', True):
            reason = f"{reason}; CRITICAL health halt active: {trading_response.get('reason')}"
        return stage_result("trader", StageStatus.SKIPPED, reason, plan)

    if not trading_response.get('allow_new_trades', True):
        planned_entry = plan.get('planned_entry')
        planned_closes = plan.get('planned_closes', [])
        return stage_result(
            "trader",
            StageStatus.SUCCESS,
            (
                f"CRITICAL health halt active: new entries blocked, "
                f"prepared {len(planned_closes)} exit record(s)"
                if planned_closes
                else f"CRITICAL health halt active: {trading_response.get('reason')}"
            ),
            {
                **plan,
                'planned_trades': planned_closes,
                'planned_entry': None,
                'entry_reason': trading_response.get('reason'),
                'health_action': trading_response,
                'blocked_entry': planned_entry,
            },
        )

    return stage_result(
        "trader",
        StageStatus.SUCCESS,
        f"Prepared {len(planned_trades)} trade record(s) for authoritative state update",
        {**plan, 'health_action': trading_response},
    )


def run_state_update(trader_stage: StageResult) -> StageResult:
    """Persist trader output and update authoritative position state only after trader success."""
    if trader_stage.status != StageStatus.SUCCESS.value:
        return stage_result("authoritative_state_update", StageStatus.SKIPPED, "Trader did not succeed; state update blocked")

    trader_module = load_script_module("phase1-paper-trader.py", "phase1_paper_trader")
    planned_trades = (trader_stage.data or {}).get('planned_trades', [])
    if not planned_trades:
        return stage_result("authoritative_state_update", StageStatus.SKIPPED, "No trade records to persist")

    persisted = trader_module.persist_trade_records(planned_trades)
    performance = trader_module.calculate_performance()
    return stage_result(
        "authoritative_state_update",
        StageStatus.SUCCESS,
        f"Persisted {persisted} trade record(s) and refreshed performance state",
        {'persisted_records': persisted, 'performance': performance},
    )


def load_performance_data():
    """Load latest performance metrics"""
    return safe_read_json(LOGS_DIR / "phase1-performance.json")


def load_open_positions():
    """Load current open positions from authoritative state only."""
    return get_open_positions(LOGS_DIR / 'position-state.json')


def load_latest_signals():
    """Load latest signals"""
    return safe_read_jsonl(LOGS_DIR / "phase1-signals.jsonl")[-10:]


def generate_agency_report(stage_results: list[StageResult], optional_components: dict):
    """Generate comprehensive report for supervisor"""
    
    performance = load_performance_data()
    open_positions = load_open_positions()
    latest_signals = load_latest_signals()
    health_manager = SystemHealthManager()
    health_state = health_manager.refresh_state()
    trading_response = health_manager.trading_response()
    
    # Sort signals by EV
    latest_signals.sort(key=lambda x: x.get('ev_score', 0), reverse=True)
    
    report = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'agency': 'trading-phase1',
        'cycle_number': len(open_positions) + (performance.get('total_trades', 0) if performance else 0),
        
        'execution_results': {result.stage: result.status for result in stage_results},
        'execution_reasons': {result.stage: result.reason for result in stage_results},
        'stage_results': [asdict(result) for result in stage_results],
        'optional_components': optional_components,
        
        'current_state': {
            'open_positions': len(open_positions),
            'latest_signals_count': len(latest_signals),
            'top_signal_ev': latest_signals[0]['ev_score'] if latest_signals else 0,
            'system_health': health_state,
            'health_visibility': {
                'active_incidents': len(health_state.get('active_incidents', [])),
                'resolved_incidents_recent': len(health_state.get('resolved_incidents', [])),
                'cooldown_remaining': health_state.get('cooldown_remaining', 0),
                'recovery_state': health_state.get('recovery_state', 'NORMAL'),
            },
            'action_taken': trading_response,
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
            if strat['trades'] >= 30 and strat['win_rate'] >= 60 and strat['total_pnl_usd'] > 0:
                report['supervisor_action_required'].append({
                    'type': 'strategy_promotion',
                    'strategy': strat['strategy'],
                    'reason': f"Validated: {strat['trades']} trades, {strat['win_rate']}% WR, ${strat['total_pnl_usd']} PnL",
                    'recommendation': 'Promote to Phase 3 shortlist'
                })
        
        # Check if overall performance is poor
        if performance['total_trades'] >= 20 and performance['win_rate'] < 40:
            report['supervisor_action_required'].append({
                'type': 'performance_alert',
                'reason': f"Low win rate: {performance['win_rate']}% over {performance['total_trades']} trades",
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
    write_json_atomic(AGENCY_REPORT, report)

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

    optional_components = detect_optional_components()
    health_manager = SystemHealthManager()
    print("Optional components:")
    for component_name, component_state in optional_components.items():
        print(f"  - {component_name}: {component_state['status']} ({component_state['reason']})")
    print()

    stage_results: list[StageResult] = []
    opening_health = health_manager.trading_response()
    print(
        f"System health: {opening_health['overall_status']} | "
        f"Action: {opening_health['action']} | "
        f"Reason: {opening_health['reason']}"
    )
    print()

    data_stage = run_data_integrity_gate(optional_components)
    stage_results.append(data_stage)

    if data_stage.status == StageStatus.FAIL.value:
        scanner_stage = stage_result("signal_scanner", StageStatus.SKIPPED, "Blocked by data integrity failure")
        safety_stage = stage_result("safety_validation", StageStatus.SKIPPED, "Scanner did not run; entries blocked")
        stage_results.extend([scanner_stage, safety_stage])
        trader_stage = run_trader(safety_stage, health_manager.trading_response())
        stage_results.append(trader_stage)
        state_stage = run_state_update(trader_stage)
        stage_results.append(state_stage)
    else:
        scanner_stage = run_signal_scanner()
        stage_results.append(scanner_stage)

        if scanner_stage.status == StageStatus.FAIL.value:
            safety_stage = stage_result("safety_validation", StageStatus.SKIPPED, "Signal scanner failed; entries blocked")
            stage_results.append(safety_stage)
            trader_stage = run_trader(safety_stage, health_manager.trading_response())
            stage_results.append(trader_stage)
            state_stage = run_state_update(trader_stage)
            stage_results.append(state_stage)
        else:
            safety_stage = run_safety_validation()
            stage_results.append(safety_stage)
            current_response = health_manager.trading_response()
            trader_stage = run_trader(safety_stage, current_response)
            stage_results.append(trader_stage)
            state_stage = run_state_update(trader_stage)
            stage_results.append(state_stage)

    final_response = health_manager.trading_response()
    final_health_state = health_manager.refresh_state()
    monitors_stage = stage_result(
        "monitors",
        StageStatus.SUCCESS,
        (
            f"Health {final_response['overall_status']} | "
            f"active_incidents={len(final_health_state.get('active_incidents', []))} | "
            f"resolved_recent={len(final_health_state.get('resolved_incidents', []))} | "
            f"cooldown_remaining={final_health_state.get('cooldown_remaining', 0)}s | "
            f"recovery_state={final_health_state.get('recovery_state', 'NORMAL')} | "
            f"action={final_response['action']}"
        ),
        {
            'system_health': final_health_state,
            'action_taken': final_response,
        },
    )
    stage_results.append(monitors_stage)
    
    print()
    print("=" * 80)
    print("GENERATING REPORT FOR SUPERVISOR")
    print("=" * 80)
    
    # Generate report
    report = generate_agency_report(stage_results, optional_components)
    
    print()
    print(f"📊 Cycle #{report['cycle_number']} Complete")
    print("✅ Stage status summary:")
    for result in stage_results:
        print(f"   - {result.stage}: {result.status} ({result.reason})")
    print(f"📈 State: {report['current_state']['open_positions']} open positions, {report['current_state']['latest_signals_count']} signals")
    print(
        f"🩺 Health: {report['current_state']['system_health']['overall_status']} | "
        f"Active: {len(report['current_state']['system_health']['active_incidents'])} | "
        f"Resolved recent: {len(report['current_state']['system_health'].get('resolved_incidents', []))} | "
        f"Cooldown: {report['current_state']['system_health'].get('cooldown_remaining', 0)}s | "
        f"Recovery: {report['current_state']['system_health'].get('recovery_state', 'NORMAL')} | "
        f"Action: {report['current_state']['action_taken']['action']}"
    )
    
    if report['performance_summary'].get('total_trades', 0) > 0:
        perf = report['performance_summary']
        print(f"💰 Performance: {perf['total_trades']} trades, {perf['win_rate']}% WR, ${perf['total_pnl_usd']:+.2f} PnL")
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
