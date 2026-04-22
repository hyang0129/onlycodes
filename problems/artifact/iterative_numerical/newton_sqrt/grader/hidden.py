"""Hidden grader for iterative_numerical__newton_sqrt.

Contract: ``grade(scratch_dir: Path) -> GradeResult``. See docs/SCHEMA_ARTIFACT.md §3.

Correctness criterion:

    For each (id, x) pair in inputs.json, the agent's output/roots.json must
    contain a numeric value y such that |y - sqrt(x)| <= TOLERANCE.

Determinism: pure function of scratch_dir contents.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


INPUT_REL = "inputs.json"
OUTPUT_REL = "output/roots.json"
TOLERANCE = 1e-8


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()

    input_path = scratch_dir / INPUT_REL
    if not input_path.is_file():
        return GradeResult(False, 0.0, f"input {INPUT_REL} not found in scratch dir")

    try:
        inputs = json.loads(input_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return GradeResult(False, 0.0, f"could not parse inputs.json: {exc}")

    output_path = scratch_dir / OUTPUT_REL
    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    try:
        agent_output = json.loads(output_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return GradeResult(False, 0.0, f"could not parse output JSON: {exc}")

    if not isinstance(agent_output, dict):
        return GradeResult(False, 0.0, "output must be a JSON object")

    total = len(inputs)
    max_err = 0.0
    worst_id = None
    for k, x in inputs.items():
        if k not in agent_output:
            return GradeResult(False, 0.0, f"output missing id {k!r}")
        v = agent_output[k]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return GradeResult(False, 0.0, f"value for {k!r} must be numeric")
        if not math.isfinite(v):
            return GradeResult(False, 0.0, f"value for {k!r} must be finite")
        if v < 0.0:
            return GradeResult(False, 0.0, f"value for {k!r} must be non-negative")
        expected = math.sqrt(float(x))
        err = abs(float(v) - expected)
        if err > max_err:
            max_err = err
            worst_id = k

    if max_err > TOLERANCE:
        return GradeResult(
            False, 0.0,
            f"max abs error {max_err:.2e} > tol {TOLERANCE:.0e} "
            f"(worst id {worst_id!r})",
        )

    return GradeResult(
        True, 1.0,
        f"all {total} roots within tol {TOLERANCE:.0e} (max err {max_err:.2e})",
    )
