# Autonomous Trading System

Status: **CONDITIONAL-GO** — live on Hyperliquid mainnet, regime-dependent  
Last audit: 2026-04-10

## What This Is

An autonomous crypto trading engine deployed on Hyperliquid. Runs in a Docker
container on a VPS. The engine monitors positions, enforces stop-losses,
manages circuit breakers, and executes trades based on funding rate arbitrage
signals.

**Current state:**
- Live on Hyperliquid mainnet via Docker (trading_engine.py)
- CONDITIONAL-GO: backtested edge exists but is regime-dependent (active ~1/3 of time)
- Multi-layer capital protection: engine + watchdog + risk guardian + emergency fallback
- 19 pre-commit protection tests must pass before any code change
- Backtester built and validated (180-day window, 23 trades, positive expectancy)

**Limitations:**
- Small capital (~$100 starting)
- Limited live trade history (<20 audited trades)
- Strategy sits out during unfavorable market regimes
- Polymarket integration explored but not in production

## Architecture

```
Docker Container (VPS)
  trading_engine.py          Main control loop (Docker CMD)
    config/risk_params.py    Unified risk parameters
    config/runtime.py        Path/mode configuration
    idempotent_exit.py       Exit coordination with partial-fill handling
    exit_ownership.py        Lock to prevent duplicate closes
    pre_trade_validator.py   Pre-trade safety gates

  watchdog.py                Health monitor (30s cycle)
    risk-guardian.py          Autonomous position protection

  emergency_fallback.py      Last-resort capital protection (independent)
```

Signal generation (run separately or via ats-cycle.py):
- `tiered_scanner.py` — Tier 1/2/3 signal classification by strength
- `signal_engine.py` — Multi-factor composite scoring (funding + momentum + volume)

Paper trading pipeline (secondary, for validation):
- `trading-agency-phase1.py` — Orchestrator for paper trading flow
- `phase1-signal-scanner.py` / `phase1-paper-trader.py` — Paper execution

## Quick Start

### Docker (production)

```bash
cp .env.example .env
# Fill in HL_PRIVATE_KEY and HL_WALLET_ADDRESS
docker-compose up -d
```

### Local development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Status check
python3 scripts/trading_engine.py --status

# Run backtester
python3 -m scripts.backtest.engine
```

### Tests

```bash
# Pre-commit tests (run automatically on commit)
python3 tests/test_capital_protection_rules.py
python3 tests/test_multi_layer_protection.py
python3 tests/test_race_condition.py
python3 tests/test_idempotent_close.py

# Full CI suite
./scripts/ci-safe-verification.sh
```

## Repository Layout

```
config/           Risk parameters and runtime configuration
models/           Trade/position schemas and paper account state
scripts/          Active trading scripts and backtester
  backtest/       Backtesting engine, strategies, cost model
  data/           Historical data downloaders
  support/        Performance dashboard
tests/            Regression and protection tests
utils/            Alerting, API connectivity, JSON helpers
_deprecated/      39 scripts removed during 2026-04-10 audit (see README inside)
docs/             Architecture docs, runbooks, audit history
artifacts/        Backtest reports, case studies
workspace/        Runtime state, logs, operator controls (gitignored)
```

## Key Documents

| Document | Status | Purpose |
|----------|--------|---------|
| EDGE_VALIDATION_REPORT.md | Accurate | Backtested edge analysis, GO/NO-GO verdict |
| EXECUTION_PROOF_PROTOCOL.md | Accurate | Post-mortem on execution truth failures |
| CAPITAL_PROTECTION_RULES.md | Aspirational | Design intent for protection rules |
| docs/SYSTEM_ARCHITECTURE.md | Accurate | Paper trading pipeline architecture |
| docs/RUNBOOK.md | Aspirational | Operations procedures (needs update) |
| docs/OPERATOR_QUICKSTART.md | Accurate | Paper trading quickstart |

## Disclaimer

This is a personal trading system, not a product. It is not financial advice.
Performance claims are based on backtesting and limited live data.
