"""Internal grader-runner subprocess entrypoint.

Invoked by ``swebench.artifact_grade.invoke_grader`` as:

    python -m swebench._artifact_grade_runner <grader_dir> <scratch_dir>

Imports ``hidden`` from ``<grader_dir>`` (prepended to ``sys.path``), calls
``hidden.grade(Path(scratch_dir))``, and serialises the result as a single
JSON object to stdout.

The grader is expected to return an object with ``passed: bool``, ``score:
float``, ``detail: str`` attributes (structural typing — see SCHEMA §3.1).
"""

from __future__ import annotations

import importlib
import json
import sys
import traceback
from pathlib import Path


def _serialize_exception(exc: BaseException) -> dict:
    return {
        "_error": True,
        "type": type(exc).__name__,
        "message": str(exc),
        "traceback": traceback.format_exc(),
    }


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(
            json.dumps({
                "_error": True,
                "type": "UsageError",
                "message": "usage: _artifact_grade_runner <grader_dir> <scratch_dir>",
                "traceback": "",
            })
        )
        return 2

    grader_dir = Path(argv[1]).resolve()
    scratch_dir = Path(argv[2]).resolve()

    sys.path.insert(0, str(grader_dir))
    try:
        # Drop any cached version from a prior subprocess (defensive; subprocess
        # starts with a fresh import cache anyway).
        sys.modules.pop("hidden", None)
        mod = importlib.import_module("hidden")
        grade_fn = getattr(mod, "grade", None)
        if grade_fn is None:
            raise AttributeError(
                f"{grader_dir / 'hidden.py'} does not define grade()"
            )
        result = grade_fn(scratch_dir)
        # Structural typing: accept anything with passed/score/detail attrs.
        payload = {
            "passed": bool(getattr(result, "passed")),
            "score": float(getattr(result, "score")),
            "detail": str(getattr(result, "detail")),
        }
        sys.stdout.write(json.dumps(payload))
        sys.stdout.flush()
        return 0
    except Exception as exc:  # noqa: BLE001 — surface everything to parent
        sys.stdout.write(json.dumps(_serialize_exception(exc)))
        sys.stdout.flush()
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
