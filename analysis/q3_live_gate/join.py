#!/usr/bin/env python3
"""Join post-cutoff paper closes with execution_log entries on (asset, entry_time).

Match strategy: for each paper close, find the execution_log entry where
  - asset matches
  - timestamp is within ±tolerance_seconds of entry_time
  - if multiple matches, pick the closest by |delta|
Records composite_score, gate_decision (composite_score ≥ 0.70), time_delta.
Emits joined_trades.jsonl on stdout, summary on stderr.
"""
import argparse
import json
import sys
from datetime import datetime


def parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--paper", required=True)
    ap.add_argument("--exec-log", required=True)
    ap.add_argument("--tolerance-seconds", type=float, default=60.0)
    ap.add_argument("--threshold", type=float, default=0.70)
    args = ap.parse_args()

    paper = []
    with open(args.paper) as fh:
        for line in fh:
            paper.append(json.loads(line))

    exec_entries = []
    with open(args.exec_log) as fh:
        for line in fh:
            r = json.loads(line)
            details = r.get("details") or {}
            exec_entries.append({
                "asset": r.get("asset") or details.get("asset"),
                "ts": parse_iso(r["timestamp"]),
                "action": r.get("action"),
                "composite_score": details.get("composite_score"),
                "score_normalized": details.get("score_normalized"),
                "raw": r,
            })

    joined = []
    unmatched = []

    for p in paper:
        asset = p["asset"]
        et = parse_iso(p["entry_time"])
        candidates = [
            e for e in exec_entries
            if e["asset"] == asset
            and abs((e["ts"] - et).total_seconds()) <= args.tolerance_seconds
        ]
        if not candidates:
            unmatched.append({
                "position_id": p["position_id"],
                "asset": asset,
                "entry_time": p["entry_time"],
                "net_pnl_usd": p["net_pnl_usd"],
            })
            continue
        best = min(candidates, key=lambda e: abs((e["ts"] - et).total_seconds()))
        delta = (best["ts"] - et).total_seconds()
        score = best["composite_score"]
        score_norm = best["score_normalized"]
        # composite_score in execution_log is on 0-100 scale; score_normalized is 0-1
        # threshold is 0.70 (normalized), so compare against score_normalized
        gate_pass = (score_norm is not None) and (score_norm >= args.threshold)
        joined.append({
            "position_id": p["position_id"],
            "asset": asset,
            "entry_time_paper": p["entry_time"],
            "entry_time_exec": best["ts"].isoformat(),
            "time_delta_seconds": delta,
            "composite_score": score,
            "score_normalized": score_norm,
            "gate_decision": "PASS" if gate_pass else "FAIL",
            "exec_action": best["action"],
            "net_pnl_usd": p["net_pnl_usd"],
            "exit_reason": p["exit_reason"],
        })

    for j in joined:
        sys.stdout.write(json.dumps(j) + "\n")

    n_paper = len(paper)
    n_joined = len(joined)
    n_unmatched = len(unmatched)
    n_gate_pass = sum(1 for j in joined if j["gate_decision"] == "PASS")
    coverage = n_joined / n_paper if n_paper else 0

    sys.stderr.write(
        f"n_paper_closes={n_paper}\n"
        f"n_joined={n_joined}\n"
        f"n_unmatched={n_unmatched}\n"
        f"join_coverage={coverage:.4f}\n"
        f"n_gated_pass={n_gate_pass}\n"
        f"unmatched_assets={[(u['asset'], u['entry_time']) for u in unmatched]}\n"
    )


if __name__ == "__main__":
    main()
