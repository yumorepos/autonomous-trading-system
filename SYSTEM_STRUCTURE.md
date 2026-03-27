# SYSTEM STRUCTURE (Post-Cleanup)

**Last Updated:** 2026-03-26 21:05 UTC  
**Status:** OPERATIONAL — Streamlined for 30-day challenge

---

## ATS REPOSITORY (~/Projects/autonomous-trading-system)

### Essential Documents (7 files)
```
CEO_MANDATE.md              # Authoritative execution rules
CEO_OPERATING_SYSTEM.md     # 30-day framework  
CEO_DECISION_ENGINE.md      # Automated decision-making
SCALING_AND_MONETIZATION.md # Monetization pathway
STATUS.md                   # Current operational snapshot
README.md                   # Repo overview
.discipline-lock            # Commitment mechanism
```

### Active Scripts (6 core + 26 supporting)
```
scripts/ceo_decision_engine.py  # Daily decision automation
scripts/daily_update.py         # Progress tracker
scripts/trade_logger.py         # Full lifecycle logging
scripts/tiered_scanner.py       # Signal classification
scripts/hl_entry.py             # Entry execution (LIVE mode)
scripts/risk-guardian.py        # Exit monitoring (30-min cycles)
```

### Memory & Artifacts
```
memory/2026-03-26.md            # Today's log (only recent kept)
artifacts/CASE_STUDY.md         # Project case study
artifacts/INTERVIEW_PREP.md     # Interview Q&A
artifacts/PERFORMANCE_REPORT.md # Performance summary
```

### Archive
```
archive/superseded-2026-03-26/  # 26 archived files (old docs, reports)
docs/archive/                    # 50+ old audit reports
```

---

## WORKSPACE (~/.openclaw/workspace)

### Core Configuration (10 files)
```
CURRENT_MISSION.md    # Permanent reference (30-day goal + discipline lock)
MEMORY.md             # Quick task list
HEARTBEAT.md          # Automated daily tasks
SOUL.md               # Persona definition
USER.md               # User profile
IDENTITY.md           # Bot identity
AGENTS.md             # Subagent config
TOOLS.md              # CLI tools inventory
QUICK_REFERENCE.md    # Command shortcuts
README.md             # Workspace overview
```

### Memory
```
memory/2026-03-26.md  # Today's comprehensive log
memory/archive/       # Older memory files (7+ days)
```

### Archive
```
archive/superseded-2026-03-26/  # 33 archived files (job guides, old reports)
```

---

## AUTOMATION

### Launchd Jobs
```
com.ats.risk-guardian   # Runs every 30 min
  - Scans for signals
  - Monitors positions
  - Executes exits (SL/TP/trailing/timeout)
```

### Daily Automation (via HEARTBEAT)
```
00:00-01:00 UTC:
1. Run daily_update.py (progress report)
2. Run ceo_decision_engine.py (assess + execute)
3. Post update to chat (capital, trades, decision)
```

---

## DATA FLOW

### Entry → Exit Cycle
```
1. tiered_scanner.py → Finds Tier 1/2 signals
2. hl_entry.py → Enters position (records entry data)
3. risk-guardian.py → Monitors position (30-min cycles)
4. trade_logger.py → Logs exit (calculates P&L, funding, ROI)
```

### Daily Decision Cycle
```
1. daily_update.py → Reads current state
2. ceo_decision_engine.py → Assesses validation state
3. Auto-execute → HOLD/SCALE/HALT (where safe)
4. User notification → Progress + decision
```

---

## FILE COUNTS (Before/After)

| Location | Before | After | Archived |
|---|---|---|---|
| **ATS MD files** | 71 | 7 | 64 |
| **Workspace MD files** | 28 | 10 | 18 |
| **Memory files** | 25 | 1 | 24 |
| **Total** | **124** | **18** | **106** |

**Reduction:** 85% fewer files to manage

---

## KEY BENEFITS

### 1. Faster Context Loading
- 18 essential files vs 124 total
- No confusion about which doc is current
- All superseded docs archived (not deleted)

### 2. Clear Hierarchy
- CEO_MANDATE = authoritative rules
- CEO_OPERATING_SYSTEM = 30-day framework
- STATUS = current state
- CURRENT_MISSION = permanent reference

### 3. Efficient Automation
- 1 launchd job (was checking for duplicates)
- 2 daily scripts (update + decision)
- Clean logs (only recent data)

### 4. Easy Recovery
- All archived files preserved
- Can reference old docs if needed
- Git history intact

---

## DAILY WORKFLOW (Automated)

### What Runs Automatically:
1. **Every 30 min:** risk-guardian.py (scan/monitor/exit)
2. **Every day (00:00 UTC):** daily_update.py + ceo_decision_engine.py
3. **On exit:** trade_logger.py captures data

### What You See:
Daily update message:
```
Day X/30 | Capital: $X → $194 | Trades: X/20
CEO Decision: HOLD/SCALE/REVIEW/HALT
Execution: [What was auto-executed]
Dashboard: https://ats-dashboard-omega.vercel.app
```

### What You Do:
- **Week 1-2:** Nothing (system autonomous)
- **Week 3:** Review if 20 trades complete
- **Week 4:** Monitor capital progress toward $194

---

## EMERGENCY COMMANDS

### Check Status
```bash
cd ~/Projects/autonomous-trading-system
python3 scripts/daily_update.py
python3 scripts/ceo_decision_engine.py
python3 scripts/trade_logger.py
```

### Manual Intervention
```bash
# Stop system
launchctl unload ~/Library/LaunchAgents/com.ats.risk-guardian.plist

# Restart system
launchctl load ~/Library/LaunchAgents/com.ats.risk-guardian.plist
```

### Read Context
```bash
cat ~/.openclaw/workspace/CURRENT_MISSION.md
cat ~/Projects/autonomous-trading-system/STATUS.md
```

---

## NEXT SESSION CHECKLIST

When conversation ends, next session should:
1. Read `CURRENT_MISSION.md` (permanent reference)
2. Check `STATUS.md` (current state)
3. Run `daily_update.py` (if new day)
4. Maintain discipline lock (no optimization until 20 trades)

---

**Status:** OPERATIONAL — Clean, efficient, ready for 30-day challenge  
**Files:** 18 essential (vs 124 before)  
**Automation:** Active (launchd + daily scripts)  
**Next:** First daily update tomorrow 00:00-01:00 UTC
