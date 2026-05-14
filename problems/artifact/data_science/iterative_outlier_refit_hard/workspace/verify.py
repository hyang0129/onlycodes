"""Structural verifier for ``data_science__iterative_outlier_refit_hard``.

Checks ``output/result.json`` exists, parses as JSON, has exactly the five
required fields with the right types, and that ``outlier_indices`` is a
sorted list of non-negative integers and ``final_coefficients`` is a list
of exactly three numbers. Does NOT compare against the reference answer.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


REQUIRED_FIELDS = {
    "outlier_indices",
    "n_iterations",
    "final_intercept",
    "final_coefficients",
    "final_rmse",
}
_N_FEATURES = 3
_MAX_ITER = 50


def main(scratch_dir: str | None = None) -> None:
    base = Path(scratch_dir) if scratch_dir else Path(__file__).parent
    output_path = base / "output" / "result.json"

    if not output_path.is_file():
        print(f"FAIL: output artifact not found: {output_path}")
        sys.exit(1)

    try:
        data = json.loads(output_path.read_text())
    except json.JSONDecodeError as exc:
        print(f"FAIL: output is not valid JSON: {exc}")
        sys.exit(1)

    if not isinstance(data, dict):
        print(f"FAIL: top-level JSON must be an object; got {type(data).__name__}")
        sys.exit(1)

    keys = set(data.keys())
    missing = REQUIRED_FIELDS - keys
    extra = keys - REQUIRED_FIELDS
    errors: list[str] = []
    if missing:
        errors.append(f"missing required field(s): {sorted(missing)}")
    if extra:
        errors.append(f"unexpected extra field(s): {sorted(extra)}")

    if "outlier_indices" in data:
        oi = data["outlier_indices"]
        if not isinstance(oi, list) or not all(
            isinstance(x, int) and not isinstance(x, bool) for x in oi
        ):
            errors.append("outlier_indices must be a list of integers")
        else:
            if any(x < 0 for x in oi):
                errors.append("outlier_indices must contain non-negative values")
            if oi != sorted(oi):
                errors.append("outlier_indices must be sorted in ascending order")
            if len(set(oi)) != len(oi):
                errors.append("outlier_indices contains duplicates")

    if "n_iterations" in data:
        n = data["n_iterations"]
        if not isinstance(n, int) or isinstance(n, bool):
            errors.append(
                f"n_iterations must be an integer; got {type(n).__name__}"
            )
        elif n < 1 or n > _MAX_ITER:
            errors.append(f"n_iterations must be in [1, {_MAX_ITER}]; got {n}")

    if "final_intercept" in data and not isinstance(
        data["final_intercept"], (int, float)
    ):
        errors.append(
            f"final_intercept must be a number; got {type(data['final_intercept']).__name__}"
        )
    if "final_intercept" in data and isinstance(data["final_intercept"], bool):
        errors.append("final_intercept must be a number, not a bool")

    if "final_coefficients" in data:
        fc = data["final_coefficients"]
        if not isinstance(fc, list):
            errors.append("final_coefficients must be a list")
        elif len(fc) != _N_FEATURES:
            errors.append(
                f"final_coefficients must have exactly {_N_FEATURES} entries; got {len(fc)}"
            )
        elif not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in fc):
            errors.append("final_coefficients must contain only numbers")

    if "final_rmse" in data:
        r = data["final_rmse"]
        if not isinstance(r, (int, float)) or isinstance(r, bool):
            errors.append(f"final_rmse must be a number; got {type(r).__name__}")

    if errors:
        for err in errors:
            print(f"FAIL: {err}")
        sys.exit(1)

    print(
        f"OK: result.json has {len(data['outlier_indices'])} outlier(s), "
        f"n_iterations={data['n_iterations']}, "
        f"final_rmse={data['final_rmse']}"
    )
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
