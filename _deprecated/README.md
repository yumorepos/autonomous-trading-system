# Deprecated Scripts

Moved here during codebase audit (2026-04-10). These files are not in the
canonical execution path and have no active callers. They are preserved for
reference but should not be used in production.

## Disabled Scripts (sys.exit at top, redirect to trading_engine.py)

| File | Original Purpose |
|------|-----------------|
| `hl_entry.py` | Signal-driven position opening with safety gates |
| `hl_executor.py` | Safe execution module for closing/reducing positions |
| `manual_entry.py` | CEO override manual entry |

## Standalone Scripts (no callers from active code)

| File | Original Purpose |
|------|-----------------|
| `autonomous_validator.py` | One-off validation monitor for 5 consecutive closed trades |
| `ceo_decision_engine.py` | Automated decision-making based on daily_update data |
| `ceo_health_check.py` | System-wide status and anomaly detection dashboard |
| `check_mission.py` | Auto-load and resume monitoring for active missions |
| `continuous_validation.py` | Permanent health monitoring with 5 automated tests |
| `daily_update.py` | Progress report for 30-day capital doubling challenge |
| `edge_monitor.py` | Edge velocity change monitor |
| `execution_router.py` | Routes signals to PM or HL executor (PM not in production) |
| `generate_performance_report.py` | Recruiter-grade performance report generator |
| `hyperliquid-offline-soak.py` | Operator-safe deterministic soak validation |
| `live-monitor.py` | Live position monitor with 10-minute micro-control loop |
| `live-readiness-validator.py` | Future-scope readiness research framework |
| `mission_validator.py` | Mission continuity validator with corruption recovery |
| `monitor_trades.py` | Token-efficient trade monitoring for material events |
| `performance_tracker.py` | Tracks win rate, PnL, expectancy, drawdown |
| `pm_executor.py` | Polymarket executor using CLOB (Polymarket not in production) |
| `position_health.py` | Quick status check dashboard for open positions |
| `pre_trade_packet.py` | Pre-trade decision packet for CANARY_PROTOCOL |
| `pre_trade_validator.py` | Pre-trade validation guard |
| `self_healing_validator.py` | Crash-proof self-healing validation layer |
| `simple_scanner.py` | CEO override scanner bypassing multi-factor engine |
| `system_health_monitor.py` | Continuous 5-minute health monitor with auto-recovery |
| `trade_logger.py` | Comprehensive trade logging and analysis |
| `validate_trade.py` | Strict 5-source trade validation |

## Support Scripts (no callers)

| File | Original Purpose |
|------|-----------------|
| `support/alpha-intelligence-layer.py` | Dynamic signal reweighting based on strategy performance |
| `support/enhanced-exit-capture.py` | 5-step exit verification proof workflow |
| `support/exit-safeguards.py` | Force-close after max hold time, API failure handling |
| `support/portfolio-allocator.py` | Dynamic paper-trading position sizing and portfolio weight |
| `support/position-exit-tracker.py` | Rankings of positions by proximity to exit conditions |
| `support/stability-monitor.py` | 24-hour observability for crashes, cron health, API failures |
| `support/supervisor-governance.py` | Three-stage governance supervisor (VALIDATE/QUARANTINE/PROMOTE) |

## Previously Archived

| File | Original Purpose |
|------|-----------------|
| `archive/phase1-paper-trader-fixed-legacy.py` | Legacy paper trader |
| `archive/system-audit.py` | One-off system audit |
| `archive/test-full-lifecycle-simulation.py` | Legacy lifecycle test |
| `archive/test-paper-trader-fixes-legacy.py` | Legacy paper trader test |
| `archive/unified-paper-trader.py` | Legacy unified paper trader |

## Restoring a Script

If you need to restore any of these scripts to active use:

```bash
git mv _deprecated/script_name.py scripts/script_name.py
```
