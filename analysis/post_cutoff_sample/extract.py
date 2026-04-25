#!/usr/bin/env python3
"""Extract post-cutoff clean closed paper trades.

Input: paper_trades.jsonl
Filter: action == "CLOSE" AND entry_time > SAMPLE_CUTOFF_TS AND status NOT in admin_*
        (admin reclassifications use exit_reason/status fields prefixed admin_*)
Output: JSONL of qualifying CLOSE rows on stdout, summary on stderr.
"""
import argparse
import json
import sys
from datetime import datetime, timezone


def parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def is_admin(row: dict) -> bool:
    for field in ("status", "exit_reason", "action"):
        v = row.get(field)
        if isinstance(v, str) and v.startswith("admin_"):
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--cutoff", required=True, help="ISO timestamp; entry_time strictly greater")
    ap.add_argument("--exclude-admin", action="store_true", default=True)
    args = ap.parse_args()

    cutoff = parse_iso(args.cutoff)
    raw_close = 0
    admin_dropped = 0
    pre_cutoff = 0
    kept = []

    with open(args.input) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("action") != "CLOSE":
                continue
            raw_close += 1
            if args.exclude_admin and is_admin(row):
                admin_dropped += 1
                continue
            entry_ts = row.get("entry_time")
            if not entry_ts:
                continue
            entry_dt = parse_iso(entry_ts)
            if entry_dt <= cutoff:
                pre_cutoff += 1
                continue
            kept.append(row)

    for row in kept:
        sys.stdout.write(json.dumps(row) + "\n")

    sys.stderr.write(
        f"raw_close={raw_close}\n"
        f"admin_dropped={admin_dropped}\n"
        f"pre_cutoff_dropped={pre_cutoff}\n"
        f"post_cutoff_clean={len(kept)}\n"
    )


if __name__ == "__main__":
    main()
