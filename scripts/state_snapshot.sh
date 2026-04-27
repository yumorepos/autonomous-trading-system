#!/usr/bin/env bash
# state_snapshot.sh — single-round-trip read-only snapshot of ATS production state.
# Six labeled sections:
#   1. systemd ats-paper-trader status
#   2. git HEAD (short SHA + subject + author-date)
#   3. /paper/status (paper trader, :8081)
#   4. /health (engine, :8080)
#   5. tail -n 20 execution_log.jsonl
#   6. tail -n 5 paper_trades.jsonl
# Idempotent. No writes. Bash only. Designed to run on the Helsinki VPS at /opt/trading/.

REPO_DIR="/opt/trading"
DATA_DIR="${REPO_DIR}/data"

echo "=== 1. systemd ats-paper-trader ==="
systemctl is-active ats-paper-trader 2>&1 || true
echo

echo "=== 2. git HEAD (${REPO_DIR}) ==="
git -C "${REPO_DIR}" log -1 --format='%h %s %cd' --date=short 2>&1 || true
echo

echo "=== 3. /paper/status (paper trader, :8081) ==="
curl --max-time 5 -sS http://localhost:8081/paper/status 2>&1 || true
echo
echo

echo "=== 4. /health (engine, :8080) ==="
curl --max-time 5 -sS http://localhost:8080/health 2>&1 || true
echo
echo

echo "=== 5. tail -n 20 execution_log.jsonl ==="
tail -n 20 "${DATA_DIR}/execution_log.jsonl" 2>&1 || true
echo

echo "=== 6. tail -n 5 paper_trades.jsonl ==="
tail -n 5 "${DATA_DIR}/paper_trades.jsonl" 2>&1 || true

exit 0
