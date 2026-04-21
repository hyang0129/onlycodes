#!/usr/bin/env python3
"""Structural verifier for algorithmic__min_cost_assignment.

Checks output/assignment.json has the correct shape:
  - JSON object with "assignment" key
  - assignment: list of num_workers integers, each in [0, num_tasks-1], no duplicates

Does NOT check optimality — that is the hidden grader's job.
"""

import json
import sys
from pathlib import Path

COST_FILE = Path(__file__).parent / "cost_matrix.json"
OUTPUT_FILE = Path(__file__).parent / "output" / "assignment.json"


def main() -> int:
    if not COST_FILE.is_file():
        print(f"FAIL: cost_matrix.json not found at {COST_FILE}", file=sys.stderr)
        return 1
    data = json.loads(COST_FILE.read_text())
    n = data["num_workers"]

    if not OUTPUT_FILE.is_file():
        print(f"FAIL: output file not found: {OUTPUT_FILE}", file=sys.stderr)
        return 1

    try:
        out = json.loads(OUTPUT_FILE.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FAIL: could not parse output JSON: {exc}", file=sys.stderr)
        return 1

    if not isinstance(out, dict):
        print("FAIL: output must be a JSON object", file=sys.stderr)
        return 1

    if "assignment" not in out:
        print("FAIL: missing required key 'assignment'", file=sys.stderr)
        return 1

    assignment = out["assignment"]
    if not isinstance(assignment, list) or len(assignment) != n:
        print(f"FAIL: assignment must be a list of {n} integers", file=sys.stderr)
        return 1

    seen = set()
    for i, task in enumerate(assignment):
        if not isinstance(task, int) or isinstance(task, bool):
            print(f"FAIL: assignment[{i}] must be an integer", file=sys.stderr)
            return 1
        if task < 0 or task >= n:
            print(f"FAIL: assignment[{i}]={task} out of range", file=sys.stderr)
            return 1
        if task in seen:
            print(f"FAIL: duplicate task {task} in assignment", file=sys.stderr)
            return 1
        seen.add(task)

    cost = sum(data["cost_matrix"][i][assignment[i]] for i in range(n))
    print(f"OK: valid perfect matching, total cost={cost}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
