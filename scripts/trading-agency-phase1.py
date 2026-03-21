#!/usr/bin/env python3
"""
Trading Agency: Phase 1 Executor
Runs the enforced Phase 1 execution path as a single agency worker:
orchestrator -> data integrity -> signal scanner -> safety validation ->
trader -> authoritative state update -> monitor/report stage.
"""

import sys
import re
import subprocess
import importlib.util
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.runtime import (
    WORKSPACE_ROOT as WORKSPACE,
    LOGS_DIR,
    TRADING_MODE,
    mode_includes_hyperliquid,
    mode_includes_polymarket,
)
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


def safety_snapshot_summary(snapshot: dict | None) -> str:
    if not snapshot:
        return "status=UNKNOWN"

    runtime = snapshot.get('runtime_enforcement', {})
    breakers = snapshot.get('circuit_breakers', {})
    return (
        f"status={snapshot.get('status', 'UNKNOWN')} | "
        f"loss_streak={breakers.get('consecutive_losses', 0)} | "
        f"daily_loss={breakers.get('daily_loss_usd', 0)} | "
        f"hourly_loss={breakers.get('hourly_loss_usd', 0)} | "
        f"transition={runtime.get('last_transition')} | "
        f"blocked_actions={runtime.get('blocked_actions_count', 0)} | "
        f"planned={runtime.get('last_planned_trade_count', 0)} | "
        f"persisted={runtime.get('last_persisted_trade_count', 0)} | "
        f"breaker_source={runtime.get('breaker_accounting_source', 'advisory_static_defaults')} | "
        f"cooldown_mode={runtime.get('cooldown_enforcement_mode', 'advisory_config_only')}"
    )


def detect_optional_components(trading_mode: str = TRADING_MODE) -> dict:
    """Detect optional modules explicitly so missing components are visible."""
    social_scanner = REPO_ROOT / "scripts" / "phase1-social-scanner.py"
    polymarket_executor = REPO_ROOT / "scripts" / "polymarket-executor.py"
    return {
        'social_scanner': {
            'status': 'ENABLED' if social_scanner.exists() else 'MISSING',
            'reason': 'Script detected' if social_scanner.exists() else 'phase1-social-scanner.py not present',
        },
        'polymarket_execution': {
            'status': (
                'ENABLED'
                if polymarket_executor.exists() and mode_includes_polymarket(trading_mode)
                else 'DISABLED'
                if polymarket_executor.exists()
                else 'MISSING'
            ),
            'reason': (
                f"Polymarket executor active for trading_mode={trading_mode}"
                if polymarket_executor.exists() and mode_includes_polymarket(trading_mode)
                else (
                    f"Polymarket executor exists but is not active for trading_mode={trading_mode}"
                    if polymarket_executor.exists()
                    else 'polymarket-executor.py not present'
                )
            ),
        },
    }


def run_bootstrap_check() -> StageResult:
    """Verify clean-environment runtime prerequisites before loading networked scripts."""
    command = ["python3", str(REPO_ROOT / "scripts" / "bootstrap-runtime-check.py")]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    if result.returncode == 0:
        return stage_result(
            "bootstrap",
            StageStatus.SUCCESS,
            "Runtime dependency check passed",
            {'stdout': result.stdout, 'command': command},
        )
    return stage_result(
        "bootstrap",
        StageStatus.FAIL,
        result.stderr.strip() or result.stdout.strip() or "Bootstrap dependency check failed",
        {'stdout': result.stdout, 'stderr': result.stderr, 'command': command},
    )


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
    print("[SCAN] Agency: Running signal scanner...")
    
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

    safety = safety_module.ExecutionSafetyLayer()
    breaker_refresh = safety.refresh_breaker_state_from_canonical_history()
    before_snapshot = safety.snapshot_state()
    pre_validation_snapshot = safety.persist_runtime_state(
        "BEFORE_VALIDATION",
        extra={
            'candidate_signal': candidate_signal,
            'last_breaker_refresh_changes': breaker_refresh.get('changed_fields', {}),
        },
        persist_reason="Safety stage loaded candidate signal for canonical validation",
    )

    valid_canonical_signal, canonical_reason = trader_module.validate_canonical_signal(candidate_signal)
    if not valid_canonical_signal:
        trader_module.log_non_canonical_signal(candidate_signal, canonical_reason)
        skipped_snapshot = safety.persist_runtime_state(
            "VALIDATION_SKIPPED_NON_CANONICAL",
            extra={
                'candidate_signal': candidate_signal,
                'last_validation_result': 'SKIPPED_NON_CANONICAL',
            },
            persist_reason="Non-canonical signal rejected before safety proposal construction",
        )
        return stage_result(
            "safety_validation",
            StageStatus.SKIPPED,
            (
                f"SKIPPED_NON_CANONICAL_SIGNAL: {canonical_reason}; "
                f"read {safety_snapshot_summary(before_snapshot)}; "
                f"persisted {safety_snapshot_summary(skipped_snapshot)}"
            ),
            {
                'candidate_signal': candidate_signal,
                'canonical_validation': canonical_reason,
                'safety_state_before': before_snapshot,
                'safety_state_after': skipped_snapshot,
                'safety_state_pre_validation': pre_validation_snapshot,
                'breaker_state_before_validation': breaker_refresh,
            },
        )

    proposal = safety_module.TradeProposal(
        exchange=candidate_signal.get('exchange', candidate_signal.get('source', 'Hyperliquid')),
        strategy=candidate_signal.get('strategy', candidate_signal.get('signal_type', 'funding_arbitrage')),
        asset=candidate_signal.get('symbol') or candidate_signal.get('asset') or candidate_signal.get('market_id'),
        direction=candidate_signal.get('side') or candidate_signal.get('direction'),
        entry_price=float(candidate_signal.get('entry_price')),
        position_size_usd=float(candidate_signal.get('recommended_position_size_usd', trader_module.PAPER_BALANCE * 0.02)),
        signal_timestamp=candidate_signal['timestamp'],
        allocation_weight=0.02,
    )
    passed, validations = safety.validate_trade(proposal)
    summary = safety.summarize_validation_results(validations)
    transition = "VALIDATION_PASSED" if passed else "VALIDATION_BLOCKED"
    validated_snapshot = safety.persist_runtime_state(
        transition,
        proposal=proposal,
        summary=summary,
        extra={'candidate_signal': candidate_signal},
        persist_reason="Canonical safety validation results persisted for orchestrated runtime",
    )

    if passed:
        return stage_result(
            "safety_validation",
            StageStatus.SUCCESS,
            (
                f"{selection_reason}; {summary['reason']}; "
                f"read {safety_snapshot_summary(before_snapshot)}; "
                f"persisted {safety_snapshot_summary(validated_snapshot)}"
            ),
            {
                'candidate_signal': candidate_signal,
                'proposal': proposal.to_dict(),
                'validations': [asdict(result) for result in validations],
                'safety_state_before': before_snapshot,
                'safety_state_after': validated_snapshot,
                'safety_state_pre_validation': pre_validation_snapshot,
                'breaker_state_before_validation': breaker_refresh,
            },
        )

    safety.log_blocked_action(proposal, summary['reason'], validations)
    blocked_snapshot = safety.persist_runtime_state(
        "BLOCKED_TRADE",
        proposal=proposal,
        summary=summary,
        extra={'candidate_signal': candidate_signal},
        persist_reason="Blocked trade decision recorded after canonical safety enforcement",
    )
    return stage_result(
        "safety_validation",
        StageStatus.FAIL,
        (
            f"{summary['reason']}; "
            f"read {safety_snapshot_summary(before_snapshot)}; "
            f"persisted {safety_snapshot_summary(blocked_snapshot)}"
        ),
        {
            'candidate_signal': candidate_signal,
            'proposal': proposal.to_dict(),
            'validations': [asdict(result) for result in validations],
            'safety_state_before': before_snapshot,
            'safety_state_after': blocked_snapshot,
            'safety_state_pre_validation': pre_validation_snapshot,
            'breaker_state_before_validation': breaker_refresh,
        },
    )


def run_trader(safety_stage: StageResult, trading_response: dict) -> StageResult:
    """Build the trader execution plan without updating authoritative state yet."""
    trader_module = load_script_module("phase1-paper-trader.py", "phase1_paper_trader")
    safety_module = load_script_module("execution-safety-layer.py", "phase1_execution_safety")
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
        safety = safety_module.ExecutionSafetyLayer()
        planning_snapshot = safety.persist_runtime_state(
            "TRADE_PLANNED",
            extra={
                'last_planned_trade_count': len(planned_closes),
                'last_planned_close_count': len(planned_closes),
                'last_planned_entry_count': 0,
            },
            persist_reason="Trader stage prepared canonical exit records while new entries were halted",
        )
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
                'safety_state_after': planning_snapshot,
            },
        )

    safety = safety_module.ExecutionSafetyLayer()
    planning_snapshot = safety.persist_runtime_state(
        "TRADE_PLANNED",
        extra={
            'last_planned_trade_count': len(planned_trades),
            'last_planned_close_count': len(plan.get('planned_closes', [])),
            'last_planned_entry_count': 1 if plan.get('planned_entry') else 0,
        },
        persist_reason="Trader stage prepared canonical trade records",
    )
    return stage_result(
        "trader",
        StageStatus.SUCCESS,
        (
            f"Prepared {len(planned_trades)} trade record(s) for authoritative state update; "
            f"persisted {safety_snapshot_summary(planning_snapshot)}"
        ),
        {**plan, 'health_action': trading_response, 'safety_state_after': planning_snapshot},
    )


def run_state_update(trader_stage: StageResult) -> StageResult:
    """Persist trader output and update authoritative position state only after trader success."""
    if trader_stage.status != StageStatus.SUCCESS.value:
        return stage_result("authoritative_state_update", StageStatus.SKIPPED, "Trader did not succeed; state update blocked")

    trader_module = load_script_module("phase1-paper-trader.py", "phase1_paper_trader")
    safety_module = load_script_module("execution-safety-layer.py", "phase1_execution_safety")
    planned_trades = (trader_stage.data or {}).get('planned_trades', [])
    if not planned_trades:
        return stage_result("authoritative_state_update", StageStatus.SKIPPED, "No trade records to persist")

    persisted = trader_module.persist_trade_records(planned_trades)
    performance = trader_module.calculate_performance()
    safety = safety_module.ExecutionSafetyLayer()
    breaker_refresh = safety.refresh_breaker_state_from_canonical_history()
    persisted_snapshot = safety.persist_runtime_state(
        "TRADE_OUTCOME_RECORDED",
        extra={
            'last_persisted_trade_count': persisted,
            'last_planned_trade_count': len(planned_trades),
            'last_performance_total_trades': performance.get('total_trades', 0),
            'last_performance_total_pnl_usd': performance.get('total_pnl_usd', 0),
            'last_breaker_refresh_changes': breaker_refresh.get('changed_fields', {}),
        },
        persist_reason="Authoritative state update persisted trade records and refreshed performance state",
    )
    return stage_result(
        "authoritative_state_update",
        StageStatus.SUCCESS,
        (
            f"Persisted {persisted} trade record(s) and refreshed performance state; "
            f"breaker_changes={breaker_refresh.get('changed_fields', {}) or 'none'}; "
            f"persisted {safety_snapshot_summary(persisted_snapshot)}"
        ),
        {
            'persisted_records': persisted,
            'performance': performance,
            'safety_state_after': persisted_snapshot,
            'breaker_state_after_persistence': breaker_refresh,
        },
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


def count_jsonl_records(path: Path) -> int:
    """Count non-empty JSONL lines for lightweight monitor summaries."""
    if not path.exists():
        return 0
    with open(path) as handle:
        return sum(1 for line in handle if line.strip())


def extract_first_int(pattern: str, text: str) -> int | None:
    match = re.search(pattern, text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def run_timeout_monitor() -> dict:
    """Run the timeout monitor because it reads canonical state and writes monitoring artifacts only."""
    report_path = WORKSPACE / "TIMEOUT_MONITOR_REPORT.md"
    history_path = LOGS_DIR / "timeout-history.jsonl"
    before_records = count_jsonl_records(history_path)
    command = ["python3", str(REPO_ROOT / "scripts" / "timeout-monitor.py")]

    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=90)
    except subprocess.TimeoutExpired as exc:
        return {
            'script': 'timeout-monitor.py',
            'status': StageStatus.FAIL.value,
            'reason': 'Timeout monitor exceeded 90s runtime budget',
            'summary': {
                'history_records_before': before_records,
                'history_records_after': before_records,
                'history_records_added': 0,
                'report_generated': report_path.exists(),
            },
            'stdout': exc.stdout or '',
            'stderr': exc.stderr or '',
            'command': command,
        }

    stdout = result.stdout or ''
    stderr = result.stderr or ''
    after_records = count_jsonl_records(history_path)
    positions_monitored = extract_first_int(r'Monitoring (\d+) positions', stdout)
    timeout_candidates = extract_first_int(r'\[TIME\]\s+(\d+) TIMEOUT CANDIDATES identified', stdout)
    if timeout_candidates is None and 'No timeout candidates' in stdout:
        timeout_candidates = 0

    summary = {
        'positions_monitored': positions_monitored or 0,
        'timeout_candidates': timeout_candidates if timeout_candidates is not None else 'UNKNOWN',
        'history_records_before': before_records,
        'history_records_after': after_records,
        'history_records_added': max(0, after_records - before_records),
        'report_generated': report_path.exists(),
        'report_path': str(report_path),
    }

    if result.returncode == 0:
        if positions_monitored == 0 and timeout_candidates in (None, 0):
            reason = 'Timeout monitor ran successfully; no open positions to track'
        else:
            reason = (
                'Timeout monitor ran successfully; '
                f"positions={summary['positions_monitored']} | "
                f"timeout_candidates={summary['timeout_candidates']} | "
                f"history_records_added={summary['history_records_added']} | "
                f"report_generated={summary['report_generated']}"
            )
        status = StageStatus.SUCCESS.value
    else:
        status = StageStatus.FAIL.value
        reason = stderr.strip() or stdout.strip() or 'Timeout monitor exited non-zero'

    return {
        'script': 'timeout-monitor.py',
        'status': status,
        'reason': reason,
        'summary': summary,
        'stdout': stdout,
        'stderr': stderr,
        'command': command,
    }


def evaluate_monitor_scripts() -> StageResult:
    """Run only monitor scripts that are truthful and safe in the canonical loop."""
    exit_monitor_result = {
        'script': 'exit-monitor.py',
        'status': StageStatus.SKIPPED.value,
        'reason': (
            'Skipped in canonical loop: script writes exit-proof artifacts for trigger events without '
            'updating authoritative trade/state files, so running it here could overstate real closes'
        ),
        'summary': {
            'compatible_with_canonical_state': False,
            'safe_in_canonical_loop': False,
            'behavior': 'monitoring_plus_reporting_with_exit-proof side effects',
        },
    }
    timeout_monitor_result = run_timeout_monitor()

    monitor_results = [exit_monitor_result, timeout_monitor_result]
    failures = [item for item in monitor_results if item['status'] == StageStatus.FAIL.value]
    executed = [item['script'] for item in monitor_results if item['status'] == StageStatus.SUCCESS.value]
    skipped = [item['script'] for item in monitor_results if item['status'] == StageStatus.SKIPPED.value]

    if failures:
        stage_status = StageStatus.FAIL
        stage_reason = (
            f"Executed={executed or ['none']} | Skipped={skipped or ['none']} | "
            f"Failures={[item['script'] for item in failures]}"
        )
    elif executed:
        stage_status = StageStatus.SUCCESS
        stage_reason = (
            f"Executed={executed} | Skipped={skipped or ['none']} | "
            'stage truthfully reports which monitor scripts actually ran'
        )
    else:
        stage_status = StageStatus.SKIPPED
        stage_reason = 'No canonical monitor scripts were safe to run'

    return stage_result(
        'monitors',
        stage_status,
        stage_reason,
        {
            'monitor_results': monitor_results,
            'executed_scripts': executed,
            'skipped_scripts': skipped,
            'failed_scripts': [item['script'] for item in failures],
        },
    )


def generate_agency_report(stage_results: list[StageResult], optional_components: dict, status_snapshot: dict | None = None):
    """Generate comprehensive report for supervisor"""
    
    performance = load_performance_data()
    open_positions = load_open_positions()
    latest_signals = load_latest_signals()
    health_manager = SystemHealthManager()
    health_state = health_manager.refresh_state()
    trading_response = health_manager.trading_response()
    status_snapshot = status_snapshot or health_manager.write_system_status()
    
    # Sort signals by EV
    latest_signals.sort(key=lambda x: x.get('ev_score', 0), reverse=True)
    
    monitor_stage = next((result for result in stage_results if result.stage == 'monitors'), None)

    report = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'agency': 'trading-phase1',
        'cycle_number': len(open_positions) + (performance.get('total_trades', 0) if performance else 0),
        
        'execution_results': {result.stage: result.status for result in stage_results},
        'execution_reasons': {result.stage: result.reason for result in stage_results},
        'stage_results': [asdict(result) for result in stage_results],
        'optional_components': optional_components,
        'monitoring_summary': (monitor_stage.data or {}) if monitor_stage else {},
        
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
            'operator_status': status_snapshot,
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

    optional_components = detect_optional_components(TRADING_MODE)
    health_manager = SystemHealthManager()
    print("Optional components:")
    for component_name, component_state in optional_components.items():
        print(f"  - {component_name}: {component_state['status']} ({component_state['reason']})")
    print()
    print(f"Trading mode: {TRADING_MODE}")
    print(f"  - Hyperliquid enabled: {mode_includes_hyperliquid(TRADING_MODE)}")
    print(f"  - Polymarket enabled: {mode_includes_polymarket(TRADING_MODE)}")
    print()

    stage_results: list[StageResult] = []
    bootstrap_stage = run_bootstrap_check()
    stage_results.append(bootstrap_stage)
    if bootstrap_stage.status == StageStatus.FAIL.value:
        generate_agency_report(stage_results, optional_components, health_manager.write_system_status())
        return

    opening_health = health_manager.trading_response()
    health_manager.write_system_status()
    print(
        f"System health: {opening_health['overall_status']} | "
        f"Recovery: {opening_health.get('recovery_state', 'NORMAL')} | "
        f"Cooldown: {opening_health.get('cooldown_remaining', 0)}s | "
        f"Operator mode: {opening_health.get('operator_control', {}).get('manual_mode', 'OFF')} | "
        f"Override: {opening_health.get('operator_control', {}).get('trading_override', 'ALLOW')}/"
        f"{opening_health.get('operator_control', {}).get('recovery_override', 'AUTO')} | "
        f"Action: {opening_health['action']} | "
        f"Alert: {opening_health.get('alert_level', 'INFO')} | "
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

    monitors_stage = evaluate_monitor_scripts()
    stage_results.append(monitors_stage)

    final_response = health_manager.trading_response()
    final_health_state = health_manager.refresh_state()
    final_status_snapshot = health_manager.write_system_status()
    if monitors_stage.data is None:
        monitors_stage.data = {}
    monitors_stage.data.update({
        'system_health': final_health_state,
        'action_taken': final_response,
        'system_status': final_status_snapshot,
    })
    monitors_stage.reason = (
        f"{monitors_stage.reason} | "
        f"Health {final_response['overall_status']} | "
        f"active_incidents={len(final_health_state.get('active_incidents', []))} | "
        f"resolved_recent={len(final_health_state.get('resolved_incidents', []))} | "
        f"cooldown_remaining={final_health_state.get('cooldown_remaining', 0)}s | "
        f"recovery_state={final_health_state.get('recovery_state', 'NORMAL')} | "
        f"operator_mode={final_response.get('operator_control', {}).get('manual_mode', 'OFF')} | "
        f"active_override={final_response.get('operator_control', {}).get('trading_override', 'ALLOW')}/"
        f"{final_response.get('operator_control', {}).get('recovery_override', 'AUTO')} | "
        f"action={final_response['action']} | "
        f"alert={final_response.get('alert_level', 'INFO')}"
    )
    
    print()
    print("=" * 80)
    print("GENERATING REPORT FOR SUPERVISOR")
    print("=" * 80)
    
    # Generate report
    report = generate_agency_report(stage_results, optional_components, final_status_snapshot)
    
    print()
    print(f"[STATS] Cycle #{report['cycle_number']} Complete")
    print("[OK] Stage status summary:")
    for result in stage_results:
        print(f"   - {result.stage}: {result.status} ({result.reason})")
    print(f"[TREND] State: {report['current_state']['open_positions']} open positions, {report['current_state']['latest_signals_count']} signals")
    print(
        f"[HEALTH] Health: {report['current_state']['system_health']['overall_status']} | "
        f"Active: {len(report['current_state']['system_health']['active_incidents'])} | "
        f"Resolved recent: {len(report['current_state']['system_health'].get('resolved_incidents', []))} | "
        f"Cooldown: {report['current_state']['system_health'].get('cooldown_remaining', 0)}s | "
        f"Recovery: {report['current_state']['action_taken'].get('recovery_state', report['current_state']['system_health'].get('recovery_state', 'NORMAL'))} | "
        f"Operator: {report['current_state']['action_taken'].get('operator_control', {}).get('manual_mode', 'OFF')} | "
        f"Override: {report['current_state']['action_taken'].get('operator_control', {}).get('trading_override', 'ALLOW')}/"
        f"{report['current_state']['action_taken'].get('operator_control', {}).get('recovery_override', 'AUTO')} | "
        f"Action: {report['current_state']['action_taken']['action']} | "
        f"Alert: {report['current_state']['action_taken'].get('alert_level', 'INFO')}"
    )
    
    if report['performance_summary'].get('total_trades', 0) > 0:
        perf = report['performance_summary']
        print(f"[MONEY] Performance: {perf['total_trades']} trades, {perf['win_rate']}% WR, ${perf['total_pnl_usd']:+.2f} PnL")
    else:
        print(f"[PENDING] Performance: No closed trades yet")
    
    print()
    
    if report['supervisor_action_required']:
        print("[ALERT] SUPERVISOR ACTION REQUIRED:")
        for action in report['supervisor_action_required']:
            print(f"  - {action['type'].upper()}: {action['reason']}")
            print(f"    -> {action['recommendation']}")
    else:
        print("[OK] No supervisor action required - agency operating normally")
    
    print()
    print(f"[REPORT] Full report saved: {AGENCY_REPORT}")
    print("=" * 80)


if __name__ == "__main__":
    main()
