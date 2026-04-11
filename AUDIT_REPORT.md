# Codebase Audit Report

**Date:** 2026-04-10  
**Auditor:** Claude Opus 4.6  
**Scope:** Full codebase audit and cleanup

---

## Summary

| Metric | Before | After |
|--------|--------|-------|
| Python files in scripts/ | 75 | 41 |
| Python files deprecated | 0 | 34 |
| Active .md files (root + docs/) | 67+ | 39 |
| .md files archived | ~20 | 26 |
| Pre-commit test failures | 0 | 0 |
| Hardcoded wallet addresses | 7 files | 0 files |
| Bare except: blocks | 2 | 0 |
| Core files using logging | 0 | 4 |

---

## Phase 1: Discovery

Mapped every Python file to its role in the execution path:

**Core Production (Docker, runs on VPS):**
- `trading_engine.py` - Main control loop (Docker CMD)
- `risk-guardian.py` - Autonomous position protection
- `watchdog.py` - 30-second health monitor
- `emergency_fallback.py` - Last-resort capital protection
- `idempotent_exit.py` - Exit coordination with partial-fill handling
- `exit_ownership.py` - Prevents duplicate closes
- `pre_trade_validator.py` - Pre-trade safety gates
- `self_healing_validator.py` - Auto-recovery from bad state
- `trade_logger.py` - Trade logging for risk guardian

**Signal Generation:**
- `tiered_scanner.py` - Tier 1/2/3 signal classification
- `signal_engine.py` - Multi-factor composite scoring
- `ats-cycle.py` - Entry scan + protection orchestrator
- `hl_entry.py` - Signal-driven entry (disabled, but dynamically loaded by ats-cycle)
- `pre_trade_packet.py` - Pre-trade decision packet (loaded by hl_entry)

**Paper Trading Pipeline:**
- `trading-agency-phase1.py` - Paper trading orchestrator
- `phase1-signal-scanner.py` / `phase1-paper-trader.py`
- `data-integrity-layer.py` / `execution-safety-layer.py`
- `bootstrap-runtime-check.py` / `runtime-connectivity-check.py`
- `timeout-monitor.py` / `exit-monitor.py`
- `daily-review.py` - Daily position review

**Backtester:**
- `backtest/engine.py`, `cost_model.py`, `report.py`, `sweep.py`, `validate_edge.py`
- `backtest/strategies/funding_arb.py`, `mean_reversion.py`
- `backtest/download_history.py`, `diagnose_funding_arb.py`
- `data/download_hl_history.py`

**Analytics:**
- `edge_analytics.py` - Evidence-based strategy evaluation
- `trade_ledger.py` - Append-only trade log
- `trade_diagnosis.py` - Post-trade failure analysis
- `support/performance-dashboard.py` - CLI dashboard

**Config / Models / Utils:** 17 files (all active, no dead code)

---

## Phase 2: Dead Code Cleanup

Moved **34 scripts** to `_deprecated/` (+ 1 backup file):

| Category | Count | Examples |
|----------|-------|---------|
| Disabled (sys.exit at top) | 2 | hl_executor.py, manual_entry.py |
| Standalone, no callers | 21 | autonomous_validator, ceo_decision_engine, daily_update, position_health, pm_executor, simple_scanner, validate_trade... |
| Support scripts, no callers | 7 | alpha-intelligence-layer, portfolio-allocator, supervisor-governance... |
| Previously archived | 5 | Legacy paper traders, system audit |

Each file documented in `_deprecated/README.md` with original purpose.

**Kept but flagged:** 5 scripts have active imports from production code despite appearing standalone (pre_trade_validator, self_healing_validator, trade_logger, hl_entry, pre_trade_packet).

---

## Phase 3: Code Quality

### Logging (print -> logger)
Converted 99 print() statements to Python logging across 4 core files:
- `trading_engine.py` (48 prints)
- `risk-guardian.py` (18 prints)
- `watchdog.py` (7 prints)
- `emergency_fallback.py` (26 prints)

All use `_StdoutHandler` that writes to current `sys.stdout` so existing tests using `redirect_stdout` continue to work.

`status_check()` in trading_engine.py kept as print() for CLI compatibility.

### Bare except blocks
Fixed 2 bare `except:` blocks in `self_healing_validator.py`:
- Line 190: `except:` -> `except (ValueError, TypeError):`
- Line 304: `except:` -> `except Exception:`

### Not changed (by design)
- No trading logic or strategy parameters modified
- No type hints added to files not otherwise changed
- Print statements in non-core files left as-is (CLI tools)

---

## Phase 4: Documentation Reality Check

### Status headers added to 28 documents:
- **ACCURATE** (11 files): EDGE_VALIDATION_REPORT, EXECUTION_PROOF_PROTOCOL, SYSTEM_STATUS, and 8 docs/ files
- **ASPIRATIONAL** (17 files): CEO_*, CAPITAL_PROTECTION_RULES, SCALING_AND_MONETIZATION, STATUS, etc.

### Moved to docs/archive/ (6 files):
- PROOF_MATRIX.md (minimal placeholder)
- SYSTEM_STRUCTURE.md (outdated March 26 snapshot)
- EXIT_TRACKER_REPORT.md, POSITION_TRACKING_REPORT.md, TIMEOUT_MONITOR_REPORT.md (historical examples)
- STABILITY_REPORT.md (empty support artifact)

### README.md rewritten:
- Old: Paper-trading-only framing with stale order references and "Version 6.0"
- New: Honest description of live engine on VPS, CONDITIONAL-GO status, Docker deployment, true architecture diagram

### Key documentation flags:
- CEO_MANDATE.md, CEO_OPERATING_SYSTEM.md: Reference $97 capital doubling mission (capital now depleted)
- SCALING_AND_MONETIZATION.md: Assumes successful compounding from $97
- STATUS.md: Dated March 26, not updated since
- EXPANSION_ROADMAP.md: 0/10 trades audited after 14 days

---

## Phase 5: Security

### .gitignore hardened:
Added missing patterns:
- `*.plist` (launchd configs with secrets)
- `*.pyc`
- `data/historical/`
- `.DS_Store`, `.vscode/`, `.idea/`
- `.venv/`, `venv/`, `build/`, `dist/`
- Preserved `.env.example` with `!.env.example`

### Hardcoded secrets removed:
- Wallet address `0x8743...` removed from 2 active files
- Replaced with `os.environ.get("HL_WALLET_ADDRESS", "")`
- 5 additional instances were in deprecated files (now in _deprecated/)
- No API keys, private keys, or passwords found hardcoded anywhere

### Verified clean:
- No .plist files tracked in git
- No .env files tracked (only .env.example)
- No secrets in active codebase

---

## Remaining Risks

1. **Stale documentation:** 17 files marked ASPIRATIONAL still reference $97 capital and missions that failed. Consider bulk-archiving or deleting CEO_* docs.

2. **Test coverage gaps:** Paper trading pipeline tests exist but core engine tests rely on pre-commit hooks only. No pytest framework or CI integration for the live engine path.

3. **Single wallet address:** `HL_WALLET_ADDRESS` env var is now required but not validated at startup. If missing, `pre_trade_validator` and `self_healing_validator` will use empty string.

4. **Polymarket code still in active path:** `phase1-signal-scanner.py`, `phase1-paper-trader.py` and several models still reference Polymarket. Not harmful but adds complexity to a Hyperliquid-only system.

5. **No structured logging format:** Logger uses plain `%(message)s` format. For a Docker/VPS deployment, structured JSON logging would improve observability.

---

## Top 5 Next Actions

1. **Add env var validation at startup** — trading_engine.py should verify `HL_WALLET_ADDRESS` and `HL_PRIVATE_KEY` are set before entering the main loop.

2. **Bulk-archive CEO_* docs** — CEO_MANDATE, CEO_OPERATING_SYSTEM, CEO_DECISION_ENGINE are all tied to the failed $97 doubling mission and add confusion.

3. **Add pytest framework** — Convert pre-commit hook tests to pytest for better CI integration and test discovery.

4. **Implement structured JSON logging** — Replace `%(message)s` format with JSON for Docker log aggregation.

5. **Update STATUS.md** — Currently dated March 26. Should reflect current capital, trade count, and system state as of latest deployment.

---

## Commits Made

1. `refactor: move 35 dead/unused scripts to _deprecated/`
2. `fix: replace print() with proper logging in core engine files`
3. `docs: audit all markdown files, add status headers, rewrite README`
4. `fix: harden .gitignore and remove hardcoded wallet addresses`
