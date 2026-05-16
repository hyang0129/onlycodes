"""Structural verifier for ml_engineering__curve_queries_{easy,medium,hard}.

Checks that ``output/answers.json`` exists, is valid JSON, and contains the
expected keys for the difficulty inferred from experiments.csv row count.

Does NOT check correctness — that is the hidden grader's job.
Run this to confirm output structure before a grading run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_QUERIES_BY_DIFFICULTY = {
    "easy":   ["best_val_loss_per_run"],
    "medium": ["best_val_loss_per_run", "convergence_step_per_run", "mean_train_val_gap"],
    "hard":   ["best_val_loss_per_run", "convergence_step_per_run", "mean_train_val_gap",
               "overfit_onset_per_run", "best_run_overall"],
}
N_RUNS = 50


def _difficulty(steps_per_run: int) -> str:
    if steps_per_run <= 2_000:
        return "easy"
    if steps_per_run <= 20_000:
        return "medium"
    return "hard"


def main(scratch_dir: str | None = None) -> None:
    base = Path(scratch_dir) if scratch_dir else Path(__file__).parent

    csv_path = base / "experiments.csv"
    output_path = base / "output" / "answers.json"

    errors: list[str] = []

    if not csv_path.is_file():
        print("FAIL: experiments.csv not found in scratch dir")
        sys.exit(1)

    if not output_path.is_file():
        print("FAIL: output/answers.json not found")
        sys.exit(1)

    try:
        text = output_path.read_text()
        agent_out = json.loads(text)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FAIL: could not parse output/answers.json: {exc}")
        sys.exit(1)

    if not isinstance(agent_out, dict):
        print("FAIL: output/answers.json must be a JSON object (dict)")
        sys.exit(1)

    # Infer difficulty from CSV row count without reading whole file.
    try:
        with open(csv_path) as fh:
            total_rows = sum(1 for _ in fh) - 1  # subtract header
        steps_per_run = total_rows // N_RUNS
        diff = _difficulty(steps_per_run)
        expected_keys = _QUERIES_BY_DIFFICULTY[diff]
    except Exception as exc:
        print(f"FAIL: could not read experiments.csv to infer difficulty: {exc}")
        sys.exit(1)

    for key in expected_keys:
        if key not in agent_out:
            errors.append(f"missing key: {key!r}")
            continue
        val = agent_out[key]
        if key in ("best_val_loss_per_run", "convergence_step_per_run", "overfit_onset_per_run"):
            if not isinstance(val, dict):
                errors.append(f"{key}: expected dict, got {type(val).__name__}")
            elif len(val) != N_RUNS:
                errors.append(f"{key}: expected {N_RUNS} entries, got {len(val)}")
        elif key == "mean_train_val_gap":
            if not isinstance(val, (int, float)):
                errors.append(f"{key}: expected numeric scalar, got {type(val).__name__}")
        elif key == "best_run_overall":
            if not isinstance(val, str):
                errors.append(f"{key}: expected string, got {type(val).__name__}")

    if errors:
        for err in errors:
            print(f"FAIL: {err}")
        sys.exit(1)

    print(f"OK: output/answers.json is structurally valid [{diff}, {len(expected_keys)} queries]")
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
