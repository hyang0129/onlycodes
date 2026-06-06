"""Subprocess entry point for official SWE-bench grading (C5 #319).

Runs under the **isolated** ``swebench==<pin>`` venv only — that package's name
collides with our repo's ``swebench`` package, so it cannot be imported
in-process (see ``scripts/extract_swebench_specs.py`` and ``swebench/specs.py``).
Do NOT import this module from our package.

Protocol: reads one JSON object from stdin::

    {"instance": <full SWE-bench instance dict>, "log": "<test stdout/stderr>"}

and writes one JSON object to stdout::

    {"resolution": "RESOLVED_FULL|RESOLVED_PARTIAL|RESOLVED_NO",
     "report": {...}, "status_map": {test: status, ...}}

``instance`` must carry at least ``repo``, ``version``, ``FAIL_TO_PASS``,
``PASS_TO_PASS`` (plus whatever ``make_test_spec`` needs to build a spec —
``base_commit``, ``patch``, ``test_patch``, ``problem_statement``,
``environment_setup_commit``, ``instance_id``). Grading uses the official
``MAP_REPO_TO_PARSER`` + ``get_eval_tests_report`` + ``get_resolution_status``
for exact parity with SWE-bench.
"""

import json
import sys


def _coerce_list(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return [v]
    return list(v or [])


def main() -> None:
    req = json.load(sys.stdin)
    instance = req["instance"]
    log = req["log"]

    from swebench.harness.log_parsers import MAP_REPO_TO_PARSER
    from swebench.harness.grading import get_eval_tests_report, get_resolution_status
    from swebench.harness.constants import FAIL_TO_PASS, PASS_TO_PASS
    from swebench.harness.test_spec.test_spec import make_test_spec

    # A real TestSpec keeps repo-specific parsers that consult it correct; the
    # common pytest parsers only read ``log``.
    test_spec = make_test_spec(instance)
    parser = MAP_REPO_TO_PARSER[instance["repo"]]
    status_map = parser(log, test_spec)

    gold = {
        FAIL_TO_PASS: _coerce_list(instance.get("FAIL_TO_PASS")),
        PASS_TO_PASS: _coerce_list(instance.get("PASS_TO_PASS")),
    }
    report = get_eval_tests_report(status_map, gold)
    resolution = str(get_resolution_status(report))

    json.dump(
        {"resolution": resolution, "report": report, "status_map": status_map},
        sys.stdout,
    )


if __name__ == "__main__":
    main()
