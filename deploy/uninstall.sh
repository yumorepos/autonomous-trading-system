#!/bin/bash
set -euo pipefail

# Uninstall the ATS paper trader launchd agent.
# Usage: bash deploy/uninstall.sh

PLIST_DST="$HOME/Library/LaunchAgents/com.ats.paper-trader.plist"
LABEL="com.ats.paper-trader"

echo "=== Uninstalling ATS Paper Trader ==="

if launchctl list | grep -q "$LABEL"; then
    echo "Unloading agent..."
    launchctl unload "$PLIST_DST" 2>/dev/null || true
fi

if [ -f "$PLIST_DST" ]; then
    echo "Removing plist..."
    rm "$PLIST_DST"
fi

echo "Done. Paper trader stopped and removed from auto-start."
