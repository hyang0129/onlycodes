"""Hidden grader for algorithmic__makespan_scheduling.

Contract: ``grade(scratch_dir: Path) -> GradeResult``. See docs/SCHEMA_ARTIFACT.md §3.

Correctness criterion:

    The agent's output/schedule.json MUST contain a "makespan" key whose value
    equals the optimal makespan (integer, exact match). The actual assignment is
    also checked for feasibility (each job assigned exactly once, machine ids
    valid) but the grader computes optimality from the makespan value alone.

    Optimal makespan is computed by brute-force enumeration over all M^N
    assignments (N=10 jobs, M=3 machines → 59049 states — trivially fast).

Determinism: pure function of scratch_dir contents. No clock, no network.
"""
# GRADER-SENTINEL: 4cc6e89d-cc81-47d0-9e34-96d6ced97589

from __future__ import annotations

import itertools
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


INPUT_REL = "jobs.json"
OUTPUT_REL = "output/schedule.json"


def _load_input(scratch_dir: Path) -> tuple[int, list[int]] | None:
    p = scratch_dir / INPUT_REL
    if not p.is_file():
        return None
    data = json.loads(p.read_text())
    return data["num_machines"], data["job_durations"]


def _optimal_makespan(num_machines: int, job_durations: list[int]) -> int:
    best = sum(job_durations)  # worst case: all on one machine
    for assignment in itertools.product(range(num_machines), repeat=len(job_durations)):
        loads = [0] * num_machines
        for job, machine in enumerate(assignment):
            loads[machine] += job_durations[job]
        ms = max(loads)
        if ms < best:
            best = ms
    return best


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()

    inp = _load_input(scratch_dir)
    if inp is None:
        return GradeResult(False, 0.0, f"input {INPUT_REL} not found in scratch dir")
    num_machines, job_durations = inp

    output_path = scratch_dir / OUTPUT_REL
    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    try:
        agent_output = json.loads(output_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return GradeResult(False, 0.0, f"could not parse output JSON: {exc}")

    if not isinstance(agent_output, dict):
        return GradeResult(False, 0.0, "output must be a JSON object")

    if "makespan" not in agent_output:
        return GradeResult(False, 0.0, "output missing required key 'makespan'")

    agent_ms = agent_output["makespan"]
    if isinstance(agent_ms, bool) or not isinstance(agent_ms, (int, float)):
        return GradeResult(False, 0.0, f"makespan must be a number, got {type(agent_ms).__name__}")

    optimal = _optimal_makespan(num_machines, job_durations)

    if int(round(agent_ms)) != optimal:
        return GradeResult(
            False, 0.0,
            f"makespan {agent_ms} is not optimal (optimal={optimal})",
        )

    # Optional: validate assignment feasibility if provided
    if "assignment" in agent_output:
        assignment = agent_output["assignment"]
        if isinstance(assignment, list) and len(assignment) == num_machines:
            all_assigned = sorted(
                j for machine_jobs in assignment for j in machine_jobs
            )
            if all_assigned != list(range(len(job_durations))):
                return GradeResult(
                    False, 0.0,
                    "assignment is not a valid partition of all jobs",
                )
            loads = [
                sum(job_durations[j] for j in machine_jobs)
                for machine_jobs in assignment
            ]
            declared_ms = max(loads)
            if int(round(agent_ms)) != declared_ms:
                return GradeResult(
                    False, 0.0,
                    f"declared makespan {agent_ms} does not match computed "
                    f"makespan {declared_ms} from the assignment",
                )

    return GradeResult(True, 1.0, f"optimal makespan {optimal} achieved")
