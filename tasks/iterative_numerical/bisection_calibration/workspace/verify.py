"""Structural verifier for iterative_numerical__bisection_calibration."""
from __future__ import annotations
import json
import sys
from pathlib import Path


def verify(scratch_dir: str | Path) -> tuple[bool, str]:
    scratch_dir = Path(scratch_dir).resolve()
    output_path = scratch_dir / "output" / "result.json"

    if not output_path.is_file():
        return False, f"output artifact not found: {output_path}"

    try:
        data = json.loads(output_path.read_text())
    except Exception as exc:
        return False, f"could not parse output/result.json as JSON: {exc}"

    if not isinstance(data, dict):
        return False, "output/result.json must be a JSON object"

    # Check required keys and types
    if "x_star" not in data:
        return False, "missing key 'x_star'"
    if "f_x_star" not in data:
        return False, "missing key 'f_x_star'"
    if "evaluations" not in data:
        return False, "missing key 'evaluations'"

    try:
        x_star = float(data["x_star"])
    except (TypeError, ValueError):
        return False, f"'x_star' must be a number, got {data['x_star']!r}"

    try:
        float(data["f_x_star"])
    except (TypeError, ValueError):
        return False, f"'f_x_star' must be a number, got {data['f_x_star']!r}"

    try:
        evals = int(data["evaluations"])
        if evals < 0:
            return False, f"'evaluations' must be a non-negative integer, got {evals}"
    except (TypeError, ValueError):
        return False, f"'evaluations' must be an integer, got {data['evaluations']!r}"

    if not (0.0 <= x_star <= 100.0):
        return False, f"'x_star' = {x_star} is not in [0, 100]"

    return True, "structural check passed"


if __name__ == "__main__":
    scratch = sys.argv[1] if len(sys.argv) > 1 else "."
    ok, msg = verify(scratch)
    print(msg)
    sys.exit(0 if ok else 1)
