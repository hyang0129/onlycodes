"""Structural verifier for ``data_science__expanding_percentile_multimetric_hard``.

Checks ``output/result.json`` exists, parses as JSON, has the right
top-level shape, and that ``checkpoints`` / ``metrics`` entries are
well-formed and sorted. Does NOT compare against the reference answer.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


REQUIRED_TOP = {"checkpoints"}
REQUIRED_CHECKPOINT = {"t", "n_observations", "metrics"}
REQUIRED_METRIC = {"metric", "p50", "p90", "p99"}
EXPECTED_CHECKPOINTS = [49, 99, 149, 199]
EXPECTED_METRIC_NAMES = ["metric_a", "metric_b", "metric_c"]


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
    missing = REQUIRED_TOP - keys
    extra = keys - REQUIRED_TOP
    errors: list[str] = []
    if missing:
        errors.append(f"missing top-level field(s): {sorted(missing)}")
    if extra:
        errors.append(f"unexpected top-level field(s): {sorted(extra)}")

    cps = data.get("checkpoints")
    if not isinstance(cps, list):
        errors.append("checkpoints must be a list")
    else:
        ts: list[int] = []
        for i, entry in enumerate(cps):
            if not isinstance(entry, dict):
                errors.append(f"checkpoints[{i}] must be an object")
                continue
            ek = set(entry.keys())
            if ek != REQUIRED_CHECKPOINT:
                errors.append(
                    f"checkpoints[{i}] keys {sorted(ek)} != {sorted(REQUIRED_CHECKPOINT)}"
                )
                continue
            t = entry["t"]
            if not isinstance(t, int) or isinstance(t, bool):
                errors.append(f"checkpoints[{i}].t must be a non-bool integer")
            else:
                ts.append(t)
            n_obs = entry["n_observations"]
            if not isinstance(n_obs, int) or isinstance(n_obs, bool):
                errors.append(f"checkpoints[{i}].n_observations must be a non-bool integer")
            mets = entry.get("metrics")
            if not isinstance(mets, list):
                errors.append(f"checkpoints[{i}].metrics must be a list")
                continue
            mnames: list[str] = []
            for j, m in enumerate(mets):
                if not isinstance(m, dict):
                    errors.append(f"checkpoints[{i}].metrics[{j}] must be an object")
                    continue
                mk = set(m.keys())
                if mk != REQUIRED_METRIC:
                    errors.append(
                        f"checkpoints[{i}].metrics[{j}] keys {sorted(mk)} != {sorted(REQUIRED_METRIC)}"
                    )
                    continue
                if not isinstance(m["metric"], str):
                    errors.append(f"checkpoints[{i}].metrics[{j}].metric must be a string")
                else:
                    mnames.append(m["metric"])
                for pf in ("p50", "p90", "p99"):
                    pv = m[pf]
                    if not isinstance(pv, (int, float)) or isinstance(pv, bool):
                        errors.append(f"checkpoints[{i}].metrics[{j}].{pf} must be a number")
            if mnames != sorted(mnames):
                errors.append(f"checkpoints[{i}].metrics must be sorted ascending by metric name")
            if len(set(mnames)) != len(mnames):
                errors.append(f"checkpoints[{i}].metrics has duplicate metric names")
        if ts != sorted(ts):
            errors.append("checkpoints must be sorted ascending by t")
        if len(set(ts)) != len(ts):
            errors.append("checkpoints has duplicate t values")

    if errors:
        for err in errors:
            print(f"FAIL: {err}")
        sys.exit(1)

    print(f"OK: result.json has {len(data['checkpoints'])} checkpoint(s)")
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
