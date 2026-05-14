#!/usr/bin/env python3
"""Workspace generator for ``ml_engineering__find_broken_runs_*``.

Emits N training-run logs as JSONL files under ``runs/``. Each healthy run
contains a start event, per-step metric lines, and a final ``done`` event.
A small subset of runs are corrupted with one of three failure signatures:

  * ``nan``       — a mid-run metric line contains a bareword ``NaN`` value;
                    the file ends after that line with no ``done`` event.
  * ``truncated`` — the file ends mid-record (unparseable last line); no
                    ``done`` event.
  * ``diverged``  — the last ~30 step lines show monotonically increasing
                    val_loss climbing above 1e3 while remaining finite; no
                    ``done`` event.

Difficulty parameters (selected by ``--instance-id``):

  * ``find_broken_runs_easy``   — N=50,  failures = {nan: 5}
  * ``find_broken_runs_medium`` — N=200, failures = {nan: 6, truncated: 4}
  * ``find_broken_runs_hard``   — N=500, failures = {nan: 10, truncated: 8, diverged: 7}

The script is invoked by the harness with ``--seed``, ``--output-dir``,
and ``--instance-id``. It is also runnable standalone for reference
generation. The mapping from ``(seed, instance_id)`` to corruption layout
is fully deterministic.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path
from typing import Dict, List, Tuple


# (N_runs, failures_by_mode) per slug
_DIFFICULTY: Dict[str, Tuple[int, Dict[str, int]]] = {
    "find_broken_runs_easy":   (50,  {"nan": 5}),
    "find_broken_runs_medium": (200, {"nan": 6, "truncated": 4}),
    "find_broken_runs_hard":   (500, {"nan": 10, "truncated": 8, "diverged": 7}),
}


def _slug_from_instance_id(instance_id: str) -> str:
    # instance_id = "ml_engineering__<slug>"
    parts = instance_id.split("__", 1)
    return parts[1] if len(parts) == 2 else instance_id


def _decide_corruption_plan(
    n_runs: int,
    failures: Dict[str, int],
    rng: random.Random,
) -> Dict[int, str]:
    """Pick which run indices are broken and which mode each one is.

    Returns a dict mapping run_index -> mode. Run indices not present are healthy.
    Selection is reproducible from the provided RNG.
    """
    total_broken = sum(failures.values())
    if total_broken > n_runs:
        raise ValueError(f"too many failures ({total_broken}) for n_runs={n_runs}")
    chosen = rng.sample(range(n_runs), total_broken)
    plan: Dict[int, str] = {}
    cursor = 0
    for mode, count in failures.items():
        for idx in chosen[cursor:cursor + count]:
            plan[idx] = mode
        cursor += count
    return plan


def _healthy_trajectory(
    rng: random.Random,
    total_steps: int,
) -> List[Tuple[int, float, float]]:
    """Return a list of (step, train_loss, val_loss) for a healthy run."""
    # Exponential decay from a start loss in [3.0, 5.0] toward a floor in
    # [0.30, 0.80], with small per-step noise. val_loss is train_loss
    # plus a small positive offset that grows mildly late in training.
    start = rng.uniform(3.0, 5.0)
    floor = rng.uniform(0.30, 0.80)
    decay = rng.uniform(0.0035, 0.0070)
    out: List[Tuple[int, float, float]] = []
    for s in range(1, total_steps + 1):
        base = floor + (start - floor) * math.exp(-decay * s)
        train_noise = rng.gauss(0.0, 0.02)
        val_offset = 0.08 + 0.0001 * s
        val_noise = rng.gauss(0.0, 0.03)
        train_loss = max(0.01, base + train_noise)
        val_loss = max(0.02, base + val_offset + val_noise)
        out.append((s, round(train_loss, 4), round(val_loss, 4)))
    return out


def _write_healthy(path: Path, run_id: str, rng: random.Random) -> None:
    total_steps = rng.randrange(200, 1001)
    traj = _healthy_trajectory(rng, total_steps)
    with open(path, "w") as fh:
        fh.write(json.dumps({
            "event": "start",
            "run_id": run_id,
            "total_steps": total_steps,
            "lr": round(rng.uniform(1e-5, 1e-3), 6),
        }) + "\n")
        for step, tl, vl in traj:
            fh.write(json.dumps({
                "step": step,
                "train_loss": tl,
                "val_loss": vl,
            }) + "\n")
        fh.write(json.dumps({"event": "done", "run_id": run_id}) + "\n")


def _write_nan(path: Path, run_id: str, rng: random.Random) -> None:
    """A NaN value appears mid-run; file ends after that line; no `done`."""
    total_steps = rng.randrange(200, 1001)
    traj = _healthy_trajectory(rng, total_steps)
    # Crash somewhere in the middle 50% of the run.
    crash_idx = rng.randrange(max(1, total_steps // 4), max(2, 3 * total_steps // 4))
    with open(path, "w") as fh:
        fh.write(json.dumps({
            "event": "start",
            "run_id": run_id,
            "total_steps": total_steps,
            "lr": round(rng.uniform(1e-5, 1e-3), 6),
        }) + "\n")
        for i, (step, tl, vl) in enumerate(traj[:crash_idx]):
            fh.write(json.dumps({
                "step": step,
                "train_loss": tl,
                "val_loss": vl,
            }) + "\n")
        # NaN line: Python's default json.dumps emits the bareword `NaN`
        # for float('nan'), matching what real frameworks like PyTorch
        # Lightning's CSVLogger emit when loss explodes.
        nan_metric = "train_loss" if rng.random() < 0.5 else "val_loss"
        nan_obj = {
            "step": traj[crash_idx][0],
            "train_loss": float("nan") if nan_metric == "train_loss" else traj[crash_idx][1],
            "val_loss": float("nan") if nan_metric == "val_loss" else traj[crash_idx][2],
        }
        fh.write(json.dumps(nan_obj) + "\n")


def _write_truncated(path: Path, run_id: str, rng: random.Random) -> None:
    """Last line is unparseable JSON (cut mid-record); no `done`."""
    total_steps = rng.randrange(200, 1001)
    traj = _healthy_trajectory(rng, total_steps)
    cutoff_idx = rng.randrange(max(2, total_steps // 4), max(3, 3 * total_steps // 4))
    with open(path, "w") as fh:
        fh.write(json.dumps({
            "event": "start",
            "run_id": run_id,
            "total_steps": total_steps,
            "lr": round(rng.uniform(1e-5, 1e-3), 6),
        }) + "\n")
        for step, tl, vl in traj[:cutoff_idx]:
            fh.write(json.dumps({
                "step": step,
                "train_loss": tl,
                "val_loss": vl,
            }) + "\n")
        # Begin one more record, but truncate it mid-key/value (no newline).
        partial_step = traj[cutoff_idx][0]
        partial_train = traj[cutoff_idx][1]
        # Drop the closing brace and val_loss field. No trailing newline.
        partial = f'{{"step": {partial_step}, "train_loss": {partial_train}, "val_lo'
        fh.write(partial)


def _write_diverged(path: Path, run_id: str, rng: random.Random) -> None:
    """Last ~30 step lines climb monotonically above 1e3; finite; no `done`."""
    total_steps = rng.randrange(300, 1001)
    traj = _healthy_trajectory(rng, total_steps)
    # Replace the trailing window with a divergence ramp.
    ramp_len = rng.randrange(25, 41)
    if ramp_len >= total_steps:
        ramp_len = total_steps - 1
    # Build a monotonically increasing tail that ends well above 1e3.
    start_loss = traj[-ramp_len - 1][2] if total_steps > ramp_len else 1.0
    end_loss = rng.uniform(1.5e3, 9.0e3)
    step_increment = (end_loss - start_loss) / ramp_len
    diverged_tail: List[Tuple[int, float, float]] = []
    for k in range(ramp_len):
        step = traj[total_steps - ramp_len + k][0]
        # train_loss climbs too but slightly behind val_loss.
        val_loss = round(start_loss + step_increment * (k + 1), 4)
        train_loss = round(val_loss * rng.uniform(0.85, 0.95), 4)
        diverged_tail.append((step, train_loss, val_loss))
    final = traj[:total_steps - ramp_len] + diverged_tail
    with open(path, "w") as fh:
        fh.write(json.dumps({
            "event": "start",
            "run_id": run_id,
            "total_steps": total_steps,
            "lr": round(rng.uniform(1e-5, 1e-3), 6),
        }) + "\n")
        for step, tl, vl in final:
            fh.write(json.dumps({
                "step": step,
                "train_loss": tl,
                "val_loss": vl,
            }) + "\n")


_WRITERS = {
    "nan": _write_nan,
    "truncated": _write_truncated,
    "diverged": _write_diverged,
}


def generate(output_dir: Path, seed: int, instance_id: str) -> None:
    slug = _slug_from_instance_id(instance_id)
    if slug not in _DIFFICULTY:
        raise ValueError(f"unknown slug {slug!r}; expected one of {list(_DIFFICULTY)}")
    n_runs, failures = _DIFFICULTY[slug]

    runs_dir = output_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    # Use one master RNG to decide which indices are broken and which mode.
    master = random.Random(seed)
    plan = _decide_corruption_plan(n_runs, failures, master)

    # Each run gets its own RNG so per-run noise doesn't depend on order.
    for idx in range(n_runs):
        run_id = f"run_{idx:04d}"
        # Derive a per-run seed deterministically from (seed, idx).
        run_rng = random.Random((seed * 1_000_003) ^ (idx * 2_654_435_761) & 0xFFFFFFFF)
        path = runs_dir / f"{run_id}.jsonl"
        mode = plan.get(idx)
        if mode is None:
            _write_healthy(path, run_id, run_rng)
        else:
            _WRITERS[mode](path, run_id, run_rng)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--instance-id", type=str, required=True)
    args = ap.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    generate(args.output_dir, args.seed, args.instance_id)


if __name__ == "__main__":
    main()
