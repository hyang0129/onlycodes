"""Hidden grader for ``data_science__expanding_percentile_multimetric_hard``.

Recomputes expanding-window p50/p90/p99 snapshots for three metrics at
four checkpoints from ``scratch_dir/metrics.csv`` and compares the
agent's ``output/result.json`` field-by-field. All-or-nothing scoring.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


INPUT_CSV = "metrics.csv"
OUTPUT_REL = "output/result.json"
REQUIRED_TOP = {"checkpoints"}
REQUIRED_CHECKPOINT = {"t", "n_observations", "metrics"}
REQUIRED_METRIC = {"metric", "p50", "p90", "p99"}
EXPECTED_CHECKPOINTS = [49, 99, 149, 199]
EXPECTED_METRIC_NAMES = ["metric_a", "metric_b", "metric_c"]
PCT_TOL = 0.01


def _compute_expected(scratch_dir: Path) -> list[dict]:
    df = pd.read_csv(scratch_dir / INPUT_CSV).sort_values("t").reset_index(drop=True)
    checkpoints = []
    for T in EXPECTED_CHECKPOINTS:
        sub = df[df["t"] <= T]
        metrics_block = []
        for name in EXPECTED_METRIC_NAMES:
            arr = sub[name].to_numpy()
            metrics_block.append(
                {
                    "metric": name,
                    "p50": float(np.quantile(arr, 0.50)),
                    "p90": float(np.quantile(arr, 0.90)),
                    "p99": float(np.quantile(arr, 0.99)),
                }
            )
        checkpoints.append(
            {
                "t": int(T),
                "n_observations": int(T + 1),
                "metrics": metrics_block,
            }
        )
    return checkpoints


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()
    output_path = scratch_dir / OUTPUT_REL

    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    try:
        data = json.loads(output_path.read_text())
    except json.JSONDecodeError as exc:
        return GradeResult(False, 0.0, f"output is not valid JSON: {exc}")

    if not isinstance(data, dict):
        return GradeResult(
            False, 0.0, f"top-level JSON must be an object; got {type(data).__name__}"
        )

    keys = set(data.keys())
    missing = REQUIRED_TOP - keys
    extra = keys - REQUIRED_TOP
    if missing:
        return GradeResult(False, 0.0, f"missing top-level field(s): {sorted(missing)}")
    if extra:
        return GradeResult(False, 0.0, f"unexpected top-level field(s): {sorted(extra)}")

    cps = data["checkpoints"]
    if not isinstance(cps, list):
        return GradeResult(False, 0.0, "checkpoints must be a list")
    ts: list[int] = []
    for i, entry in enumerate(cps):
        if not isinstance(entry, dict):
            return GradeResult(False, 0.0, f"checkpoints[{i}] must be an object")
        ek = set(entry.keys())
        if ek != REQUIRED_CHECKPOINT:
            return GradeResult(
                False, 0.0,
                f"checkpoints[{i}] keys {sorted(ek)} != {sorted(REQUIRED_CHECKPOINT)}",
            )
        if not isinstance(entry["t"], int) or isinstance(entry["t"], bool):
            return GradeResult(False, 0.0, f"checkpoints[{i}].t must be a non-bool integer")
        ts.append(entry["t"])
        if not isinstance(entry["n_observations"], int) or isinstance(entry["n_observations"], bool):
            return GradeResult(
                False, 0.0, f"checkpoints[{i}].n_observations must be a non-bool integer"
            )
        mets = entry["metrics"]
        if not isinstance(mets, list):
            return GradeResult(False, 0.0, f"checkpoints[{i}].metrics must be a list")
        mnames: list[str] = []
        for j, m in enumerate(mets):
            if not isinstance(m, dict):
                return GradeResult(False, 0.0, f"checkpoints[{i}].metrics[{j}] must be an object")
            mk = set(m.keys())
            if mk != REQUIRED_METRIC:
                return GradeResult(
                    False, 0.0,
                    f"checkpoints[{i}].metrics[{j}] keys {sorted(mk)} != {sorted(REQUIRED_METRIC)}",
                )
            if not isinstance(m["metric"], str):
                return GradeResult(False, 0.0, f"checkpoints[{i}].metrics[{j}].metric must be a string")
            mnames.append(m["metric"])
            for pf in ("p50", "p90", "p99"):
                pv = m[pf]
                if not isinstance(pv, (int, float)) or isinstance(pv, bool):
                    return GradeResult(False, 0.0, f"checkpoints[{i}].metrics[{j}].{pf} must be a number")
        if mnames != sorted(mnames):
            return GradeResult(
                False, 0.0, f"checkpoints[{i}].metrics must be sorted ascending by metric name"
            )
        if len(set(mnames)) != len(mnames):
            return GradeResult(False, 0.0, f"checkpoints[{i}].metrics has duplicate metric names")

    if ts != sorted(ts):
        return GradeResult(False, 0.0, "checkpoints must be sorted ascending by t")
    if len(set(ts)) != len(ts):
        return GradeResult(False, 0.0, "checkpoints has duplicate t values")

    expected = _compute_expected(scratch_dir)
    exp_ts = [e["t"] for e in expected]
    if ts != exp_ts:
        got = set(ts)
        ref = set(exp_ts)
        missing_t = sorted(ref - got)
        extra_t = sorted(got - ref)
        bits: list[str] = []
        if missing_t:
            bits.append(f"missing checkpoint(s): {missing_t}")
        if extra_t:
            bits.append(f"unexpected checkpoint(s): {extra_t}")
        if not bits:
            bits.append(f"checkpoint t set must be exactly {EXPECTED_CHECKPOINTS} in ascending order")
        return GradeResult(False, 0.0, "checkpoint t set mismatch: " + "; ".join(bits))

    for got_cp, exp_cp in zip(cps, expected):
        T = exp_cp["t"]
        if got_cp["n_observations"] != exp_cp["n_observations"]:
            return GradeResult(
                False, 0.0,
                f"checkpoints[t={T}].n_observations mismatch: got {got_cp['n_observations']}, "
                f"expected {exp_cp['n_observations']} (= T + 1 for expanding window through T inclusive)",
            )
        got_mnames = [m["metric"] for m in got_cp["metrics"]]
        exp_mnames = [m["metric"] for m in exp_cp["metrics"]]
        if got_mnames != exp_mnames:
            got = set(got_mnames)
            ref = set(exp_mnames)
            missing_m = sorted(ref - got)
            extra_m = sorted(got - ref)
            bits: list[str] = []
            if missing_m:
                bits.append(f"missing metric(s): {missing_m}")
            if extra_m:
                bits.append(f"unexpected metric(s): {extra_m}")
            if not bits:
                bits.append(f"metric order must be {EXPECTED_METRIC_NAMES}")
            return GradeResult(
                False, 0.0,
                f"checkpoints[t={T}] metric set mismatch: " + "; ".join(bits),
            )
        for got_m, exp_m in zip(got_cp["metrics"], exp_cp["metrics"]):
            mname = exp_m["metric"]
            for pf in ("p50", "p90", "p99"):
                if abs(float(got_m[pf]) - exp_m[pf]) > PCT_TOL:
                    return GradeResult(
                        False, 0.0,
                        f"checkpoints[t={T}].metrics[{mname}].{pf} off by more than "
                        f"{PCT_TOL} from the expanding-window value over rows t<={T} "
                        "(check: linear-interpolation quantile on the per-metric column only)",
                    )

    return GradeResult(
        True,
        1.0,
        f"all {len(expected)} expanding-window checkpoints × {len(EXPECTED_METRIC_NAMES)} "
        f"metrics × 3 percentiles within ±{PCT_TOL}",
    )
