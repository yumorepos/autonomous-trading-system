#!/usr/bin/env bash
set -euo pipefail

run_step() {
  local title="$1"
  shift
  printf '\n[%s]\n' "$title"
  "$@"
}

echo '================================================================================'
echo 'OPENCLAW SAFE VERIFICATION SUITE'
echo 'Paper trading only | CI-safe | No blocking network dependency checks'
echo '================================================================================'

run_step '1/4 bootstrap runtime check' python3 scripts/bootstrap-runtime-check.py
run_step '2/4 compile validation' bash -lc '
  set -euo pipefail
  python3 -m compileall config models utils tests scripts/*.py
'
run_step '3/4 script regression tests' bash -lc '
  set -euo pipefail
  for test_file in \
    tests/bootstrap-runtime-check-test.py \
    tests/data-integrity-mode-gate-test.py \
    tests/paper-mode-schema-test.py \
    tests/trade-schema-contract-test.py \
    tests/execution-safety-schema-test.py \
    tests/paper-contract-centralization-test.py \
    tests/mixed-mode-policy-test.py \
    tests/polymarket-metadata-truth-test.py \
    tests/signal-integrity-canonical-test.py \
    tests/repo-truth-guard-test.py \
    tests/performance-dashboard-canonical-test.py \
    tests/timeout-monitor-polymarket-threshold-test.py
  do
    echo "[TEST] $test_file"
    python3 "$test_file"
  done
'
run_step '4/4 offline isolated lifecycle tests' bash -lc '
  set -euo pipefail
  for test_file in \
    tests/destructive/trading-agency-hyperliquid-test.py \
    tests/destructive/trading-agency-hyperliquid-repeat-cycle-test.py \
    tests/destructive/trading-agency-state-recovery-test.py \
    tests/destructive/trading-agency-negative-path-test.py \
    tests/destructive/trading-agency-polymarket-negative-path-test.py \
    tests/destructive/trading-agency-polymarket-test.py \
    tests/destructive/trading-agency-mixed-test.py \
    tests/destructive/full-lifecycle-integration-test.py \
    tests/destructive/real-exit-integration-test.py \
    tests/destructive/polymarket-paper-flow-test.py \
    tests/destructive/mixed-mode-integration-test.py
  do
    echo "[TEST] $test_file"
    python3 "$test_file"
  done
'

echo
echo '[PASS] Safe verification suite completed successfully'
