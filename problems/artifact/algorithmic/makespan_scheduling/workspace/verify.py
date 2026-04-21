#!/usr/bin/env python3
"""Structural verifier for algorithmic__makespan_scheduling.

Checks output/schedule.json has the correct shape:
  - JSON object
  - "makespan" key with a numeric value
  - optional "assignment" key: list of num_machines lists of job ids

Does NOT check optimality — that is the hidden grader's job.
"""

import json
import sys
from pathlib import Path

JOBS_FILE = Path(__file__).parent / "jobs.json"
OUTPUT_FILE = Path(__file__).parent / "output" / "schedule.json"


def main() -> int:
    if not JOBS_FILE.is_file():
        print(f"FAIL: jobs.json not found at {JOBS_FILE}", file=sys.stderr)
        return 1
    jobs_data = json.loads(JOBS_FILE.read_text())
    num_machines = jobs_data["num_machines"]
    num_jobs = len(jobs_data["job_durations"])

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

    if "makespan" not in out:
        print("FAIL: missing required key 'makespan'", file=sys.stderr)
        return 1

    ms = out["makespan"]
    if isinstance(ms, bool) or not isinstance(ms, (int, float)):
        print(f"FAIL: makespan must be a number, got {type(ms).__name__}", file=sys.stderr)
        return 1

    if ms <= 0:
        print(f"FAIL: makespan must be positive, got {ms}", file=sys.stderr)
        return 1

    if "assignment" in out:
        assignment = out["assignment"]
        if not isinstance(assignment, list) or len(assignment) != num_machines:
            print(
                f"FAIL: assignment must be a list of {num_machines} lists",
                file=sys.stderr,
            )
            return 1
        all_jobs = sorted(j for m in assignment for j in m)
        if all_jobs != list(range(num_jobs)):
            print(
                "FAIL: assignment is not a valid partition of all job ids",
                file=sys.stderr,
            )
            return 1

    print(f"OK: makespan={ms}" + (f" with assignment" if "assignment" in out else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
