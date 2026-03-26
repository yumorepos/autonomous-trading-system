#!/usr/bin/env python3
"""Regression guards for recent execution fixes."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import runtime
from models.trade_schema import normalize_trade_record, validate_trade_record

TMP_WORKSPACE = Path(tempfile.mkdtemp(prefix='permanence-'))
os.environ['OPENCLAW_WORKSPACE'] = str(TMP_WORKSPACE)


def load_script(name: str, relative_path: str):
    script_path = REPO_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, script_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


paper_trader = load_script('phase1_paper_trader', 'scripts/phase1-paper-trader.py')
agency_module = load_script('trading_agency_phase1', 'scripts/trading-agency-phase1.py')
safety_module = load_script('execution_safety_layer', 'scripts/execution-safety-layer.py')


def test_exit_thresholds_refresh_from_adapter() -> None:
    adapter = SimpleNamespace(take_profit_pct=1.5, stop_loss_pct=-1.5, timeout_hours=0.25)

    def stub_adapter(exchange: str):
        return adapter

    def fake_check_exit(position: dict) -> tuple[bool, str | None]:
        assert position['take_profit_pct'] == adapter.take_profit_pct
        assert position['stop_loss_pct'] == adapter.stop_loss_pct
        assert position['timeout_hours'] == adapter.timeout_hours
        return False, None

    original_adapter = getattr(paper_trader, 'get_paper_exchange_adapter')
    original_check = getattr(paper_trader, 'check_exit')
    try:
        setattr(paper_trader, 'get_paper_exchange_adapter', lambda exchange: adapter)
        setattr(paper_trader, 'check_exit', fake_check_exit)
        open_positions = [
            {
                'exchange': 'Hyperliquid',
                'take_profit_pct': 10,
                'stop_loss_pct': -10,
                'timeout_hours': 24,
                'entry_timestamp': datetime.now(timezone.utc).isoformat(),
                'position_size': 1,
                'entry_price': 1,
                'direction': 'LONG',
            }
        ]
        paper_trader.evaluate_exit_trades(open_positions)
    finally:
        setattr(paper_trader, 'get_paper_exchange_adapter', original_adapter)
        setattr(paper_trader, 'check_exit', original_check)


def test_hyperliquid_liquidity_skips_missing_coin() -> None:
    from utils.paper_exchange_adapters import HyperliquidPaperAdapter
    from models.paper_contracts import SIGNAL_CONTRACTS

    class DummyResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

        def raise_for_status(self):
            pass

    payload_with_coin = [None, [{'symbol': 'PROVE', 'coin': 'PROVE', 'dayNtlVlm': 100}]]
    adapter = HyperliquidPaperAdapter(contract=SIGNAL_CONTRACTS['Hyperliquid'])
    requests_module = SimpleNamespace(post=lambda *args, **kwargs: DummyResponse(payload_with_coin))
    assert adapter.fetch_liquidity('PROVE', requests_module) == 100.0

    payload_missing_coin = [None, [{'dayNtlVlm': 50}]]
    requests_module_bad = SimpleNamespace(post=lambda *args, **kwargs: DummyResponse(payload_missing_coin))
    assert adapter.fetch_liquidity('PROVE', requests_module_bad) is None


def test_reporting_accepts_trade_count_only() -> None:
    StageResult = agency_module.StageResult
    StageStatus = agency_module.StageStatus

    stage_results = [
        StageResult(stage='safety_validation', status=StageStatus.SKIPPED.value, reason='no signal', data={}),
        StageResult(stage='trader', status=StageStatus.SKIPPED.value, reason='safety skip', data={'planned_closes': []}),
        StageResult(stage='authoritative_state_update', status=StageStatus.SKIPPED.value, reason='nothing to persist', data={}),
    ]
    summary = agency_module.build_cycle_summary(stage_results, {'trade_count': 10}, [], [])
    perf = summary['performance_summary']
    assert perf.get('trade_count') == 10
    assert perf.get('total_trades', 0) in (0, 10)


def _canonical_closed_trade_example() -> tuple[dict, str]:
    canonical_log = Path('workspace/logs/phase1-paper-trades.jsonl')
    for line in canonical_log.read_text().splitlines():
        if not line.strip():
            continue
        trade = json.loads(line)
        if trade.get('status') == 'CLOSED':
            return trade, line
    raise RuntimeError('No canonical closed trade available; run a paper cycle first')


def test_cooldown_uses_persisted_trade_timestamp() -> None:
    os.environ['OPENCLAW_WORKSPACE'] = tempfile.mkdtemp(prefix='oc_workspace_')
    workspace_path = Path(os.environ['OPENCLAW_WORKSPACE'])
    logs_dir = workspace_path / 'logs'
    logs_dir.mkdir(parents=True, exist_ok=True)
    trades_file = logs_dir / 'phase1-paper-trades.jsonl'

    runtime.LOGS_DIR = logs_dir
    runtime.WORKSPACE_ROOT = workspace_path

    closed_trade, canonical_line = _canonical_closed_trade_example()
    assert validate_trade_record(closed_trade, context='permanence.test')
    trades_file.write_text(canonical_line + '\n')
    normalized = normalize_trade_record(closed_trade)

    if 'OPENCLAW_TRADING_MODE' in os.environ:
        del os.environ['OPENCLAW_TRADING_MODE']

    safety = safety_module.ExecutionSafetyLayer()
    safety.refresh_breaker_state_from_canonical_history()
    refreshed_id = id(safety)
    last_trade = safety.state['circuit_breakers']['last_trade_timestamp']
    assert last_trade is not None
    last_dt = datetime.fromisoformat(last_trade.replace('Z', '+00:00'))
    normalized_dt = datetime.fromisoformat(normalized.get('exit_timestamp').replace('Z', '+00:00'))
    assert abs((last_dt - normalized_dt).total_seconds()) < 1

    proposal = safety_module.TradeProposal(
        exchange='Hyperliquid',
        strategy='funding_arbitrage',
        asset='PROVE',
        direction='LONG',
        entry_price=0.1,
        position_size_usd=1,
        signal_timestamp=datetime.now(timezone.utc).isoformat(),
        allocation_weight=0.01,
    )
    safety.persist_runtime_state('BLOCKED_TRADE', proposal=proposal, summary={'failed_critical_checks': []}, extra=None, persist_reason='test block')
    assert id(safety) == refreshed_id
    assert safety.state['circuit_breakers']['last_trade_timestamp'] == last_trade

def main() -> None:
    test_exit_thresholds_refresh_from_adapter()
    test_hyperliquid_liquidity_skips_missing_coin()
    test_reporting_accepts_trade_count_only()
    test_cooldown_uses_persisted_trade_timestamp()
    print('[OK] permanence regression tests passed')


if __name__ == '__main__':
    main()
