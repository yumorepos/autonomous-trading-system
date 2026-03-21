#!/usr/bin/env python3
"""
Data Integrity & Signal Reliability Layer
Validates all inputs before they influence signal generation, trading, governance, or allocation
Sits between data sources and signal scanner
"""

import json
import sys
import requests
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.runtime import WORKSPACE_ROOT as WORKSPACE, LOGS_DIR, DATA_DIR
from utils.system_health import SystemHealthManager
DATA_STATE = LOGS_DIR / "data-integrity-state.json"
REJECTED_SIGNALS = LOGS_DIR / "rejected-signals.jsonl"
SOURCE_METRICS = LOGS_DIR / "source-reliability-metrics.json"
DATA_HEALTH_REPORT = WORKSPACE / "DATA_HEALTH_REPORT.md"

# Data Quality Thresholds
DATA_QUALITY = {
    'max_data_age_seconds': 60,              # 1 minute max data age
    'max_fetch_failures': 3,                 # 3 consecutive failures → DEGRADED
    'min_asset_count': 100,                  # Min 100 assets from Hyperliquid
    'min_market_count': 3,                   # Min 3 markets from Polymarket
    'max_price_change_pct': 50,              # 50% max price change (outlier detection)
    'min_volume_usd': 1000,                  # $1K min volume for validity
    'max_spread_pct': 5.0,                   # 5% max spread for data validity
    'min_funding_consistency_hours': 2,      # 2 hours funding stability required
    'signal_decay_hours': 1,                 # 1 hour max signal age
    'required_fields': {                     # Required fields per data type
        'funding': ['coin', 'funding', 'prevDayNtlVlm', 'openInterest'],
        'market': ['question', 'tokens'],
        'signal': ['asset', 'entry_price', 'signal_type', 'timestamp']
    }
}


class DataHealth(Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    HALT = "HALT"


@dataclass
class DataSource:
    name: str
    url: str
    last_success: Optional[str]
    last_failure: Optional[str]
    consecutive_failures: int
    total_requests: int
    total_failures: int
    avg_latency_ms: float
    health: str
    last_data_timestamp: Optional[str]
    
    def success_rate(self) -> float:
        if self.total_requests == 0:
            return 0
        return ((self.total_requests - self.total_failures) / self.total_requests) * 100


@dataclass
class ValidationResult:
    passed: bool
    check_name: str
    reason: str
    severity: str
    data: Optional[Dict] = None


class DataIntegrityLayer:
    """Validates all data inputs before they can influence the system"""
    
    def __init__(self):
        self.state = self.load_state()
        self.metrics = self.load_metrics()
        self.health_manager = SystemHealthManager()
    
    def load_state(self) -> Dict:
        """Load current data state"""
        if DATA_STATE.exists():
            with open(DATA_STATE) as f:
                return json.load(f)
        
        return {
            'health': DataHealth.HEALTHY.value,
            'last_update': None,
            'sources': {
                'hyperliquid': {
                    'last_success': None,
                    'last_failure': None,
                    'consecutive_failures': 0,
                    'health': 'UNKNOWN'
                },
                'polymarket': {
                    'last_success': None,
                    'last_failure': None,
                    'consecutive_failures': 0,
                    'health': 'UNKNOWN'
                }
            },
            'last_validated_data': {},
            'validation_failures': []
        }
    
    def save_state(self):
        """Save current state"""
        self.state['last_update'] = datetime.now(timezone.utc).isoformat()
        with open(DATA_STATE, 'w') as f:
            json.dump(self.state, f, indent=2)
    
    def load_metrics(self) -> Dict:
        """Load source reliability metrics"""
        if SOURCE_METRICS.exists():
            with open(SOURCE_METRICS) as f:
                return json.load(f)
        
        return {
            'hyperliquid': {
                'total_requests': 0,
                'total_failures': 0,
                'avg_latency_ms': 0,
                'signals_generated': 0,
                'signals_rejected': 0,
                'rejection_reasons': {}
            },
            'polymarket': {
                'total_requests': 0,
                'total_failures': 0,
                'avg_latency_ms': 0,
                'signals_generated': 0,
                'signals_rejected': 0,
                'rejection_reasons': {}
            }
        }
    
    def save_metrics(self):
        """Save metrics"""
        with open(SOURCE_METRICS, 'w') as f:
            json.dump(self.metrics, f, indent=2)
    
    def log_rejected_signal(self, source: str, signal: Dict, reason: str, validations: List[ValidationResult]):
        """Log rejected signal with full details"""
        rejection = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'source': source,
            'signal': signal,
            'reason': reason,
            'validations': [asdict(v) for v in validations]
        }
        
        with open(REJECTED_SIGNALS, 'a') as f:
            f.write(json.dumps(rejection) + '\n')
        
        # Update metrics
        if source in self.metrics:
            self.metrics[source]['signals_rejected'] += 1
            
            if reason not in self.metrics[source]['rejection_reasons']:
                self.metrics[source]['rejection_reasons'][reason] = 0
            self.metrics[source]['rejection_reasons'][reason] += 1
    
    # === SOURCE HEALTH MONITORING ===
    
    def check_source_health(self, source: str, url: str) -> Tuple[bool, float, Optional[str]]:
        """Check if data source is responsive"""
        try:
            start = time.time()
            
            if source == 'hyperliquid':
                resp = requests.post(
                    url,
                    json={'type': 'metaAndAssetCtxs'},
                    timeout=5
                )
                resp.raise_for_status()
                data = resp.json()
                
                # Validate response structure
                if not isinstance(data, list) or len(data) < 2:
                    raise ValueError("Invalid response structure")
                
                if not data[0].get('universe'):
                    raise ValueError("Missing universe data")
            
            elif source == 'polymarket':
                resp = requests.get(
                    url,
                    params={'limit': 5, 'closed': 'false'},
                    timeout=5
                )
                resp.raise_for_status()
                data = resp.json()
                
                if not isinstance(data, list):
                    raise ValueError("Invalid response structure")
            
            latency_ms = (time.time() - start) * 1000
            
            # Update metrics
            self.metrics[source]['total_requests'] += 1
            self.metrics[source]['avg_latency_ms'] = (
                (self.metrics[source]['avg_latency_ms'] * (self.metrics[source]['total_requests'] - 1) + latency_ms) /
                self.metrics[source]['total_requests']
            )
            
            # Update state
            self.state['sources'][source]['last_success'] = datetime.now(timezone.utc).isoformat()
            self.state['sources'][source]['consecutive_failures'] = 0
            self.state['sources'][source]['health'] = 'UP'
            
            return True, latency_ms, None
        
        except Exception as e:
            error = str(e)
            
            # Update metrics
            self.metrics[source]['total_requests'] += 1
            self.metrics[source]['total_failures'] += 1
            
            # Update state
            self.state['sources'][source]['last_failure'] = datetime.now(timezone.utc).isoformat()
            self.state['sources'][source]['consecutive_failures'] += 1
            
            if self.state['sources'][source]['consecutive_failures'] >= DATA_QUALITY['max_fetch_failures']:
                self.state['sources'][source]['health'] = 'DOWN'
            else:
                self.state['sources'][source]['health'] = 'DEGRADED'
            
            return False, 0, error
    
    # === DATA VALIDATION ===
    
    def validate_timestamp_freshness(self, data_timestamp: str) -> ValidationResult:
        """Ensure data is fresh"""
        try:
            data_time = datetime.fromisoformat(data_timestamp.replace('Z', '+00:00'))
            age_seconds = (datetime.now(timezone.utc) - data_time).total_seconds()
            
            passed = age_seconds <= DATA_QUALITY['max_data_age_seconds']
            
            return ValidationResult(
                passed=passed,
                check_name="timestamp_freshness",
                reason=f"Data age: {age_seconds:.0f}s (max: {DATA_QUALITY['max_data_age_seconds']}s)",
                severity="CRITICAL" if not passed else "INFO",
                data={'age_seconds': age_seconds}
            )
        except Exception as e:
            return ValidationResult(
                passed=False,
                check_name="timestamp_freshness",
                reason=f"Invalid timestamp: {e}",
                severity="CRITICAL",
                data={'error': str(e)}
            )
    
    def validate_required_fields(self, data: Dict, data_type: str) -> ValidationResult:
        """Ensure all required fields are present"""
        required = DATA_QUALITY['required_fields'].get(data_type, [])
        missing = [field for field in required if field not in data or data[field] is None]
        
        passed = len(missing) == 0
        
        return ValidationResult(
            passed=passed,
            check_name="required_fields",
            reason=f"Missing fields: {missing}" if missing else "All fields present",
            severity="CRITICAL" if not passed else "INFO",
            data={'missing': missing}
        )
    
    def validate_price_outlier(self, asset: str, current_price: float, historical_prices: Dict) -> ValidationResult:
        """Detect price outliers"""
        if asset not in historical_prices or not historical_prices[asset]:
            # No history yet, allow
            return ValidationResult(
                passed=True,
                check_name="price_outlier",
                reason="No historical data (first fetch)",
                severity="INFO"
            )
        
        last_price = historical_prices[asset][-1]
        change_pct = abs((current_price - last_price) / last_price) * 100
        
        passed = change_pct <= DATA_QUALITY['max_price_change_pct']
        
        return ValidationResult(
            passed=passed,
            check_name="price_outlier",
            reason=f"Price change: {change_pct:.1f}% (max: {DATA_QUALITY['max_price_change_pct']}%)",
            severity="WARNING" if not passed else "INFO",
            data={'change_pct': change_pct, 'last_price': last_price, 'current_price': current_price}
        )
    
    def validate_volume(self, volume: float) -> ValidationResult:
        """Ensure sufficient volume for validity"""
        passed = volume >= DATA_QUALITY['min_volume_usd']
        
        return ValidationResult(
            passed=passed,
            check_name="volume",
            reason=f"Volume: ${volume:,.0f} (min: ${DATA_QUALITY['min_volume_usd']:,})",
            severity="WARNING" if not passed else "INFO",
            data={'volume': volume}
        )
    
    def validate_spread(self, bid: float, ask: float) -> ValidationResult:
        """Validate bid-ask spread for data quality"""
        spread_pct = ((ask - bid) / bid) * 100 if bid > 0 else 100
        
        passed = spread_pct <= DATA_QUALITY['max_spread_pct']
        
        return ValidationResult(
            passed=passed,
            check_name="spread",
            reason=f"Spread: {spread_pct:.2f}% (max: {DATA_QUALITY['max_spread_pct']}%)",
            severity="WARNING" if not passed else "INFO",
            data={'spread_pct': spread_pct}
        )
    
    def validate_funding_stability(self, asset: str, current_funding: float, 
                                   historical_funding: Dict) -> ValidationResult:
        """Check funding rate stability"""
        if asset not in historical_funding or len(historical_funding[asset]) < 3:
            return ValidationResult(
                passed=True,
                check_name="funding_stability",
                reason="Insufficient history for stability check",
                severity="INFO"
            )
        
        recent = historical_funding[asset][-3:]
        avg = sum(recent) / len(recent)
        volatility = max(abs(f - avg) for f in recent)
        
        # High volatility = unstable funding
        unstable = volatility > abs(avg) * 0.5  # 50% deviation
        
        return ValidationResult(
            passed=not unstable,
            check_name="funding_stability",
            reason=f"Funding volatility: {volatility:.4f} (avg: {avg:.4f})",
            severity="WARNING" if unstable else "INFO",
            data={'volatility': volatility, 'avg': avg, 'recent': recent}
        )
    
    def validate_no_duplicates(self, signal: Dict, recent_signals: List[Dict]) -> ValidationResult:
        """Detect duplicate signals"""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
        
        duplicates = []
        for s in recent_signals:
            sig_time = datetime.fromisoformat(s['timestamp'].replace('Z', '+00:00'))
            
            if sig_time > cutoff:
                if (s['asset'] == signal.get('asset') and
                    s['signal_type'] == signal.get('signal_type') and
                    abs(s['entry_price'] - signal.get('entry_price', 0)) < signal.get('entry_price', 1) * 0.01):
                    duplicates.append(s)
        
        passed = len(duplicates) == 0
        
        return ValidationResult(
            passed=passed,
            check_name="no_duplicates",
            reason=f"Found {len(duplicates)} duplicate signals" if duplicates else "No duplicates",
            severity="WARNING" if not passed else "INFO",
            data={'duplicates': len(duplicates)}
        )
    
    def apply_signal_decay(self, signal: Dict) -> Tuple[float, bool]:
        """Apply time-based decay to signal score"""
        try:
            signal_time = datetime.fromisoformat(signal['timestamp'].replace('Z', '+00:00'))
            age_hours = (datetime.now(timezone.utc) - signal_time).total_seconds() / 3600
            
            if age_hours > DATA_QUALITY['signal_decay_hours']:
                return 0, False  # Signal expired
            
            # Linear decay over signal lifetime
            decay_factor = 1.0 - (age_hours / DATA_QUALITY['signal_decay_hours'])
            original_score = signal.get('ev_score', 0)
            decayed_score = original_score * decay_factor
            
            return decayed_score, True
        
        except Exception:
            return 0, False
    
    # === ORCHESTRATION ===
    
    def validate_hyperliquid_data(self, raw_data: Dict) -> Tuple[bool, List[ValidationResult]]:
        """Validate Hyperliquid data quality"""
        validations = []
        
        # Check required fields
        validations.append(self.validate_required_fields(raw_data, 'funding'))
        
        # Check volume
        if 'prevDayNtlVlm' in raw_data:
            validations.append(self.validate_volume(float(raw_data['prevDayNtlVlm'])))
        
        # Check funding stability (if we have history)
        historical_funding = self.state.get('last_validated_data', {}).get('funding', {})
        if 'funding' in raw_data and 'coin' in raw_data:
            validations.append(self.validate_funding_stability(
                raw_data['coin'],
                float(raw_data['funding']),
                historical_funding
            ))
        
        # All critical checks must pass
        critical_failures = [v for v in validations if v.severity == "CRITICAL" and not v.passed]
        
        return len(critical_failures) == 0, validations
    
    def validate_polymarket_data(self, raw_data: Dict) -> Tuple[bool, List[ValidationResult]]:
        """Validate Polymarket data quality"""
        validations = []
        
        # Check required fields
        validations.append(self.validate_required_fields(raw_data, 'market'))
        
        # Check token prices if available
        if 'tokens' in raw_data and isinstance(raw_data['tokens'], list):
            for token in raw_data['tokens']:
                if 'price' in token:
                    # Validate price is reasonable (0-1 for prediction markets)
                    price = float(token['price'])
                    valid_range = 0 <= price <= 1
                    
                    validations.append(ValidationResult(
                        passed=valid_range,
                        check_name="price_range",
                        reason=f"Price {price} {'valid' if valid_range else 'invalid'} (must be 0-1)",
                        severity="CRITICAL" if not valid_range else "INFO",
                        data={'price': price}
                    ))
        
        critical_failures = [v for v in validations if v.severity == "CRITICAL" and not v.passed]
        
        return len(critical_failures) == 0, validations
    
    def validate_signal(self, signal: Dict, source: str) -> Tuple[bool, List[ValidationResult]]:
        """Validate a generated signal before it can influence decisions"""
        validations = []
        
        # Required fields
        validations.append(self.validate_required_fields(signal, 'signal'))
        
        # Timestamp freshness
        if 'timestamp' in signal:
            validations.append(self.validate_timestamp_freshness(signal['timestamp']))
        
        # Duplicate detection
        recent_signals = self.state.get('recent_signals', [])
        validations.append(self.validate_no_duplicates(signal, recent_signals))
        
        # Signal decay
        decayed_score, still_valid = self.apply_signal_decay(signal)
        
        if not still_valid:
            validations.append(ValidationResult(
                passed=False,
                check_name="signal_decay",
                reason=f"Signal expired (age > {DATA_QUALITY['signal_decay_hours']}h)",
                severity="CRITICAL",
                data={'original_score': signal.get('ev_score', 0)}
            ))
        else:
            signal['ev_score_decayed'] = decayed_score
            validations.append(ValidationResult(
                passed=True,
                check_name="signal_decay",
                reason=f"Score decayed: {signal.get('ev_score', 0):.1f} → {decayed_score:.1f}",
                severity="INFO",
                data={'original': signal.get('ev_score', 0), 'decayed': decayed_score}
            ))
        
        # All critical checks must pass
        critical_failures = [v for v in validations if v.severity == "CRITICAL" and not v.passed]
        
        passed = len(critical_failures) == 0
        
        # Log if rejected
        if not passed:
            self.log_rejected_signal(source, signal, "Validation failed", validations)
        else:
            # Update metrics
            self.metrics[source]['signals_generated'] += 1
        
        return passed, validations
    
    def determine_system_health(self) -> DataHealth:
        """Determine overall data health status"""
        
        # Check source health
        sources_down = 0
        sources_degraded = 0
        
        for source, state in self.state['sources'].items():
            if state['health'] == 'DOWN':
                sources_down += 1
            elif state['health'] == 'DEGRADED':
                sources_degraded += 1
        
        # If primary source (Hyperliquid) is down, HALT
        if self.state['sources']['hyperliquid']['health'] == 'DOWN':
            return DataHealth.HALT
        
        # If any source is degraded, DEGRADED
        if sources_degraded > 0 or sources_down > 0:
            return DataHealth.DEGRADED
        
        # Check recent validation failures
        recent_failures = self.state.get('validation_failures', [])
        if len(recent_failures) > 10:
            return DataHealth.DEGRADED
        
        return DataHealth.HEALTHY

    def run_pre_scan_gate(self, include_polymarket: bool = False) -> Dict:
        """
        Enforce the pre-scan data gate for the orchestrator.

        This validates API availability, the freshness of the fetched snapshot, and
        minimum completeness requirements before scanner execution is allowed.
        """
        checks: List[ValidationResult] = []
        reasons: List[str] = []
        now = datetime.now(timezone.utc).isoformat()

        hyperliquid_ok, latency_ms, error = self.check_source_health(
            'hyperliquid',
            'https://api.hyperliquid.xyz/info',
        )
        checks.append(ValidationResult(
            passed=hyperliquid_ok,
            check_name='api_availability',
            reason=(
                f"Hyperliquid reachable in {latency_ms:.0f}ms"
                if hyperliquid_ok else f"Hyperliquid unavailable: {error}"
            ),
            severity='CRITICAL' if not hyperliquid_ok else 'INFO',
            data={'source': 'hyperliquid', 'latency_ms': latency_ms, 'error': error}
        ))

        if hyperliquid_ok:
            try:
                response = requests.post(
                    'https://api.hyperliquid.xyz/info',
                    json={'type': 'metaAndAssetCtxs'},
                    timeout=5
                )
                response.raise_for_status()
                data = response.json()
                universe = data[0].get('universe', []) if isinstance(data, list) and len(data) > 1 else []
                contexts = data[1] if isinstance(data, list) and len(data) > 1 else []

                self.state['sources']['hyperliquid']['last_data_timestamp'] = now
                checks.append(self.validate_timestamp_freshness(now))

                asset_count = min(len(universe), len(contexts))
                asset_count_passed = asset_count >= DATA_QUALITY['min_asset_count']
                checks.append(ValidationResult(
                    passed=asset_count_passed,
                    check_name='data_completeness',
                    reason=(
                        f"Hyperliquid assets: {asset_count} (min: {DATA_QUALITY['min_asset_count']})"
                    ),
                    severity='CRITICAL' if not asset_count_passed else 'INFO',
                    data={'source': 'hyperliquid', 'asset_count': asset_count}
                ))

                sample_failures = 0
                for asset, ctx in zip(universe[:10], contexts[:10]):
                    raw_data = {
                        'coin': asset.get('name'),
                        'funding': ctx.get('funding'),
                        'prevDayNtlVlm': ctx.get('dayNtlVlm', ctx.get('prevDayNtlVlm')),
                        'openInterest': ctx.get('openInterest'),
                    }
                    valid, _ = self.validate_hyperliquid_data(raw_data)
                    if not valid:
                        sample_failures += 1

                sample_passed = sample_failures == 0
                checks.append(ValidationResult(
                    passed=sample_passed,
                    check_name='required_fields',
                    reason=(
                        "Hyperliquid sample data complete"
                        if sample_passed else f"Hyperliquid sample validation failed for {sample_failures} assets"
                    ),
                    severity='CRITICAL' if not sample_passed else 'INFO',
                    data={'source': 'hyperliquid', 'sample_failures': sample_failures}
                ))
            except Exception as exc:
                checks.append(ValidationResult(
                    passed=False,
                    check_name='data_completeness',
                    reason=f"Hyperliquid data validation failed: {exc}",
                    severity='CRITICAL',
                    data={'source': 'hyperliquid', 'error': str(exc)}
                ))

        if include_polymarket:
            polymarket_ok, pm_latency_ms, pm_error = self.check_source_health(
                'polymarket',
                'https://gamma-api.polymarket.com/markets',
            )
            checks.append(ValidationResult(
                passed=polymarket_ok,
                check_name='api_availability',
                reason=(
                    f"Polymarket reachable in {pm_latency_ms:.0f}ms"
                    if polymarket_ok else f"Polymarket unavailable: {pm_error}"
                ),
                severity='WARNING' if not polymarket_ok else 'INFO',
                data={'source': 'polymarket', 'latency_ms': pm_latency_ms, 'error': pm_error}
            ))

        failed_critical = [check for check in checks if check.severity == 'CRITICAL' and not check.passed]
        warning_failures = [check for check in checks if check.severity == 'WARNING' and not check.passed]
        for check in failed_critical:
            reasons.append(f"{check.check_name}: {check.reason}")

        self.state['health'] = self.determine_system_health().value
        self.save_state()
        self.save_metrics()

        if failed_critical:
            self.health_manager.record_incident(
                incident_type='data_integrity_failure',
                severity='CRITICAL',
                source='data-integrity',
                message=" | ".join(reasons),
                affected_system='signal-ingestion',
                affected_components=['data_integrity', 'signal_scanner'],
                metadata={'checks': [asdict(check) for check in failed_critical]},
            )
        elif warning_failures:
            self.health_manager.record_incident(
                incident_type='data_integrity_warning',
                severity='LOW',
                source='data-integrity',
                message=" | ".join(check.reason for check in warning_failures),
                affected_system='signal-ingestion',
                affected_components=['data_integrity'],
                metadata={'checks': [asdict(check) for check in warning_failures]},
            )

        return {
            'passed': len(failed_critical) == 0,
            'health': self.state['health'],
            'reason': " | ".join(reasons) if reasons else "All enforced data-integrity checks passed",
            'checks': [asdict(check) for check in checks],
        }
    
    def generate_health_report(self) -> str:
        """Generate data health report"""
        health = self.determine_system_health()
        
        lines = []
        lines.append("# DATA HEALTH REPORT")
        lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M EDT')}")
        lines.append(f"**System Health:** {health.value}")
        lines.append("")
        
        # Status indicator
        if health == DataHealth.HEALTHY:
            lines.append("🟢 **HEALTHY** — All data sources operational, data quality verified")
        elif health == DataHealth.DEGRADED:
            lines.append("🟡 **DEGRADED** — Data quality issues detected, fallback active")
        else:
            lines.append("🔴 **HALT** — Critical data issues, signal generation halted")
        
        lines.append("")
        lines.append("---")
        lines.append("")
        
        # Source status
        lines.append("## Data Sources")
        lines.append("")
        
        for source_name, source_state in self.state['sources'].items():
            metrics = self.metrics.get(source_name, {})
            
            if source_state['health'] == 'UP':
                icon = "🟢"
            elif source_state['health'] == 'DEGRADED':
                icon = "🟡"
            elif source_state['health'] == 'DOWN':
                icon = "🔴"
            else:
                icon = "⚪"
            
            lines.append(f"### {icon} {source_name.title()}")
            lines.append(f"**Status:** {source_state['health']}")
            lines.append(f"**Last Success:** {source_state['last_success'] or 'Never'}")
            lines.append(f"**Last Failure:** {source_state['last_failure'] or 'Never'}")
            lines.append(f"**Consecutive Failures:** {source_state['consecutive_failures']}")
            
            if metrics.get('total_requests', 0) > 0:
                success_rate = ((metrics['total_requests'] - metrics['total_failures']) / 
                               metrics['total_requests']) * 100
                lines.append(f"**Success Rate:** {success_rate:.1f}%")
                lines.append(f"**Avg Latency:** {metrics['avg_latency_ms']:.0f}ms")
            
            lines.append(f"**Signals Generated:** {metrics.get('signals_generated', 0)}")
            lines.append(f"**Signals Rejected:** {metrics.get('signals_rejected', 0)}")
            
            if metrics.get('rejection_reasons'):
                lines.append("")
                lines.append("**Rejection Reasons:**")
                for reason, count in sorted(metrics['rejection_reasons'].items(), 
                                           key=lambda x: x[1], reverse=True):
                    lines.append(f"- {reason}: {count}")
            
            lines.append("")
        
        lines.append("---")
        lines.append("")
        
        # Data quality metrics
        lines.append("## Data Quality Metrics")
        lines.append("")
        lines.append(f"- **Max Data Age:** {DATA_QUALITY['max_data_age_seconds']}s")
        lines.append(f"- **Max Fetch Failures:** {DATA_QUALITY['max_fetch_failures']}")
        lines.append(f"- **Signal Decay Time:** {DATA_QUALITY['signal_decay_hours']}h")
        lines.append(f"- **Min Volume:** ${DATA_QUALITY['min_volume_usd']:,}")
        lines.append(f"- **Max Spread:** {DATA_QUALITY['max_spread_pct']}%")
        lines.append("")
        
        return "\n".join(lines)


def main():
    print("=" * 80)
    print("DATA INTEGRITY & SIGNAL RELIABILITY LAYER")
    print(f"Check Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S EDT')}")
    print("=" * 80)
    print()
    
    integrity = DataIntegrityLayer()
    
    # Check source health
    print("Checking data sources...")
    
    hl_ok, hl_latency, hl_error = integrity.check_source_health(
        'hyperliquid',
        'https://api.hyperliquid.xyz/info'
    )
    
    if hl_ok:
        print(f"  Hyperliquid: ✅ UP ({hl_latency:.0f}ms)")
    else:
        print(f"  Hyperliquid: ❌ {hl_error}")
    
    pm_ok, pm_latency, pm_error = integrity.check_source_health(
        'polymarket',
        'https://gamma-api.polymarket.com/markets'
    )
    
    if pm_ok:
        print(f"  Polymarket: ✅ UP ({pm_latency:.0f}ms)")
    else:
        print(f"  Polymarket: ❌ {pm_error}")
    
    print()
    
    # Determine health
    health = integrity.determine_system_health()
    print(f"System Health: {health.value}")
    print()
    
    # Save state
    integrity.state['health'] = health.value
    integrity.save_state()
    integrity.save_metrics()
    
    # Generate report
    report = integrity.generate_health_report()
    
    with open(DATA_HEALTH_REPORT, 'w') as f:
        f.write(report)
    
    print("=" * 80)
    print(f"✅ Data integrity check complete")
    print(f"📄 Report: {DATA_HEALTH_REPORT}")
    print(f"📊 State: {DATA_STATE}")
    print(f"📈 Metrics: {SOURCE_METRICS}")
    print("=" * 80)


if __name__ == "__main__":
    main()
