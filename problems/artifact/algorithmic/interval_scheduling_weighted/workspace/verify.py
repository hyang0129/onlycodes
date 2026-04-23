#!/usr/bin/env python3
"""Structural verifier for algorithmic__interval_scheduling_weighted."""

import json
import sys
from pathlib import Path

REQUESTS = Path(__file__).parent / "requests.json"
OUTPUT = Path(__file__).parent / "output" / "schedule.json"


def main() -> int:
    if not REQUESTS.is_file():
        print(f"FAIL: requests.json not found at {REQUESTS}", file=sys.stderr)
        return 1
    data = json.loads(REQUESTS.read_text())
    by_id = {r["id"]: r for r in data["requests"]}

    if not OUTPUT.is_file():
        print(f"FAIL: output file not found: {OUTPUT}", file=sys.stderr)
        return 1

    try:
        out = json.loads(OUTPUT.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FAIL: could not parse output JSON: {exc}", file=sys.stderr)
        return 1

    if not isinstance(out, dict):
        print("FAIL: output must be a JSON object", file=sys.stderr)
        return 1

    if "total_revenue" not in out:
        print("FAIL: missing required key 'total_revenue'", file=sys.stderr)
        return 1

    tr = out["total_revenue"]
    if isinstance(tr, bool) or not isinstance(tr, int):
        print(f"FAIL: total_revenue must be an integer", file=sys.stderr)
        return 1
    if tr < 0:
        print(f"FAIL: total_revenue must be non-negative, got {tr}", file=sys.stderr)
        return 1

    if "chosen_ids" in out:
        ids = out["chosen_ids"]
        if not isinstance(ids, list):
            print("FAIL: chosen_ids must be a list", file=sys.stderr)
            return 1
        if len(set(ids)) != len(ids):
            print("FAIL: chosen_ids contains duplicates", file=sys.stderr)
            return 1
        for i in ids:
            if not isinstance(i, int) or isinstance(i, bool) or i not in by_id:
                print(f"FAIL: chosen_ids contains invalid id {i!r}", file=sys.stderr)
                return 1
        # Non-overlap check
        chosen = sorted((by_id[i] for i in ids), key=lambda r: r["start"])
        for a, b in zip(chosen[:-1], chosen[1:]):
            if a["end"] > b["start"]:
                print(f"FAIL: chosen intervals overlap: {a['id']} and {b['id']}", file=sys.stderr)
                return 1

    print(f"OK: total_revenue={tr}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
