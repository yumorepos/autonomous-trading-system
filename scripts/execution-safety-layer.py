#!/usr/bin/env python3
"""
Execution Safety & Reliability Layer
Pre-trade validation, circuit breakers, kill switches, and operational risk
monitoring. Critical checks can actively block trade entry proposals.
"""

import json
import sys
import time
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, asdict
from enum import Enum

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.runtime import WORKSPACE_ROOT as WORKSPACE, LOGS_DIR, DATA_DIR
from models.paper_contracts import paper_position_identifier
from models.trade_schema import is_trade_closed, is_trade_open, normalize_trade_record, validate_trade_record
from utils.system_health import SystemHealthManager
from utils.paper_exchange_adapters import get_paper_exchange_adapter
SAFETY_STATE = LOGS_DIR / "execution-safety-state.json"
BLOCKED_ACTIONS = LOGS_DIR / "blocked-actions.jsonl"
INCIDENT_LOG = LOGS_DIR / "incident-log.jsonl"
SAFETY_REPORT = WORKSPACE / "EXECUTION_SAFETY_REPORT.md"
PORTFOLIO_ALLOCATION = LOGS_DIR / "portfolio-allocation.json"
STRATEGY_REGISTRY = LOGS_DIR / "strategy-registry.json"
PAPER_TRADES_FILE = LOGS_DIR / "phase1-paper-trades.jsonl"

# Safety Thresholds
SAFETY_LIMITS = {
    'max_signal_age_seconds': 300,          # 5 minutes max signal age
    'max_slippage_pct': 0.5,                # 0.5% max slippage
    'min_liquidity_usd': 10000,             # $10K min liquidity
    'max_spread_pct': 1.0,                  # 1% max bid-ask spread
    'min_exchange_uptime_pct': 99.0,        # 99% uptime required
    'max_api_latency_ms': 1000,             # 1 second max API response
    'duplicate_order_window_seconds': 60,   # 60 second deduplication window
    'max_portfolio_drawdown_pct': 15.0,     # 15% max portfolio DD
    'max_daily_trades': 50,                 # 50 trades per day max
    'max_position_size_usd': 20,            # $20 max per position
    'cooldown_after_loss_seconds': 300      # 5 min cooldown after loss
}

# Circuit Breaker Thresholds
CIRCUIT_BREAKERS = {
    'max_consecutive_losses': 5,
    'max_daily_loss_usd': 10,
    'max_hourly_loss_usd': 3,
    'max_drawdown_from_peak_pct': 20,
    'min_time_between_trades_seconds': 60
}


class SystemStatus(Enum):
    SAFE = "SAFE"
    CAUTION = "CAUTION"
    HALT = "HALT"


@dataclass
class ValidationResult:
    passed: bool
    check_name: str
    reason: str
    severity: str  # INFO, WARNING, CRITICAL
    timestamp: str
    data: Optional[Dict] = None


@dataclass
class TradeProposal:
    exchange: str
    strategy: str
    asset: str
    direction: str  # LONG/SHORT or YES/NO
    entry_price: float
    position_size_usd: float
    signal_timestamp: str
    allocation_weight: float
    
    def to_dict(self):
        return asdict(self)


class ExecutionSafetyLayer:
    """Validates all proposed trades before execution"""
    
    def __init__(self):
        self.state = self.load_state()
        self.recent_trades = self.load_recent_trades()
        self.incident_history = self.load_incidents()
        self.health_manager = SystemHealthManager()
    
    def load_state(self) -> Dict:
        """Load current safety state"""
        if SAFETY_STATE.exists():
            with open(SAFETY_STATE) as f:
                return json.load(f)
        
        return {
            'status': SystemStatus.SAFE.value,
            'last_update': None,
            'circuit_breakers': {
                'consecutive_losses': 0,
                'daily_loss_usd': 0,
                'hourly_loss_usd': 0,
                'peak_balance': 97.80,
                'last_trade_timestamp': None
            },
            'exchange_health': {},
            'last_incident': None,
            'kill_switch_active': False,
            'manual_override': False,
            'runtime_enforcement': {
                'last_transition': None,
                'last_transition_at': None,
                'last_persist_reason': None,
                'last_proposal': None,
                'last_validation_summary': None,
                'last_validation_result': None,
                'last_planned_trade_count': 0,
                'last_persisted_trade_count': 0,
                'blocked_actions_count': 0,
                'breaker_accounting_source': 'advisory_static_defaults',
                'cooldown_enforcement_mode': 'advisory_config_only',
            },
        }
    
    def save_state(self):
        """Save current safety state"""
        self.state['last_update'] = datetime.now(timezone.utc).isoformat()
        with open(SAFETY_STATE, 'w') as f:
            json.dump(self.state, f, indent=2)

    def _count_jsonl_records(self, path: Path) -> int:
        if not path.exists():
            return 0

        count = 0
        with open(path) as handle:
            for line in handle:
                if line.strip():
                    count += 1
        return count

    def snapshot_state(self) -> Dict:
        runtime = self.state.get('runtime_enforcement', {})
        breakers = self.state.get('circuit_breakers', {})
        return {
            'status': self.state.get('status'),
            'kill_switch_active': self.state.get('kill_switch_active', False),
            'manual_override': self.state.get('manual_override', False),
            'exchange_health': self.state.get('exchange_health', {}),
            'circuit_breakers': {
                'consecutive_losses': breakers.get('consecutive_losses', 0),
                'daily_loss_usd': breakers.get('daily_loss_usd', 0),
                'hourly_loss_usd': breakers.get('hourly_loss_usd', 0),
                'peak_balance': breakers.get('peak_balance', 97.80),
                'last_trade_timestamp': breakers.get('last_trade_timestamp'),
            },
            'runtime_enforcement': {
                'last_transition': runtime.get('last_transition'),
                'last_transition_at': runtime.get('last_transition_at'),
                'last_persist_reason': runtime.get('last_persist_reason'),
                'last_validation_result': runtime.get('last_validation_result'),
                'last_planned_trade_count': runtime.get('last_planned_trade_count', 0),
                'last_persisted_trade_count': runtime.get('last_persisted_trade_count', 0),
                'blocked_actions_count': runtime.get('blocked_actions_count', 0),
                'breaker_accounting_source': runtime.get('breaker_accounting_source', 'advisory_static_defaults'),
                'cooldown_enforcement_mode': runtime.get('cooldown_enforcement_mode', 'advisory_config_only'),
                'breaker_accounting_updated_at': runtime.get('breaker_accounting_updated_at'),
            },
        }

    def _canonical_trade_history(self) -> List[Dict]:
        if not PAPER_TRADES_FILE.exists():
            return []

        trades: List[Dict] = []
        with open(PAPER_TRADES_FILE) as handle:
            for line in handle:
                if not line.strip():
                    continue
                record = normalize_trade_record(json.loads(line))
                if not validate_trade_record(record, context='execution-safety.trade-history'):
                    continue
                trades.append(record)
        return trades

    def refresh_breaker_state_from_canonical_history(self) -> Dict:
        trades = self._canonical_trade_history()
        closed_trades = [trade for trade in trades if is_trade_closed(trade)]
        closed_trades.sort(key=lambda trade: trade.get('exit_timestamp') or trade.get('entry_timestamp') or '')

        now = datetime.now(timezone.utc)
        hourly_cutoff = now - timedelta(hours=1)
        daily_cutoff = now - timedelta(hours=24)

        consecutive_losses = 0
        for trade in reversed(closed_trades):
            pnl = float(trade.get('realized_pnl_usd') or 0)
            if pnl < 0:
                consecutive_losses += 1
                continue
            break

        daily_loss_usd = 0.0
        hourly_loss_usd = 0.0
        for trade in closed_trades:
            pnl = float(trade.get('realized_pnl_usd') or 0)
            if pnl >= 0:
                continue
            exit_timestamp = trade.get('exit_timestamp')
            if not exit_timestamp:
                continue
            exit_time = datetime.fromisoformat(exit_timestamp.replace('Z', '+00:00'))
            loss_amount = abs(pnl)
            if exit_time >= daily_cutoff:
                daily_loss_usd += loss_amount
            if exit_time >= hourly_cutoff:
                hourly_loss_usd += loss_amount

        last_trade_timestamp = None
        if trades:
            latest_trade = max(
                trades,
                key=lambda trade: trade.get('exit_timestamp') or trade.get('entry_timestamp') or '',
            )
            last_trade_timestamp = latest_trade.get('exit_timestamp') or latest_trade.get('entry_timestamp')

        breakers = self.state.setdefault('circuit_breakers', {})
        previous_breakers = {
            'consecutive_losses': breakers.get('consecutive_losses', 0),
            'daily_loss_usd': breakers.get('daily_loss_usd', 0.0),
            'hourly_loss_usd': breakers.get('hourly_loss_usd', 0.0),
            'last_trade_timestamp': breakers.get('last_trade_timestamp'),
        }

        breakers['consecutive_losses'] = consecutive_losses
        breakers['daily_loss_usd'] = round(daily_loss_usd, 8)
        breakers['hourly_loss_usd'] = round(hourly_loss_usd, 8)
        breakers['last_trade_timestamp'] = last_trade_timestamp

        runtime = self.state.setdefault('runtime_enforcement', {})
        runtime['breaker_accounting_source'] = 'persisted_trade_history'
        runtime['breaker_accounting_updated_at'] = now.isoformat()
        runtime['cooldown_enforcement_mode'] = 'advisory_config_only'

        changed_fields = {
            field: {
                'before': previous_breakers[field],
                'after': breakers.get(field),
            }
            for field in previous_breakers
            if previous_breakers[field] != breakers.get(field)
        }
        return {
            'changed_fields': changed_fields,
            'breaker_snapshot': {
                'consecutive_losses': breakers.get('consecutive_losses', 0),
                'daily_loss_usd': breakers.get('daily_loss_usd', 0.0),
                'hourly_loss_usd': breakers.get('hourly_loss_usd', 0.0),
                'last_trade_timestamp': breakers.get('last_trade_timestamp'),
            },
        }

    def persist_runtime_state(
        self,
        transition: str,
        *,
        proposal: Optional[TradeProposal] = None,
        summary: Optional[Dict] = None,
        extra: Optional[Dict] = None,
        persist_reason: str,
    ) -> Dict:
        runtime = self.state.setdefault('runtime_enforcement', {})
        runtime['last_transition'] = transition
        runtime['last_transition_at'] = datetime.now(timezone.utc).isoformat()
        runtime['last_persist_reason'] = persist_reason
        runtime['last_proposal'] = proposal.to_dict() if proposal else runtime.get('last_proposal')
        runtime['last_validation_summary'] = summary or runtime.get('last_validation_summary')
        if summary is not None:
            failed = summary.get('failed_critical_checks', [])
            runtime['last_validation_result'] = 'BLOCKED' if failed else 'PASSED'
        if extra:
            runtime.update(extra)

        runtime['blocked_actions_count'] = self._count_jsonl_records(BLOCKED_ACTIONS)
        self.state['status'] = self.determine_system_status().value
        self.save_state()
        return self.snapshot_state()
    
    def load_recent_trades(self) -> List[Dict]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        recent = []

        for trade in self._canonical_trade_history():
            entry_timestamp = trade.get('entry_timestamp')
            if not entry_timestamp:
                continue
            entry_time = datetime.fromisoformat(entry_timestamp.replace('Z', '+00:00'))
            if entry_time > cutoff:
                recent.append(trade)

        return recent
    
    def load_incidents(self) -> List[Dict]:
        """Load incident history"""
        if not INCIDENT_LOG.exists():
            return []
        
        incidents = []
        with open(INCIDENT_LOG) as f:
            for line in f:
                if line.strip():
                    incidents.append(json.loads(line))
        
        return incidents[-100:]  # Last 100 incidents
    
    def log_incident(self, severity: str, message: str, data: Dict = None):
        """Log safety incident"""
        incident = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'severity': severity,
            'message': message,
            'data': data or {}
        }
        
        self.incident_history.append(incident)
        self.state['last_incident'] = incident
        
        with open(INCIDENT_LOG, 'a') as f:
            f.write(json.dumps(incident) + '\n')
    
    def log_blocked_action(self, proposal: TradeProposal, reason: str, validation_results: List[ValidationResult]):
        """Log blocked trade with full validation details"""
        blocked = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'proposal': proposal.to_dict(),
            'reason': reason,
            'validations': [asdict(r) for r in validation_results]
        }
        
        with open(BLOCKED_ACTIONS, 'a') as f:
            f.write(json.dumps(blocked) + '\n')
    
    # === PRE-TRADE VALIDATION CHECKS ===
    
    def check_signal_freshness(self, proposal: TradeProposal) -> ValidationResult:
        """Ensure signal is not stale"""
        signal_time = datetime.fromisoformat(proposal.signal_timestamp.replace('Z', '+00:00'))
        age_seconds = (datetime.now(timezone.utc) - signal_time).total_seconds()
        
        passed = age_seconds <= SAFETY_LIMITS['max_signal_age_seconds']
        
        return ValidationResult(
            passed=passed,
            check_name="signal_freshness",
            reason=f"Signal age: {age_seconds:.0f}s (max: {SAFETY_LIMITS['max_signal_age_seconds']}s)",
            severity="CRITICAL" if not passed else "INFO",
            timestamp=datetime.now(timezone.utc).isoformat(),
            data={'age_seconds': age_seconds}
        )
    
    def check_duplicate_order(self, proposal: TradeProposal) -> ValidationResult:
        """Prevent duplicate orders"""
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=SAFETY_LIMITS['duplicate_order_window_seconds'])

        duplicates = []
        for trade in self.recent_trades:
            if not is_trade_open(trade):
                continue
            entry_timestamp = trade.get('entry_timestamp')
            if not entry_timestamp:
                continue
            if datetime.fromisoformat(entry_timestamp.replace('Z', '+00:00')) <= cutoff:
                continue

            trade_asset = paper_position_identifier(trade)
            trade_direction = trade.get('side')
            if trade_asset == proposal.asset and trade_direction == proposal.direction:
                duplicates.append(trade)
        
        passed = len(duplicates) == 0
        
        return ValidationResult(
            passed=passed,
            check_name="duplicate_order",
            reason=f"Found {len(duplicates)} duplicate open orders" if duplicates else "No duplicates",
            severity="CRITICAL" if not passed else "INFO",
            timestamp=datetime.now(timezone.utc).isoformat(),
            data={'duplicates': len(duplicates)}
        )
    
    def check_position_size(self, proposal: TradeProposal) -> ValidationResult:
        """Validate position size limits"""
        passed = proposal.position_size_usd <= SAFETY_LIMITS['max_position_size_usd']
        
        return ValidationResult(
            passed=passed,
            check_name="position_size",
            reason=f"Position: ${proposal.position_size_usd:.2f} (max: ${SAFETY_LIMITS['max_position_size_usd']})",
            severity="CRITICAL" if not passed else "INFO",
            timestamp=datetime.now(timezone.utc).isoformat(),
            data={'position_size': proposal.position_size_usd}
        )
    
    def check_exchange_health(self, exchange: str = "Hyperliquid") -> ValidationResult:
        """Check exchange API health and latency via the canonical exchange adapter."""
        try:
            start = time.time()
            adapter = get_paper_exchange_adapter(exchange)
            if adapter is None:
                raise RuntimeError(f"Unsupported exchange {exchange!r}")
            adapter.fetch_health(requests)
            latency_ms = (time.time() - start) * 1000
            
            passed = latency_ms <= SAFETY_LIMITS['max_api_latency_ms']
            
            # Update state
            self.state['exchange_health'][exchange] = {
                'status': 'UP' if passed else 'SLOW',
                'latency_ms': latency_ms,
                'last_check': datetime.now(timezone.utc).isoformat()
            }
            
            return ValidationResult(
                passed=passed,
                check_name="exchange_health",
                reason=f"{exchange} latency: {latency_ms:.0f}ms (max: {SAFETY_LIMITS['max_api_latency_ms']}ms)",
                severity="WARNING" if not passed else "INFO",
                timestamp=datetime.now(timezone.utc).isoformat(),
                data={'latency_ms': latency_ms}
            )
        
        except Exception as e:
            self.state['exchange_health'][exchange] = {
                'status': 'DOWN',
                'error': str(e),
                'last_check': datetime.now(timezone.utc).isoformat()
            }
            
            return ValidationResult(
                passed=False,
                check_name="exchange_health",
                reason=f"{exchange} API error: {e}",
                severity="CRITICAL",
                timestamp=datetime.now(timezone.utc).isoformat(),
                data={'error': str(e)}
            )
    
    def check_liquidity(self, proposal: TradeProposal) -> ValidationResult:
        """Check market liquidity via the canonical exchange adapter."""
        try:
            adapter = get_paper_exchange_adapter(proposal.exchange)
            if adapter is None:
                raise RuntimeError(f"Unsupported exchange {proposal.exchange!r}")
            volume_24h = adapter.fetch_liquidity(proposal.asset, requests)
            if volume_24h is None:
                return ValidationResult(
                    passed=False,
                    check_name="liquidity",
                    reason=f"{proposal.exchange} market {proposal.asset} not found",
                    severity="CRITICAL",
                    timestamp=datetime.now(timezone.utc).isoformat()
                )

            passed = volume_24h >= SAFETY_LIMITS['min_liquidity_usd']
            
            return ValidationResult(
                passed=passed,
                check_name="liquidity",
                reason=f"24h volume: ${volume_24h:,.0f} (min: ${SAFETY_LIMITS['min_liquidity_usd']:,})",
                severity="WARNING" if not passed else "INFO",
                timestamp=datetime.now(timezone.utc).isoformat(),
                data={'volume_24h': volume_24h}
            )
        
        except Exception as e:
            return ValidationResult(
                passed=False,
                check_name="liquidity",
                reason=f"Liquidity check failed: {e}",
                severity="WARNING",
                timestamp=datetime.now(timezone.utc).isoformat(),
                data={'error': str(e)}
            )
    
    def check_spread(self, proposal: TradeProposal) -> ValidationResult:
        """Check bid-ask spread as an advisory sanity signal (not a blocking gate)."""
        try:
            adapter = get_paper_exchange_adapter(proposal.exchange)
            if adapter is None:
                raise RuntimeError(f"Unsupported exchange {proposal.exchange!r}")
            best_bid, best_ask = adapter.fetch_spread(proposal.asset, proposal.direction, requests)
            if best_bid is None or best_ask is None:
                return ValidationResult(
                    passed=False,
                    check_name="spread",
                    reason=f"{proposal.exchange} order book unavailable",
                    severity="WARNING",
                    timestamp=datetime.now(timezone.utc).isoformat()
                )
            spread_pct = ((best_ask - best_bid) / best_bid) * 100
            
            passed = spread_pct <= SAFETY_LIMITS['max_spread_pct']
            
            return ValidationResult(
                passed=passed,
                check_name="spread",
                reason=f"Spread: {spread_pct:.2f}% (max: {SAFETY_LIMITS['max_spread_pct']}%)",
                severity="WARNING" if not passed else "INFO",
                timestamp=datetime.now(timezone.utc).isoformat(),
                data={'spread_pct': spread_pct, 'bid': best_bid, 'ask': best_ask}
            )
        
        except Exception as e:
            return ValidationResult(
                passed=True,
                check_name="spread",
                reason=f"Spread check unavailable (advisory only): {e}",
                severity="WARNING",
                timestamp=datetime.now(timezone.utc).isoformat(),
                data={'error': str(e)}
            )
    
    def check_circuit_breakers(self) -> ValidationResult:
        """Check portfolio-level circuit breakers"""
        breakers = self.state['circuit_breakers']
        
        failures = []
        
        # Consecutive losses
        if breakers['consecutive_losses'] >= CIRCUIT_BREAKERS['max_consecutive_losses']:
            failures.append(f"{breakers['consecutive_losses']} consecutive losses")
        
        # Daily loss
        if breakers['daily_loss_usd'] >= CIRCUIT_BREAKERS['max_daily_loss_usd']:
            failures.append(f"${breakers['daily_loss_usd']:.2f} daily loss")
        
        # Hourly loss
        if breakers['hourly_loss_usd'] >= CIRCUIT_BREAKERS['max_hourly_loss_usd']:
            failures.append(f"${breakers['hourly_loss_usd']:.2f} hourly loss")
        
        # Drawdown from peak
        current_balance = 97.80  # TODO: Get from live balance
        peak = breakers['peak_balance']
        dd_pct = ((peak - current_balance) / peak) * 100 if peak > 0 else 0
        
        if dd_pct >= CIRCUIT_BREAKERS['max_drawdown_from_peak_pct']:
            failures.append(f"{dd_pct:.1f}% drawdown from peak")
        
        # Time between trades
        if breakers['last_trade_timestamp']:
            last_trade = datetime.fromisoformat(breakers['last_trade_timestamp'])
            seconds_since = (datetime.now(timezone.utc) - last_trade).total_seconds()
            
            if seconds_since < CIRCUIT_BREAKERS['min_time_between_trades_seconds']:
                failures.append(f"Only {seconds_since:.0f}s since last trade (min: {CIRCUIT_BREAKERS['min_time_between_trades_seconds']}s)")
        
        passed = len(failures) == 0
        
        return ValidationResult(
            passed=passed,
            check_name="circuit_breakers",
            reason=" | ".join(failures) if failures else "All circuit breakers OK",
            severity="CRITICAL" if not passed else "INFO",
            timestamp=datetime.now(timezone.utc).isoformat(),
            data={'breakers_triggered': failures}
        )
    
    def check_kill_switch(self) -> ValidationResult:
        """Check emergency kill switch"""
        passed = not self.state['kill_switch_active']
        
        return ValidationResult(
            passed=passed,
            check_name="kill_switch",
            reason="KILL SWITCH ACTIVE - All trading halted" if not passed else "Kill switch off",
            severity="CRITICAL" if not passed else "INFO",
            timestamp=datetime.now(timezone.utc).isoformat()
        )
    
    def check_data_integrity(self) -> ValidationResult:
        """Validate data integrity across system"""
        issues = []
        
        if PORTFOLIO_ALLOCATION.exists():
            with open(PORTFOLIO_ALLOCATION) as f:
                allocation = json.load(f)
            
            if allocation.get('timestamp'):
                alloc_time = datetime.fromisoformat(allocation['timestamp'].replace('Z', '+00:00'))
                age = (datetime.now(timezone.utc) - alloc_time).total_seconds()
                
                if age > 3600 * 6:  # 6 hours
                    issues.append(f"Allocation data stale ({age/3600:.1f}h old)")
        
        if STRATEGY_REGISTRY.exists():
            with open(STRATEGY_REGISTRY) as f:
                registry = json.load(f)
            if registry.get('generated_at'):
                registry_time = datetime.fromisoformat(registry['generated_at'].replace('Z', '+00:00'))
                age = (datetime.now(timezone.utc) - registry_time).total_seconds()
                if age > 3600 * 12:
                    issues.append(f"Strategy registry stale ({age/3600:.1f}h old)")
        
        passed = len(issues) == 0
        
        return ValidationResult(
            passed=passed,
            check_name="data_integrity",
            reason=" | ".join(issues) if issues else "Data integrity OK",
            severity="WARNING" if not passed else "INFO",
            timestamp=datetime.now(timezone.utc).isoformat(),
            data={'issues': issues}
        )
    
    # === VALIDATION ORCHESTRATION ===
    
    def validate_trade(self, proposal: TradeProposal) -> Tuple[bool, List[ValidationResult]]:
        """Run enforced pre-trade checks plus advisory sanity checks."""
        results = []
        
        # Critical checks (any failure = block)
        results.append(self.check_kill_switch())
        results.append(self.check_signal_freshness(proposal))
        results.append(self.check_duplicate_order(proposal))
        results.append(self.check_position_size(proposal))
        results.append(self.check_circuit_breakers())
        
        # Health checks (failures = caution)
        results.append(self.check_exchange_health(proposal.exchange))
        results.append(self.check_data_integrity())
        
        # Market checks (failures = caution)
        results.append(self.check_liquidity(proposal))
        results.append(self.check_spread(proposal))
        
        # Determine overall pass/fail
        critical_checks = [r for r in results if r.severity == "CRITICAL"]
        failed_critical = [r for r in critical_checks if not r.passed]
        
        passed = len(failed_critical) == 0

        warnings = [r for r in results if r.severity == "WARNING" and not r.passed]
        if failed_critical:
            severity = "HIGH"
            if any(r.check_name in {"kill_switch", "circuit_breakers"} for r in failed_critical):
                severity = "CRITICAL"
            self.health_manager.record_incident(
                incident_type="safety_failure",
                severity=severity,
                source="execution-safety",
                message=" | ".join(result.reason for result in failed_critical),
                affected_system="trade-entry",
                affected_components=["execution_safety", "trade_entry"],
                metadata={
                    "asset": proposal.asset,
                    "strategy": proposal.strategy,
                    "checks": [asdict(result) for result in failed_critical],
                },
            )
        elif warnings:
            self.health_manager.record_incident(
                incident_type="safety_warning",
                severity="LOW",
                source="execution-safety",
                message=" | ".join(result.reason for result in warnings),
                affected_system="trade-entry",
                affected_components=["execution_safety"],
                metadata={
                    "asset": proposal.asset,
                    "strategy": proposal.strategy,
                    "checks": [asdict(result) for result in warnings],
                },
            )
        else:
            self.health_manager.resolve_incident(
                incident_type="safety_failure",
                source="execution-safety",
                affected_trade=proposal.asset,
                metadata_match={"strategy": proposal.strategy},
                resolution_reason="All enforced safety conditions passed again for the candidate trade",
            )
            self.health_manager.resolve_incident(
                incident_type="safety_warning",
                source="execution-safety",
                affected_trade=proposal.asset,
                metadata_match={"strategy": proposal.strategy},
                resolution_reason="Safety advisory conditions cleared for the candidate trade",
            )

        return passed, results

    def summarize_validation_results(self, results: List[ValidationResult]) -> Dict:
        """Summarize enforced failures and advisory warnings for orchestrator logging."""
        failed_critical = [r for r in results if r.severity == "CRITICAL" and not r.passed]
        warnings = [r for r in results if r.severity == "WARNING" and not r.passed]
        return {
            'failed_critical_checks': [asdict(result) for result in failed_critical],
            'warning_checks': [asdict(result) for result in warnings],
            'reason': (
                " | ".join(result.reason for result in failed_critical)
                if failed_critical else "All enforced safety checks passed"
            ),
        }
    
    def determine_system_status(self) -> SystemStatus:
        """Determine overall system status"""
        
        # Check kill switch
        if self.state['kill_switch_active']:
            return SystemStatus.HALT
        
        # Check circuit breakers
        breakers = self.state['circuit_breakers']
        
        if (breakers['consecutive_losses'] >= CIRCUIT_BREAKERS['max_consecutive_losses'] or
            breakers['daily_loss_usd'] >= CIRCUIT_BREAKERS['max_daily_loss_usd']):
            return SystemStatus.HALT
        
        # Check exchange health
        for exchange, health in self.state['exchange_health'].items():
            if health['status'] == 'DOWN':
                return SystemStatus.HALT
            if health['status'] == 'SLOW':
                return SystemStatus.CAUTION
        
        # Check recent incidents
        if self.incident_history:
            recent = [i for i in self.incident_history 
                     if datetime.fromisoformat(i['timestamp']) > 
                     datetime.now(timezone.utc) - timedelta(hours=1)]
            
            critical_recent = [i for i in recent if i['severity'] == 'CRITICAL']
            
            if len(critical_recent) >= 3:
                return SystemStatus.HALT
            elif len(critical_recent) >= 1:
                return SystemStatus.CAUTION
        
        return SystemStatus.SAFE
    
    def generate_safety_report(self) -> str:
        """Generate operational risk report"""
        status = self.determine_system_status()
        
        lines = []
        lines.append("# EXECUTION SAFETY REPORT")
        lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M EDT')}")
        lines.append(f"**System Status:** {status.value}")
        lines.append("")
        
        # Status indicator
        if status == SystemStatus.SAFE:
            lines.append("[GREEN] **SAFE** -- All systems operational, trading allowed")
        elif status == SystemStatus.CAUTION:
            lines.append("[YELLOW] **CAUTION** -- Non-critical issues detected, trading restricted")
        else:
            lines.append("[RED] **HALT** -- Critical issues detected, trading halted")
        
        lines.append("")
        lines.append("---")
        lines.append("")
        
        # Circuit breakers
        lines.append("## Circuit Breakers")
        lines.append("")
        breakers = self.state['circuit_breakers']
        lines.append(f"- **Consecutive Losses:** {breakers['consecutive_losses']}/{CIRCUIT_BREAKERS['max_consecutive_losses']}")
        lines.append(f"- **Daily Loss:** ${breakers['daily_loss_usd']:.2f}/${CIRCUIT_BREAKERS['max_daily_loss_usd']}")
        lines.append(f"- **Hourly Loss:** ${breakers['hourly_loss_usd']:.2f}/${CIRCUIT_BREAKERS['max_hourly_loss_usd']}")
        
        current_balance = 97.80
        peak = breakers['peak_balance']
        dd_pct = ((peak - current_balance) / peak) * 100 if peak > 0 else 0
        lines.append(f"- **Drawdown from Peak:** {dd_pct:.1f}%/{CIRCUIT_BREAKERS['max_drawdown_from_peak_pct']}%")
        lines.append("")
        lines.append("---")
        lines.append("")
        
        # Exchange health
        lines.append("## Exchange Health")
        lines.append("")
        for exchange, health in self.state['exchange_health'].items():
            status_icon = "[GREEN]" if health['status'] == 'UP' else "[YELLOW]" if health['status'] == 'SLOW' else "[RED]"
            lines.append(f"### {status_icon} {exchange}")
            lines.append(f"**Status:** {health['status']}")
            if 'latency_ms' in health:
                lines.append(f"**Latency:** {health['latency_ms']:.0f}ms")
            if 'error' in health:
                lines.append(f"**Error:** {health['error']}")
            lines.append(f"**Last Check:** {health['last_check']}")
            lines.append("")
        
        lines.append("---")
        lines.append("")
        
        # Recent incidents
        if self.incident_history:
            recent = self.incident_history[-5:]
            lines.append("## Recent Incidents (Last 5)")
            lines.append("")
            for incident in reversed(recent):
                severity_icon = "[RED]" if incident['severity'] == 'CRITICAL' else "[YELLOW]" if incident['severity'] == 'WARNING' else "[INFO]"
                lines.append(f"### {severity_icon} {incident['severity']}")
                lines.append(f"**Time:** {incident['timestamp']}")
                lines.append(f"**Message:** {incident['message']}")
                lines.append("")
        
        lines.append("---")
        lines.append("")
        
        # Kill switch
        lines.append("## Emergency Controls")
        lines.append("")
        lines.append(f"- **Kill Switch:** {'[RED] ACTIVE' if self.state['kill_switch_active'] else '[GREEN] OFF'}")
        lines.append(f"- **Manual Override:** {'YES' if self.state['manual_override'] else 'NO'}")
        lines.append("")
        
        return "\n".join(lines)


def main():
    print("=" * 80)
    print("EXECUTION SAFETY LAYER -- Operational Risk Monitor")
    print(f"Check Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S EDT')}")
    print("=" * 80)
    print()
    
    safety = ExecutionSafetyLayer()
    
    # Determine system status
    status = safety.determine_system_status()
    
    print(f"System Status: {status.value}")
    print()
    
    # Run health checks
    print("Running health checks...")
    
    exchange_health = safety.check_exchange_health()
    print(f"  Exchange Health: {'[OK]' if exchange_health.passed else '[FAIL]'} {exchange_health.reason}")
    
    data_integrity = safety.check_data_integrity()
    print(f"  Data Integrity: {'[OK]' if data_integrity.passed else '[FAIL]'} {data_integrity.reason}")
    
    circuit_breakers = safety.check_circuit_breakers()
    print(f"  Circuit Breakers: {'[OK]' if circuit_breakers.passed else '[FAIL]'} {circuit_breakers.reason}")
    
    kill_switch = safety.check_kill_switch()
    print(f"  Kill Switch: {'[OK]' if kill_switch.passed else '[FAIL]'} {kill_switch.reason}")
    
    print()
    
    # Save state
    safety.state['status'] = status.value
    safety.save_state()
    
    # Generate report
    report = safety.generate_safety_report()
    
    with open(SAFETY_REPORT, 'w') as f:
        f.write(report)
    
    print("=" * 80)
    print(f"[OK] Safety check complete")
    print(f"[REPORT] Report: {SAFETY_REPORT}")
    print(f"[STATS] State: {SAFETY_STATE}")
    print("=" * 80)


if __name__ == "__main__":
    main()
