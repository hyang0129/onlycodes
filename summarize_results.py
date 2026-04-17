#!/usr/bin/env python3
"""Summarize SWE-bench experiment results from results_swebench/."""

import csv
import json
import os
import glob
import statistics
import sys
from collections import defaultdict

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results_swebench")


def load_result_record(jsonl_path: str) -> dict | None:
    """Return the final 'result' record from a JSONL file."""
    result = None
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("type") == "result":
                result = record
    return result


def load_test_outcome(test_txt_path: str) -> str | None:
    """Return 'PASS', 'FAIL', or None if file missing."""
    if not os.path.exists(test_txt_path):
        return None
    with open(test_txt_path) as f:
        content = f.read()
    last_line = content.strip().splitlines()[-1].strip() if content.strip() else ""
    return last_line if last_line in ("PASS", "FAIL") else "UNKNOWN"


def collect_runs() -> list[dict]:
    runs = []
    for jsonl_path in sorted(glob.glob(os.path.join(RESULTS_DIR, "*.jsonl"))):
        basename = os.path.basename(jsonl_path)
        # derive test file: replace .jsonl -> _test.txt
        stem = basename[: -len(".jsonl")]
        test_path = os.path.join(RESULTS_DIR, stem + "_test.txt")

        result = load_result_record(jsonl_path)
        if result is None:
            continue

        usage = result.get("usage", {})
        # parse arm and run number from filename e.g. django__django-15814_onlycode_run1
        parts = stem.rsplit("_run", 1)
        run_num = int(parts[1]) if len(parts) == 2 and parts[1].isdigit() else None
        name_parts = parts[0].rsplit("_", 1)
        arm = name_parts[-1] if len(name_parts) == 2 else "unknown"
        instance_id = name_parts[0] if len(name_parts) == 2 else parts[0]

        runs.append(
            {
                "file": basename,
                "instance_id": instance_id,
                "arm": arm,
                "run": run_num,
                "outcome": load_test_outcome(test_path),
                "num_turns": result.get("num_turns", 0),
                "cost_usd": result.get("total_cost_usd", 0.0),
                "duration_ms": result.get("duration_ms", 0),
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "cache_creation_tokens": usage.get("cache_creation_input_tokens", 0),
                "cache_read_tokens": usage.get("cache_read_input_tokens", 0),
            }
        )
    return runs


FIELDS = [
    "instance_id", "arm", "run", "outcome",
    "num_turns", "cost_usd", "duration_ms",
    "input_tokens", "output_tokens", "cache_creation_tokens", "cache_read_tokens",
]


def main() -> None:
    runs = collect_runs()
    if not runs:
        print("No result records found in", RESULTS_DIR, file=sys.stderr)
        return

    writer = csv.DictWriter(sys.stdout, fieldnames=FIELDS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(runs)


if __name__ == "__main__":
    main()
