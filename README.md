# Autonomous Trading System

Funding-rate arbitrage engine running a paper-trading validation window on a VPS.

**Status (verified 2026-04-17):** paper mode, `dry_run=true`. 6 clean closed trades, WR 66.7%, +$51.87 closed PnL, 1 open position. Target is n ≥ 20 clean closes before any live-capital decision.

## What it does

Detects funding-rate arbitrage opportunities on Hyperliquid perpetuals, scores candidates through a composite signal filter (funding rate + cross-exchange premium + liquidity + duration prediction), and opens/closes simulated positions to collect the funding yield. All entry gates and exit rules (trailing stop, timeout, invalidation) are pre-registered in `config/` and must not be hot-patched during a validation window.

## Deployment

| | |
|---|---|
| Host | Hetzner VPS |
| Service | systemd unit `ats-paper-trader` |
| Install path | `/opt/trading/` |
| Entry point | `scripts/run_paper_trading.py` |
| Mode | Paper / `dry_run=true` (no real orders) |
| Stats API | `http://localhost:8081/paper/status`, `/paper/stats` |
| Trade ledger | `/opt/trading/data/paper_trades.jsonl` (never rotated) |
| Engine log | `/opt/trading/workspace/logs/trading_engine.jsonl` |

Operational procedures: [docs/RUNBOOK.md](docs/RUNBOOK.md) and [docs/operations/](docs/operations/).

## Architecture

```text
scripts/run_paper_trading.py         entry point — wires components, serves stats API
│
├── src/bridge/ats_connector.py      consumes regime transitions from ATS engine
├── src/collectors/                  exchange adapters (Binance, Hyperliquid, Bybit)
│     exchange_adapters/, regime_history.py, spread_scanner.py
├── src/scoring/                     composite signal scoring
│     composite_scorer.py, duration_predictor.py, liquidity_scorer.py
├── src/pipeline/
│     signal_filter.py               scores and gates candidates
│     live_orchestrator.py           event → signal → paper-trade loop
├── src/simulator/paper_trader.py    simulated position lifecycle, PnL, funding accrual
├── src/execution/
│     executor.py                    Hyperliquid entry path (gated by dry_run)
│     kill_switch.py                 hard cutoff
├── src/api/stats_server.py          /paper/status, /paper/stats
└── config/
      risk_params.py                 pre-registered risk + exit rules
      config.yaml, regime_thresholds.py
```

## Backtest (canonical figures)

180-day window, 30-asset universe.

**23 trades · WR 82.6% · PF 1.68 · net +$2.44 on $95 · max DD 1.59% · Sharpe 5.64.**
Exit mix: TRAILING_STOP 18, STOP_LOSS 2, TAKE_PROFIT 2, TIMEOUT 1.

- Source of truth: [docs/audits/EDGE_VALIDATION_REPORT.md](docs/audits/EDGE_VALIDATION_REPORT.md) (generated 2026-04-10, reproduced exactly during D36 on 2026-04-17).
- Trade log pinned at `artifacts/backtest_trades_d31.jsonl` — sha256 `2ee4f3725b5ec9cccae1bec499a969ecdc3b702f4de17f334c6548692afe31f4`, 23 lines, 7005 bytes.

Known caveats:
- **Sample concentration:** 20 of 23 trades are on a single asset (VVV).
- **SHORT partition empty:** the 180-day dataset contains zero observations with `rate_8h ≥ +100% APY`, so the strategy's SHORT side is untested against real historical data.
- "PF 2.02" appearing in older docs is a mis-cite of a forward-looking governance target in `docs/THREE_STAGE_GOVERNANCE.md`, not a backtest result.

## Live paper trading window

Snapshot as of 2026-04-17 (for current figures, hit the stats API directly):

| Asset | Dir | Exit | Net PnL |
|---|---|---|---|
| BLUR | long | TRAILING_STOP | +$1.37 |
| BLUR | long | TRAILING_STOP | +$17.44 |
| ALT | long | TRAILING_STOP | +$50.12 |
| YZY | long | TIMEOUT | −$16.87 |
| ZETA | long | TRAILING_STOP | +$44.68 |
| BLUR | long | TIMEOUT | −$44.86 |

**Closed PnL +$51.87 · WR 66.7% · n = 6 · 1 open (SAGA).** At this sample size, expectancy is indistinguishable from noise. The window continues until n ≥ 20 and PF meets pre-registered thresholds.

## Running locally

```bash
cp .env.example .env
# Fill HL_PRIVATE_KEY, HL_WALLET_ADDRESS (read-only is sufficient for paper)

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python3 scripts/run_paper_trading.py
```

Stats will be live at `http://localhost:8081/paper/status`.

## Tests

```bash
./scripts/ci-safe-verification.sh
```

Runs bootstrap runtime check, compile validation, regression tests, and offline lifecycle tests. No network dependencies, no live exchange calls.

## Legacy paths

These exist in the repo but are **not** on the live path. Kept for reference, not for new work:

- `scripts/trading_engine.py`, `watchdog.py`, `risk-guardian.py`, `emergency_fallback.py` — earlier Hyperliquid mainnet attempt. Superseded by `scripts/run_paper_trading.py` + `src/`.
- `scripts/phase1-paper-trader.py`, `scripts/phase1-signal-scanner.py` — paper trader v1. Superseded by `src/simulator/paper_trader.py`.
- `Dockerfile`, `docker-compose.yml` — retained for local containerized dev. The VPS does not use Docker.
- `docs/POLYMARKET_*.md` — Polymarket support was removed (D32) and is not on any live path.

## Key docs

| File | Purpose |
|---|---|
| [docs/audits/EDGE_VALIDATION_REPORT.md](docs/audits/EDGE_VALIDATION_REPORT.md) | Canonical backtest headline |
| [docs/SYSTEM_ARCHITECTURE.md](docs/SYSTEM_ARCHITECTURE.md) | Pipeline architecture |
| [docs/OPERATOR_QUICKSTART.md](docs/OPERATOR_QUICKSTART.md) | Paper-trading quickstart |
| [docs/RUNBOOK.md](docs/RUNBOOK.md) | Operational procedures |
| [docs/THREE_STAGE_GOVERNANCE.md](docs/THREE_STAGE_GOVERNANCE.md) | Go/no-go framework (contains aspirational PF target — not a backtest result) |

## Disclaimer

Personal research project. Not financial advice. Backtest claims are based on a 180-day window with acknowledged sample-concentration caveats. The live paper-trading window is small and statistically inconclusive. No real capital is deployed.
