"""Hidden grader for iterative_numerical__gradient_descent_rosenbrock.

Contract: ``grade(scratch_dir: Path) -> GradeResult``. See docs/SCHEMA_ARTIFACT.md §3.

Correctness criterion:

    output/minimum.json gives (x, y) such that the Rosenbrock function
        f(x, y) = (a - x)^2 + b * (y - x^2)^2
    evaluated at (x, y) (with a, b from problem.json) is strictly below
    F_THRESHOLD (1e-6). The 'f' field in the output is informational:
    the grader recomputes f from (x, y).

Determinism: pure arithmetic on scratch_dir contents.
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


INPUT_REL = "problem.json"
OUTPUT_REL = "output/minimum.json"
F_THRESHOLD = 1e-6


def _rosen(a: float, b: float, x: float, y: float) -> float:
    return (a - x) ** 2 + b * (y - x * x) ** 2


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()

    input_path = scratch_dir / INPUT_REL
    if not input_path.is_file():
        return GradeResult(False, 0.0, f"input {INPUT_REL} not found in scratch dir")

    try:
        problem = json.loads(input_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return GradeResult(False, 0.0, f"could not parse problem.json: {exc}")

    a = float(problem["a"])
    b = float(problem["b"])

    output_path = scratch_dir / OUTPUT_REL
    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    try:
        agent_output = json.loads(output_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return GradeResult(False, 0.0, f"could not parse output JSON: {exc}")

    if not isinstance(agent_output, dict):
        return GradeResult(False, 0.0, "output must be a JSON object")

    for key in ("x", "y"):
        if key not in agent_output:
            return GradeResult(False, 0.0, f"output missing required key '{key}'")
        v = agent_output[key]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return GradeResult(False, 0.0, f"'{key}' must be a number, got {type(v).__name__}")
        if not math.isfinite(v):
            return GradeResult(False, 0.0, f"'{key}' must be finite, got {v}")

    x = float(agent_output["x"])
    y = float(agent_output["y"])

    actual_f = _rosen(a, b, x, y)
    if not math.isfinite(actual_f):
        return GradeResult(False, 0.0, f"f(x={x}, y={y}) is not finite")

    if actual_f >= F_THRESHOLD:
        return GradeResult(
            False, 0.0,
            f"f(x={x:.6g}, y={y:.6g}) = {actual_f:.3e} >= threshold {F_THRESHOLD:.0e}",
        )

    return GradeResult(
        True, 1.0,
        f"f(x={x:.6g}, y={y:.6g}) = {actual_f:.3e} < threshold {F_THRESHOLD:.0e}",
    )
