> **Status: ACCURATE** — verified against current codebase.

# CRITICAL STABILITY FIXES — 2026-04-06

**Context:** Trading engine was blocked for multiple days due to cascading failures. System recovered and made operational on April 6, 2026.

---

## FIXES APPLIED

### 1. LIQUIDITY CHECK FAILURE ❌ → ✅

**Problem:**
- Hyperliquid API returns market data with inconsistent field names
- Code expected `'coin'` field but some markets only have `'symbol'` or `'name'`
- Missing field caused `KeyError` → safety checks failed → all trades blocked

**Fix:**
```python
# Before
coin = market.get('coin') or market.get('symbol')
if coin == asset:

# After  
coin = market.get('coin') or market.get('symbol') or market.get('name')
if not coin:
    continue
if str(coin).upper() == str(asset).upper():
```

**File:** `utils/paper_exchange_adapters.py`

**Validation:**
```bash
python3 scripts/tiered_scanner.py  # Should return signals without liquidity errors
```

---

### 2. STATE CORRUPTION (CONCURRENT WRITES) ❌ → ✅

**Problem:**
- Multiple engine instances running concurrently (launchd `KeepAlive` spawning duplicates)
- Concurrent writes to `trading_engine_state.json` caused JSON corruption
- Corrupted state → engine crash on startup → continuous restart loop

**Fix (Part A — Backwards Compatibility):**
```python
# Load state with default merge (prevents KeyError on new fields)
default = { "heartbeat": None, "peak_roe": {}, ... }
if STATE_FILE.exists():
    loaded = json.loads(STATE_FILE.read_text())
    for key in default:
        if key not in loaded:
            loaded[key] = default[key]
    return loaded
return default
```

**Fix (Part B — PID Lock):**
```python
# Prevent concurrent instances
pid_file = LOGS_DIR / "trading_engine.pid"
if pid_file.exists():
    old_pid = int(pid_file.read_text().strip())
    if process_running(old_pid):
        print("❌ ENGINE ALREADY RUNNING")
        sys.exit(1)

pid_file.write_text(str(os.getpid()))
try:
    engine.run()
finally:
    pid_file.unlink()
```

**File:** `scripts/trading_engine.py`

**Validation:**
```bash
# Start engine twice — second should fail with "ALREADY RUNNING"
python3 scripts/trading_engine.py &
python3 scripts/trading_engine.py  # Should exit immediately
```

---

### 3. POSITION DATA MISSING (EXIT COORDINATOR BUG) ❌ → ✅

**Problem:**
- `HyperliquidClient.get_state()` returned simplified position dict
- Exit coordinator (`idempotent_exit.py`) expected raw `"szi"` field from API
- Missing field → `KeyError` → exits failed → positions unprotected

**Fix:**
```python
# Include raw szi field in position dict
positions.append({
    "coin": p["coin"],
    "size": abs(szi),
    "szi": p.get("szi"),  # ← ADD THIS (raw API field)
    "entry_price": float(p.get("entryPx", 0)),
    ...
})
```

**File:** `scripts/trading_engine.py` (HyperliquidClient.get_state)

**Validation:**
```bash
# With open position, check exit works
python3 -c "
from scripts.trading_engine import HyperliquidClient
client = HyperliquidClient()
positions = client.get_positions()
assert 'szi' in positions[0] if positions else True
"
```

---

### 4. SIZING PRECISION (HYPERLIQUID REJECTION) ❌ → ✅

**Problem:**
- Position size calculated as float: `size_coins = (size_usd * leverage) / price`
- Hyperliquid SDK rejects floats with too many decimals: `"float_to_wire causes rounding"`
- Entry orders rejected → no trades executed

**Fix:**
```python
# Round to 8 decimals (Hyperliquid max precision)
size_coins = (size_usd * leverage) / price
size_coins = round(size_coins, 8)  # ← ADD THIS
response = self.client.exchange.market_open(coin, True, size_coins)
```

**File:** `scripts/trading_engine.py` (execute_entry)

**Validation:**
```bash
# Check recent entries have no rounding errors
grep "entry_executed" workspace/logs/trading_engine.jsonl | tail -5
# Should NOT see "float_to_wire" errors
```

---

### 5. LAUNCHD SERVICE (PERSISTENT OPERATION) ❌ → ✅

**Problem:**
- Engine not running as persistent daemon
- Manual `nohup python3 ...` crashed without restart
- No environment variable loading (HL_PRIVATE_KEY missing)

**Fix:**
Created `~/Library/LaunchAgents/com.ats.trading-engine.plist`:

```xml
<key>KeepAlive</key>
<dict>
    <key>SuccessfulExit</key>
    <false/>  <!-- Restart on unexpected exit -->
    <key>Crashed</key>
    <true/>   <!-- Restart on crash -->
</dict>

<key>EnvironmentVariables</key>
<dict>
    <key>HL_PRIVATE_KEY</key>
    <string>0x...</string>  <!-- Loaded from secure location -->
</dict>
```

**⚠️ SECURITY NOTE:** Launchd plist contains secrets. **NEVER commit to git.**

**File (LOCAL ONLY):** `~/Library/LaunchAgents/com.ats.trading-engine.plist`

**Validation:**
```bash
launchctl list | grep com.ats.trading-engine  # Should show PID
ps aux | grep "[p]ython3.*trading_engine"     # Should show running process
```

**Start/Stop:**
```bash
launchctl load ~/Library/LaunchAgents/com.ats.trading-engine.plist
launchctl unload ~/Library/LaunchAgents/com.ats.trading-engine.plist
```

---

## VERIFICATION CHECKLIST

**Before claiming operational:**

- [ ] Engine PID exists: `launchctl list | grep com.ats.trading-engine`
- [ ] Heartbeat fresh: `python3 scripts/trading_engine.py --status` shows ✅ FRESH
- [ ] No duplicate instances: `ps aux | grep trading_engine | wc -l` returns 1
- [ ] PID lock file present: `ls workspace/logs/trading_engine.pid`
- [ ] Scanner runs without errors: `python3 scripts/tiered_scanner.py`
- [ ] Entry execution works: Check `workspace/logs/trading_engine.jsonl` for `entry_executed` events
- [ ] Exit execution works: Open position hits SL/TP and closes cleanly
- [ ] State file valid JSON: `python3 -c "import json; json.load(open('workspace/logs/trading_engine_state.json'))"`

---

## WHAT REMAINS LOCAL-ONLY (SECURITY)

**NEVER sync these to remote git:**

1. **Launchd plist** — Contains HL_PRIVATE_KEY
   - File: `~/Library/LaunchAgents/com.ats.trading-engine.plist`
   - Regenerate manually on new machines

2. **Environment files** — API keys, wallet private keys
   - Covered by `.gitignore`: `.env`, `.env.*`, `*.key`, `*.secret`

3. **Runtime logs** — May contain wallet addresses, trade details
   - Covered by `.gitignore`: `*.jsonl`, `*.log`, `workspace/logs/`

4. **State files** — Contain position tracking, capital info
   - Covered by `.gitignore`: `*.state.json`, `circuit-breaker-state.json`

---

## PERMANENT SAFEGUARDS ADDED

### Git Pre-Commit Hook (TODO)
Scan staged files for secrets before allowing commit:

```bash
#!/bin/bash
# .git/hooks/pre-commit
if git diff --cached | grep -E "HL_PRIVATE_KEY|0x[a-fA-F0-9]{64}"; then
    echo "❌ BLOCKED: Secrets detected in staged changes"
    exit 1
fi
```

### Startup Validation Script
Run on boot to verify engine health:

```bash
#!/bin/bash
# ~/Projects/autonomous-trading-system/scripts/startup_validation.sh

# Check launchd service
if ! launchctl list | grep -q com.ats.trading-engine; then
    echo "⚠️ ENGINE NOT LOADED"
    launchctl load ~/Library/LaunchAgents/com.ats.trading-engine.plist
fi

# Check heartbeat
python3 ~/Projects/autonomous-trading-system/scripts/trading_engine.py --status
```

Add to crontab:
```
@reboot sleep 30 && ~/Projects/autonomous-trading-system/scripts/startup_validation.sh
```

### Continuous Monitoring (TODO)
Add heartbeat check every 5 minutes:

```bash
*/5 * * * * python3 ~/Projects/autonomous-trading-system/scripts/trading_engine.py --status | grep -q "FRESH" || echo "🚨 ENGINE DOWN" | mail -s "ATS Alert" your@email.com
```

---

## LESSONS LEARNED

1. **Test in production-like conditions** — Concurrent writes weren't caught in dev
2. **PID locks are mandatory** — Daemon managers can spawn duplicates
3. **API field names are unreliable** — Always handle missing fields gracefully
4. **Precision matters** — Financial APIs have strict decimal requirements
5. **Secrets in environment only** — Never hardcode, never commit

---

## NEXT STEPS

- [x] Commit fixes to git (done: b9928b3)
- [ ] Push to remote (pending repo deep-dive)
- [ ] Add pre-commit hook for secret scanning
- [ ] Document launchd plist regeneration for new machines
- [ ] Add automated uptime monitoring alerts
- [ ] Create runbook for engine restart after crash

---

**Status:** System operational, trading resumed, 1/20 validation trades complete.  
**Last Updated:** 2026-04-06 18:35 UTC
