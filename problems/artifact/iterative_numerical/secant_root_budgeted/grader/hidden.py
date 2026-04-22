"""Hidden grader for iterative_numerical__secant_root_budgeted.

Contract: ``grade(scratch_dir: Path) -> GradeResult``. See docs/SCHEMA_ARTIFACT.md §3.

Correctness criterion:

    For each bracket entry (name, a, b) in brackets.json, output/roots.json
    must contain x = roots[name] with:
      - x finite, a <= x <= b
      - |f(x)| < TOLERANCE, where f = getattr(black_box, name) and
        black_box is loaded from scratch_dir/black_box.py.

Determinism: pure function of scratch_dir contents; black_box uses
stdlib math only and is deterministic.
"""

from __future__ import annotations

import importlib.util
import json
import math
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


BRACKETS_REL = "brackets.json"
OUTPUT_REL = "output/roots.json"
TOLERANCE = 1e-8


def _load_black_box(scratch_dir: Path):
    spec = importlib.util.spec_from_file_location(
        "black_box_secant", scratch_dir / "black_box.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()

    brackets_path = scratch_dir / BRACKETS_REL
    if not brackets_path.is_file():
        return GradeResult(False, 0.0, f"input {BRACKETS_REL} not found in scratch dir")

    try:
        brackets = json.loads(brackets_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return GradeResult(False, 0.0, f"could not parse brackets.json: {exc}")

    output_path = scratch_dir / OUTPUT_REL
    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    try:
        agent_output = json.loads(output_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return GradeResult(False, 0.0, f"could not parse output JSON: {exc}")

    if not isinstance(agent_output, dict):
        return GradeResult(False, 0.0, "output must be a JSON object")

    try:
        bb = _load_black_box(scratch_dir)
    except Exception as exc:
        return GradeResult(False, 0.0, f"could not import black_box.py: {exc}")

    worst_name = None
    worst_abs = 0.0
    for entry in brackets:
        name = entry["name"]
        a, b = float(entry["a"]), float(entry["b"])
        if name not in agent_output:
            return GradeResult(False, 0.0, f"output missing root for {name!r}")
        v = agent_output[name]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return GradeResult(False, 0.0, f"'{name}' must be a number")
        if not math.isfinite(v):
            return GradeResult(False, 0.0, f"'{name}' must be finite")
        x = float(v)
        if not (a <= x <= b):
            return GradeResult(False, 0.0, f"'{name}'={x} outside bracket [{a},{b}]")
        try:
            fx = getattr(bb, name)(x)
        except Exception as exc:
            return GradeResult(False, 0.0, f"error evaluating {name}({x}): {exc}")
        if not math.isfinite(fx):
            return GradeResult(False, 0.0, f"{name}({x}) is not finite")
        if abs(fx) > worst_abs:
            worst_abs = abs(fx)
            worst_name = name

    if worst_abs >= TOLERANCE:
        return GradeResult(
            False, 0.0,
            f"max |f(x)| = {worst_abs:.2e} >= tol {TOLERANCE:.0e} "
            f"(worst: {worst_name})",
        )

    return GradeResult(
        True, 1.0,
        f"all {len(brackets)} roots within tol {TOLERANCE:.0e} "
        f"(max |f(x)| = {worst_abs:.2e})",
    )
