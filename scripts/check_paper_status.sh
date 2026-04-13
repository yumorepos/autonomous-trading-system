#!/bin/bash
# Quick status check for paper trading pipeline
# Usage: bash scripts/check_paper_status.sh

echo "╔══════════════════════════════════════╗"
echo "║   PAPER TRADING STATUS CHECK         ║"
echo "║   $(date -u '+%Y-%m-%d %H:%M:%S UTC')          ║"
echo "╚══════════════════════════════════════╝"
echo ""

# Process check
PID=$(cat data/paper_trader.pid 2>/dev/null)
if [ -n "$PID" ] && kill -0 $PID 2>/dev/null; then
    UPTIME=$(ps -p $PID -o etime= 2>/dev/null || echo "unknown")
    echo "  Process: RUNNING (PID: $PID, uptime:$UPTIME)"
else
    echo "  Process: NOT RUNNING"
    echo "  Start with: nohup python3 scripts/run_paper_trading.py > data/paper_stdout.log 2>&1 &"
fi

# API check
echo ""
API_HEALTH=$(curl -s --max-time 3 http://localhost:8081/health 2>/dev/null)
if [ -n "$API_HEALTH" ]; then
    echo "  Stats API: RESPONDING on :8081"
else
    echo "  Stats API: NOT RESPONDING"
fi

# Paper trading metrics
echo ""
STATS=$(curl -s --max-time 3 http://localhost:8081/paper/stats 2>/dev/null)
if [ -n "$STATS" ]; then
    echo "  Paper Trading Metrics:"
    echo "$STATS" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(f'    Open positions:    {d.get(\"open_positions\", 0)}')
    print(f'    Closed trades:     {d.get(\"closed_positions\", 0)}')
    print(f'    Total PnL:         \${d.get(\"total_pnl_usd\", 0):.2f}')
    print(f'    Win rate:          {d.get(\"win_rate\", 0):.0%}')
    print(f'    Funding collected: \${d.get(\"total_funding_collected_usd\", 0):.2f}')
    print(f'    Fees paid:         \${d.get(\"total_fees_paid_usd\", 0):.2f}')
except:
    print('    (Could not parse stats response)')
" 2>/dev/null
else
    echo "  Paper Trading Metrics: unavailable"
fi

# Orchestrator status
echo ""
STATUS=$(curl -s --max-time 3 http://localhost:8081/paper/status 2>/dev/null)
if [ -n "$STATUS" ]; then
    echo "  Orchestrator:"
    echo "$STATUS" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    o = d.get('orchestrator', {})
    print(f'    Uptime:            {o.get(\"uptime_seconds\", 0):.0f}s')
    print(f'    Events processed:  {o.get(\"events_processed\", 0)}')
    print(f'    Actionable:        {o.get(\"signals_actionable\", 0)}')
    print(f'    Positions opened:  {o.get(\"positions_opened\", 0)}')
    print(f'    Positions closed:  {o.get(\"positions_closed\", 0)}')
except:
    print('    (Could not parse status response)')
" 2>/dev/null
fi

# Trade log
echo ""
if [ -f data/paper_trades.jsonl ]; then
    TRADE_COUNT=$(wc -l < data/paper_trades.jsonl)
    echo "  Trade log: $TRADE_COUNT entries"
    echo "  Last entry:"
    tail -1 data/paper_trades.jsonl 2>/dev/null | python3 -m json.tool 2>/dev/null || tail -1 data/paper_trades.jsonl
else
    echo "  Trade log: no trades yet"
fi

# ATS engine status
echo ""
if [ -f workspace/logs/trading_engine.jsonl ]; then
    LAST_EVENT=$(tail -1 workspace/logs/trading_engine.jsonl 2>/dev/null)
    LAST_TIME=$(echo "$LAST_EVENT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('timestamp','?'))" 2>/dev/null || echo "?")
    echo "  ATS Engine: last event at $LAST_TIME"
    REGIME_EVENTS=$(grep -c 'regime_updated' workspace/logs/trading_engine.jsonl 2>/dev/null || echo "0")
    echo "  Regime transitions in log: $REGIME_EVENTS"
else
    echo "  ATS Engine: JSONL file not found"
fi

echo ""
echo "  ─────────────────────────────────────"
echo "  Full logs:  tail -50 data/paper_stdout.log"
echo "  Stop:       kill \$(cat data/paper_trader.pid)"
echo "  Restart:    nohup python3 scripts/run_paper_trading.py > data/paper_stdout.log 2>&1 &"
