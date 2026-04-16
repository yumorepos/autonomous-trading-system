#!/bin/bash
# Log rotation for paper trader logs.
# Rotates logs over 50MB, keeps 3 backups.
# Add to crontab: 0 */6 * * * bash /Users/yumo/Projects/autonomous-trading-system/deploy/rotate-logs.sh
#
# Uses copytruncate approach: copies the file, then truncates the original.
# This avoids needing to restart the process (it keeps writing to the same fd).

PROJECT_ROOT="/Users/yumo/Projects/autonomous-trading-system"
MAX_SIZE=$((50 * 1024 * 1024))  # 50MB
KEEP=3

rotate_file() {
    local file="$1"
    if [ ! -f "$file" ]; then
        return
    fi

    local size
    size=$(stat -f%z "$file" 2>/dev/null || echo 0)

    if [ "$size" -gt "$MAX_SIZE" ]; then
        # Rotate existing backups
        for i in $(seq $((KEEP - 1)) -1 1); do
            if [ -f "${file}.${i}" ]; then
                mv "${file}.${i}" "${file}.$((i + 1))"
            fi
        done

        # Copy current to .1, then truncate
        cp "$file" "${file}.1"
        : > "$file"

        # Remove oldest if beyond KEEP
        rm -f "${file}.$((KEEP + 1))"

        echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') Rotated $file ($size bytes)" >> "$PROJECT_ROOT/data/rotate.log"
    fi
}

rotate_file "$PROJECT_ROOT/data/paper_stdout.log"
rotate_file "$PROJECT_ROOT/data/paper_stderr.log"
# NOTE: paper_trades.jsonl is a trade LEDGER, not a log. It must NOT be
# rotated — the paper trader reads it on startup to rebuild position state
# and compute lifetime aggregate stats (win rate, expectancy, total PnL).
# Rotating it fragments trade history across .1/.2.gz files, resetting
# stats on every restart.
