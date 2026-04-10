> **Status: ASPIRATIONAL** — describes design intent or goals, not verified current state.

# AUTONOMOUS TRADING SYSTEM — OPERATIONS RUNBOOK

**Purpose:** Standard procedures for starting, stopping, monitoring, and troubleshooting the trading engine.

---

## QUICK STATUS CHECK

```bash
cd ~/Projects/autonomous-trading-system
python3 scripts/trading_engine.py --status
```

**Expected output:**
```
Heartbeat: ✅ FRESH (0.3s ago)
Circuit breaker: ✅ ACTIVE
Open positions: X
✅ CAPITAL PROTECTION: ACTIVE
```

---

## STARTING THE ENGINE

### Method 1: Launchd (Recommended — Persistent)

```bash
# Load service
launchctl load ~/Library/LaunchAgents/com.ats.trading-engine.plist

# Verify running
launchctl list | grep com.ats.trading-engine
# Should show: PID  0  com.ats.trading-engine
```

### Method 2: Manual (Testing Only)

```bash
cd ~/Projects/autonomous-trading-system
python3 scripts/trading_engine.py
```

**⚠️ WARNING:** Manual start will exit when terminal closes. Use launchd for production.

---

## STOPPING THE ENGINE

### Graceful Stop (Recommended)

```bash
# Unload service
launchctl unload ~/Library/LaunchAgents/com.ats.trading-engine.plist

# Verify stopped
ps aux | grep "[p]ython3.*trading_engine"  # Should return nothing
```

### Force Kill (Emergency Only)

```bash
# Find PID
ps aux | grep "[p]ython3.*trading_engine" | awk '{print $2}'

# Kill process
kill <PID>

# Clean up lock file
rm -f ~/Projects/autonomous-trading-system/workspace/logs/trading_engine.pid
```

---

## RESTARTING THE ENGINE

```bash
launchctl unload ~/Library/LaunchAgents/com.ats.trading-engine.plist
sleep 2
launchctl load ~/Library/LaunchAgents/com.ats.trading-engine.plist

# Verify
python3 ~/Projects/autonomous-trading-system/scripts/trading_engine.py --status
```

---

## MONITORING

### Real-Time Logs

```bash
# Engine events
tail -f ~/Projects/autonomous-trading-system/workspace/logs/trading_engine.jsonl

# Launchd stdout
tail -f ~/Projects/autonomous-trading-system/workspace/logs/engine-stdout.log

# Launchd stderr
tail -f ~/Projects/autonomous-trading-system/workspace/logs/engine-stderr.log
```

### Recent Trades

```bash
cd ~/Projects/autonomous-trading-system

# Last 10 entries
grep "entry_executed" workspace/logs/trading_engine.jsonl | tail -10

# Last 10 exits
grep "action.*exit" workspace/logs/trading_engine.jsonl | tail -10
```

### Current Positions

```bash
cd ~/Projects/autonomous-trading-system
python3 scripts/position_health.py
```

---

## TROUBLESHOOTING

### Engine Not Starting

**Symptom:** `launchctl list` shows exit code 1 or no PID

**Debug:**
```bash
# Check stderr for errors
tail -50 ~/Projects/autonomous-trading-system/workspace/logs/engine-stderr.log

# Common causes:
# 1. Missing HL_PRIVATE_KEY → Check launchd plist EnvironmentVariables
# 2. PID lock exists → rm workspace/logs/trading_engine.pid
# 3. Corrupt state file → rm workspace/logs/trading_engine_state.json (will reset)
```

---

### Heartbeat Stale

**Symptom:** `--status` shows "⚠️ STALE (XXs ago)"

**Cause:** Engine crashed or stuck

**Fix:**
```bash
# Restart engine
launchctl unload ~/Library/LaunchAgents/com.ats.trading-engine.plist
sleep 2
launchctl load ~/Library/LaunchAgents/com.ats.trading-engine.plist
```

---

### No Trades Executing

**Debug checklist:**

1. **System healthy?**
   ```bash
   python3 scripts/trading_engine.py --status
   # Check circuit breaker: should be ✅ ACTIVE (not HALTED)
   ```

2. **Signals available?**
   ```bash
   python3 scripts/tiered_scanner.py
   # Should show Tier 1 or Tier 2 signals
   ```

3. **Already holding signal?**
   ```bash
   python3 scripts/position_health.py
   # If coin already open, engine won't re-enter
   ```

4. **Entry logs?**
   ```bash
   grep -E "entry_executed|entry_failed|entry_blocked" workspace/logs/trading_engine.jsonl | tail -10
   # Check for blocking reasons
   ```

---

### Positions Not Closing

**Symptom:** Position stuck open beyond timeout

**Debug:**
```bash
# Check exit attempts
grep "coin.*COINNAME" workspace/logs/trading_engine.jsonl | grep -E "exit|STOP_LOSS|TAKE_PROFIT"

# Check circuit breaker status
python3 scripts/trading_engine.py --status
```

**Force Close (Manual Override):**
```bash
cd ~/Projects/autonomous-trading-system

# Close specific coin
python3 -c "
from scripts.trading_engine import HyperliquidClient
client = HyperliquidClient()
response = client.market_close('COINNAME')
print(response)
"
```

---

### Duplicate Instances Running

**Symptom:** Multiple PIDs for trading_engine

**Fix:**
```bash
# Kill all instances
pkill -f "python3.*trading_engine"

# Remove lock file
rm -f ~/Projects/autonomous-trading-system/workspace/logs/trading_engine.pid

# Restart cleanly
launchctl load ~/Library/LaunchAgents/com.ats.trading-engine.plist
```

---

### State File Corrupted

**Symptom:** Engine crashes with "STATE FILE CORRUPTED"

**Emergency Fix:**
```bash
# Backup current state
cp workspace/logs/trading_engine_state.json workspace/logs/trading_engine_state.json.backup

# Reset state (WARNING: Loses tracking of open positions)
rm workspace/logs/trading_engine_state.json

# Restart engine — will reconcile live positions
launchctl unload ~/Library/LaunchAgents/com.ats.trading-engine.plist
launchctl load ~/Library/LaunchAgents/com.ats.trading-engine.plist
```

**⚠️ CRITICAL:** After reset, manually verify all open positions are tracked:
```bash
python3 scripts/position_health.py
python3 scripts/trading_engine.py --status  # Check "Open positions" count
```

---

## DEPLOYMENT (NEW MACHINE SETUP)

### 1. Install Dependencies

```bash
# Python 3.12+
python3 --version

# Install packages
cd ~/Projects/autonomous-trading-system
pip3 install -r requirements.txt
```

### 2. Configure Environment Variables

**⚠️ SECURE:** Store in password manager, never commit to git

```bash
export HL_PRIVATE_KEY="0x..."
export HL_ADDRESS="0x..."
export OPENAI_API_KEY="sk-..."
```

Persist in `~/.zshrc` or `~/.bashrc`:
```bash
echo 'export HL_PRIVATE_KEY="0x..."' >> ~/.zshrc
```

### 3. Create Launchd Plist

```bash
cat > ~/Library/LaunchAgents/com.ats.trading-engine.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.ats.trading-engine</string>
    
    <key>ProgramArguments</key>
    <array>
        <string>/Library/Frameworks/Python.framework/Versions/3.12/bin/python3</string>
        <string>/Users/yumo/Projects/autonomous-trading-system/scripts/trading_engine.py</string>
    </array>
    
    <key>WorkingDirectory</key>
    <string>/Users/yumo/Projects/autonomous-trading-system</string>
    
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
        <key>HL_PRIVATE_KEY</key>
        <string>REPLACE_WITH_ACTUAL_KEY</string>
        <key>HL_ADDRESS</key>
        <string>REPLACE_WITH_ACTUAL_ADDRESS</string>
    </dict>
    
    <key>StandardOutPath</key>
    <string>/Users/yumo/Projects/autonomous-trading-system/workspace/logs/engine-stdout.log</string>
    
    <key>StandardErrorPath</key>
    <string>/Users/yumo/Projects/autonomous-trading-system/workspace/logs/engine-stderr.log</string>
    
    <key>RunAtLoad</key>
    <true/>
    
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
        <key>Crashed</key>
        <true/>
    </dict>
    
    <key>ThrottleInterval</key>
    <integer>10</integer>
</dict>
</plist>
EOF

# Secure permissions
chmod 600 ~/Library/LaunchAgents/com.ats.trading-engine.plist
```

**⚠️ SECURITY:** Replace placeholders with actual secrets

### 4. Start Engine

```bash
launchctl load ~/Library/LaunchAgents/com.ats.trading-engine.plist

# Verify
python3 ~/Projects/autonomous-trading-system/scripts/trading_engine.py --status
```

---

## BACKUP & RECOVERY

### Critical Files to Backup

1. **State file** (position tracking)
   - `workspace/logs/trading_engine_state.json`

2. **Trade logs** (historical data)
   - `workspace/logs/trading_engine.jsonl`

3. **Launchd plist** (contains secrets)
   - `~/Library/LaunchAgents/com.ats.trading-engine.plist`

### Backup Script

```bash
#!/bin/bash
BACKUP_DIR="$HOME/Projects/autonomous-trading-system/backups/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

cp workspace/logs/trading_engine_state.json "$BACKUP_DIR/"
cp workspace/logs/trading_engine.jsonl "$BACKUP_DIR/"
cp ~/Library/LaunchAgents/com.ats.trading-engine.plist "$BACKUP_DIR/"

echo "✅ Backup created: $BACKUP_DIR"
```

---

## SECURITY CHECKLIST

- [ ] Secrets stored in environment variables (not code)
- [ ] Launchd plist permissions: `chmod 600`
- [ ] `.gitignore` includes: `*.log`, `*.jsonl`, `.env`, `*.key`
- [ ] Trade logs contain no API keys or private keys
- [ ] Remote git repo has no secrets committed

**Verify:**
```bash
cd ~/Projects/autonomous-trading-system
git log --all --full-history --source --stat -- "*.key" "*.env"  # Should be empty
```

---

## CONTACTS & ESCALATION

**System Owner:** Yumo  
**Documentation:** `~/Projects/autonomous-trading-system/docs/`  
**Issues:** Review logs first, then restart engine

**Emergency Stop:**
```bash
launchctl unload ~/Library/LaunchAgents/com.ats.trading-engine.plist
# Manually close all positions via Hyperliquid web UI if needed
```

---

**Last Updated:** 2026-04-06
