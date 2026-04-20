"""Hidden grader for iterative_numerical__bisection_calibration."""
from __future__ import annotations
import json
import importlib.util
import math
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


OUTPUT_REL = "output/result.json"
TOLERANCE = 1e-6


def _load_f(scratch_dir: Path):
    spec = importlib.util.spec_from_file_location(
        "black_box", scratch_dir / "black_box.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.f


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()
    output_path = scratch_dir / OUTPUT_REL

    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    try:
        agent_out = json.loads(output_path.read_text())
    except Exception as exc:
        return GradeResult(False, 0.0, f"could not parse output: {exc}")

    if not isinstance(agent_out, dict):
        return GradeResult(False, 0.0, "output must be a JSON object")

    for key in ("x_star", "f_x_star", "evaluations"):
        if key not in agent_out:
            return GradeResult(False, 0.0, f"missing key '{key}'")

    x_star = float(agent_out["x_star"])
    if not (0.0 <= x_star <= 100.0):
        return GradeResult(False, 0.0, f"x_star={x_star} not in [0, 100]")

    try:
        f = _load_f(scratch_dir)
        actual_f = f(x_star)
    except Exception as exc:
        return GradeResult(False, 0.0, f"could not evaluate f(x_star): {exc}")

    if abs(actual_f) >= TOLERANCE:
        return GradeResult(
            False,
            round(1 - min(1.0, abs(actual_f) / 1.0), 4),
            f"|f({x_star:.6f})| = {abs(actual_f):.2e} >= {TOLERANCE:.0e}",
        )

    evals = agent_out["evaluations"]
    return GradeResult(
        True,
        1.0,
        f"|f({x_star:.6f})| = {abs(actual_f):.2e} < {TOLERANCE:.0e} (reported {evals} evaluations)",
    )
