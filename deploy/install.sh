#!/bin/bash
set -euo pipefail

# Install the ATS paper trader as a macOS launchd user agent.
# No sudo required — runs as the current user.
#
# Usage: bash deploy/install.sh

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLIST_SRC="$PROJECT_ROOT/deploy/com.ats.paper-trader.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.ats.paper-trader.plist"
LABEL="com.ats.paper-trader"

echo "=== ATS Paper Trader — launchd Deployment ==="
echo "Project root: $PROJECT_ROOT"
echo "Plist:        $PLIST_DST"
echo ""

# 1. Validate plist
echo "--- Validating plist ---"
plutil -lint "$PLIST_SRC" || { echo "ERROR: Invalid plist"; exit 1; }

# 2. Ensure data directory exists
mkdir -p "$PROJECT_ROOT/data"

# 3. Unload existing agent if running
if launchctl list | grep -q "$LABEL"; then
    echo "--- Unloading existing agent ---"
    launchctl unload "$PLIST_DST" 2>/dev/null || true
fi

# 4. Create LaunchAgents directory if needed
mkdir -p "$HOME/Library/LaunchAgents"

# 5. Copy plist into place
echo "--- Installing plist ---"
cp "$PLIST_SRC" "$PLIST_DST"

# 6. Load the agent
echo "--- Loading agent ---"
launchctl load "$PLIST_DST"

# 7. Wait for startup
sleep 3

# 8. Verify
if launchctl list | grep -q "$LABEL"; then
    echo ""
    echo "=== Installation complete ==="
    echo ""
    echo "Commands:"
    echo "  Status:   launchctl list | grep paper-trader"
    echo "  Stop:     launchctl unload ~/Library/LaunchAgents/com.ats.paper-trader.plist"
    echo "  Start:    launchctl load ~/Library/LaunchAgents/com.ats.paper-trader.plist"
    echo "  Restart:  launchctl unload ~/Library/LaunchAgents/com.ats.paper-trader.plist && launchctl load ~/Library/LaunchAgents/com.ats.paper-trader.plist"
    echo "  Logs:     tail -f $PROJECT_ROOT/data/paper_stdout.log"
    echo "  Errors:   tail -f $PROJECT_ROOT/data/paper_stderr.log"
    echo ""
    echo "The service will:"
    echo "  - Auto-restart on crash (KeepAlive + ThrottleInterval 10s)"
    echo "  - Auto-start on user login (RunAtLoad)"
    echo ""
else
    echo "ERROR: Agent failed to load. Check:"
    echo "  plutil -lint $PLIST_SRC"
    echo "  tail -20 $PROJECT_ROOT/data/paper_stderr.log"
    exit 1
fi
