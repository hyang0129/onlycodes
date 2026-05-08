#!/usr/bin/env python3
"""Pre-merge grader **negative** sanity gate (SCHEMA_ARTIFACT.md §5.5).

The positive sanity check (``tools/verify_graders.py``) feeds a task's
``reference_output`` into its grader and asserts ``passed=True, score=1.0``.
That catches graders that reject their own known-good answer, but it does
NOT catch graders that *accept* deliberately-wrong artifacts because the
prompt's correctness criterion was incompletely encoded.

This tool walks every task under ``problems/artifact/<category>/<slug>/``,
applies a small set of *deliberately wrong* mutations to the reference
output, runs the grader against each mutated artifact, and asserts the
grader returns ``passed=False``. Mutations come from
``swebench.artifact_negative.default_negative_cases`` plus, optionally, a
per-task ``grader/negative_cases.py`` shipping a ``NEGATIVE_CASES`` list.

Exit codes:
  0  every case the framework expects to catch was caught (known-bug
     ``EXPECTED_MISS`` outcomes are tolerated; they print a warning)
  1  at least one mutation slipped through the grader unexpectedly
     (``MISS``), the grader rejected for the wrong reason
     (``WRONG_REASON``), or a case raised an infrastructure error (``ERROR``)
  2  task discovery / parse error, or no tasks found

Usage:
    python tools/check_grader_negative.py
    python tools/check_grader_negative.py --tasks-dir path/to/problems/artifact
    python tools/check_grader_negative.py --filter data_processing__multi_file_cohort
    python tools/check_grader_negative.py --tasks-with-custom-cases-only
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

# Allow running as ``python tools/check_grader_negative.py`` from the repo
# root without editable-installing swebench.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from swebench.artifact_loader import load_tasks
from swebench.artifact_negative import (
    NegativeCaseOutcome,
    load_task_negative_cases,
    run_all_for_task,
)


_STATUS_GLYPH = {
    "PASS": "PASS",
    "MISS": "MISS",
    "WEAK_MISS": "WEAK",
    "WRONG_REASON": "WRONG",
    "EXPECTED_MISS": "WARN",
    "ERROR": "ERR ",
}


def _print_outcome(outcome: NegativeCaseOutcome) -> None:
    glyph = _STATUS_GLYPH.get(outcome.status, outcome.status)
    print(
        f"  {glyph}  {outcome.case_name:<22s}  {outcome.detail}",
        flush=True,
    )


def _has_custom_cases(task) -> bool:
    candidate = (task.task_dir or Path(".")) / "grader" / "negative_cases.py"
    return candidate.is_file()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0] if __doc__ else "",
    )
    parser.add_argument(
        "--tasks-dir",
        type=Path,
        default=_REPO_ROOT / "problems" / "artifact",
        help="root tasks directory (default: <repo>/problems/artifact/)",
    )
    parser.add_argument(
        "--filter",
        action="append",
        default=[],
        metavar="INSTANCE_ID",
        help=(
            "only run on the named task(s); may be passed multiple times. "
            "If omitted, every task under --tasks-dir is exercised."
        ),
    )
    parser.add_argument(
        "--tasks-with-custom-cases-only",
        action="store_true",
        help=(
            "only exercise tasks that ship grader/negative_cases.py. "
            "Useful for the per-PR fast lane: a task author adding a new "
            "task can confirm their custom cases work without paying for "
            "every other task's default cases."
        ),
    )
    parser.add_argument(
        "--grader-timeout-seconds",
        type=float,
        default=120.0,
        help="per-grader timeout passed through to invoke_grader",
    )
    args = parser.parse_args(argv)

    tasks_dir: Path = args.tasks_dir
    filter_ids: list[str] | None = list(args.filter) or None

    try:
        tasks = load_tasks(tasks_dir, filter_ids=filter_ids)
    except ValueError as exc:
        print(f"ERROR: task discovery/parse failed: {exc}", file=sys.stderr)
        return 2

    if not tasks:
        print("No tasks found — nothing to check.", file=sys.stderr)
        return 2

    if args.tasks_with_custom_cases_only:
        tasks = [t for t in tasks if _has_custom_cases(t)]
        if not tasks:
            print(
                "No tasks ship grader/negative_cases.py "
                "(filtered by --tasks-with-custom-cases-only).",
                file=sys.stderr,
            )
            return 2

    overall_exit = 0
    counts: Counter[str] = Counter()
    miss_records: list[NegativeCaseOutcome] = []

    for task in tasks:
        custom = _has_custom_cases(task)
        marker = "(custom)" if custom else "(default)"
        print(f"\n{task.instance_id}  {marker}", flush=True)

        try:
            cases, is_custom = load_task_negative_cases(task)
        except Exception as exc:  # noqa: BLE001 — surface any author error
            print(f"  ERR   <load_negative_cases>  {exc}", flush=True, file=sys.stderr)
            counts["ERROR"] += 1
            overall_exit = 1
            continue

        if not cases:
            print("  WARN  <no cases registered>", flush=True)
            continue

        outcomes = run_all_for_task(
            task,
            cases,
            grader_timeout_seconds=args.grader_timeout_seconds,
            from_defaults=not is_custom,
        )
        for outcome in outcomes:
            _print_outcome(outcome)
            counts[outcome.status] += 1
            if outcome.is_failure:
                overall_exit = 1
                miss_records.append(outcome)

    print(
        "\nSummary: "
        f"{counts['PASS']} pass, "
        f"{counts['MISS']} missed-by-grader (custom), "
        f"{counts['WEAK_MISS']} missed-by-grader (default mutations, diagnostic), "
        f"{counts['WRONG_REASON']} wrong-reason, "
        f"{counts['EXPECTED_MISS']} known-bug warnings, "
        f"{counts['ERROR']} errors.",
        flush=True,
    )

    if counts["WEAK_MISS"] > 0:
        print(
            f"\n{counts['WEAK_MISS']} default-mutation MISS(es) on tasks "
            "without grader/negative_cases.py — these reveal alignment bugs "
            "but do not fail CI. Track each by adding a per-task "
            "negative_cases.py with currently_caught=False (see SCHEMA §5.5).",
        )

    if miss_records:
        print(
            "\nFailures (these slipped through the grader unexpectedly):",
            file=sys.stderr,
        )
        for o in miss_records:
            print(
                f"  {o.task_id}::{o.case_name}  [{o.status}]  {o.detail}",
                file=sys.stderr,
            )

    return overall_exit


if __name__ == "__main__":
    sys.exit(main())
