"""Arm executor for artifact-graded benchmark tasks.

Orchestrates a single (task, arm, run) triple end-to-end:

1. Materialise workspace into scratch dir (no-leak invariant enforced).
2. Build prompt from ``prompt.md``.
3. Invoke the agent via runner.invoke() with cwd=scratch_dir.
4. Invoke the grader on the populated scratch dir.
5. Write ``result.json`` + ``agent.jsonl``.

Mirrors the matched-arm pattern from ``swebench.run._run_arm`` but with
artifact primitives. Does NOT import ``swebench.cache``.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Callable

from swebench.artifact_grade import GraderInvocationError, invoke_grader
from swebench.artifact_materialize import materialize, scratch_dir_for
from swebench.artifact_models import ArtifactArmResult, GradeResult, Task
from swebench.runner import AgentRunner, ClaudeRunner

ARMS = ("code_only", "tool_rich", "bash_only")


def run_dir_for(results_dir: Path, instance_id: str, arm: str, run_idx: int) -> Path:
    """Canonical directory for a single (instance, arm, run) triple."""
    return results_dir / instance_id / arm / f"run{run_idx}"


def _build_prompt(task: Task, scratch_dir: Path, arm: str) -> str:
    """Compose the agent prompt from ``prompt.md`` plus scratch-dir context."""
    if task.task_dir is None:
        raise ValueError(f"Task {task.instance_id!r} has no task_dir attached")
    prompt_path = task.task_dir / task.problem_statement
    if not prompt_path.is_file():
        raise FileNotFoundError(f"problem_statement not found: {prompt_path}")
    prompt_body = prompt_path.read_text()

    # Use absolute paths so the agent does not need to thread cwd through
    # every code-execution call. The tool_rich arm's Bash inherits cwd from
    # the subprocess, but code_only routes through MCP execute_code which
    # defaults to a fresh tmpdir when the agent omits the cwd= param.
    # Absolute paths remove the ambiguity for both arms.
    scratch_abs = scratch_dir.resolve()
    output_abs = scratch_abs / task.output_artifact
    parts = [
        f"Your input files are under the absolute path: {scratch_abs}",
        f"Write your output artifact to the absolute path: {output_abs}",
        "",
        prompt_body,
    ]
    return "\n".join(parts)


def _log_budget(task: Task, echo: Callable[[str], None]) -> None:
    b = task.execution_budget
    if b.is_unlimited:
        echo(f"  [{task.instance_id}] budget enforcement OFF (0 = unlimited)")
    else:
        echo(
            f"  [{task.instance_id}] budget declared: "
            f"max_code_runs={b.max_code_runs}, "
            f"max_wall_seconds={b.max_wall_seconds} "
            f"(enforcement OFF — future epic)"
        )


def is_run_complete(run_dir: Path) -> bool:
    """Return True if ``run_dir/result.json`` exists with a valid verdict."""
    result_path = run_dir / "result.json"
    if not result_path.is_file():
        return False
    try:
        data = json.loads(result_path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    return data.get("verdict") in ("PASS", "FAIL")


def run_artifact_arm(
    task: Task,
    arm: str,
    run_idx: int,
    *,
    results_dir: Path,
    runner: AgentRunner | None = None,
    # Legacy param kept for callers not yet migrated to runner= keyword.
    claude_binary: str | None = None,
    mcp_config_path: str | None = None,
    echo: Callable[[str], None] | None = None,
    wall_timeout_seconds: int = 3600,
) -> ArtifactArmResult:
    """Run one (task, arm, run_idx) triple and write result.json + agent.jsonl.

    Returns the ``ArtifactArmResult`` (also serialised to disk).

    Pass ``runner`` to select the agent surface. ``claude_binary`` is accepted
    for backward compatibility and implies ``ClaudeRunner`` when runner= is
    omitted; it is ignored when runner= is provided.
    """
    if runner is None:
        runner = ClaudeRunner()
    if arm not in ARMS:
        raise ValueError(f"arm must be one of {ARMS}, got {arm!r}")
    if echo is None:
        echo = print

    binary = claude_binary or runner.find_binary()

    run_dir = run_dir_for(results_dir, task.instance_id, arm, run_idx)
    run_dir.mkdir(parents=True, exist_ok=True)
    scratch_dir = scratch_dir_for(results_dir, task.instance_id, arm, run_idx)

    agent_jsonl = run_dir / "agent.jsonl"
    result_json = run_dir / "result.json"

    echo(f"  [{task.instance_id} {arm} run{run_idx}] Materializing workspace...")
    materialize(task, scratch_dir)
    _log_budget(task, echo)

    agent_version = runner.get_version(binary)
    with open(agent_jsonl, "w") as f:
        f.write(json.dumps({
            "type": "meta",
            "mode": "artifact",
            "instance_id": task.instance_id,
            "arm": arm,
            "run": run_idx,
            "agent_surface": runner.surface,
            "agent_binary": binary,
            "agent_version": agent_version,
        }) + "\n")

    prompt = _build_prompt(task, scratch_dir, arm)
    tools_flags = runner.build_tools_flags(arm, mcp_config_path)

    # TODO(budget): increment code_run counter here — enforcement is OFF.
    # The hook is intentionally a no-op in seed-v1 per the STRONG invariant:
    # declare + store fields now, flip enforcement in a later epic.

    start = time.time()
    verdict: str
    grade_result: GradeResult | None = None
    try:
        runner.invoke(
            prompt=prompt,
            cwd=str(scratch_dir),
            system_prompt="You are a helpful assistant.",
            tools_flags=tools_flags,
            result_file=str(agent_jsonl),
            binary=binary,
            mcp_config_path=mcp_config_path,
            wall_timeout_seconds=wall_timeout_seconds,
        )
        wall_secs = int(time.time() - start)
        echo(f"  [{task.instance_id} {arm} run{run_idx}] Grading...")
        try:
            grade_result = invoke_grader(task, scratch_dir)
            verdict = "PASS" if grade_result.passed else "FAIL"
        except GraderInvocationError as exc:
            echo(f"  [{task.instance_id} {arm} run{run_idx}] ERROR: {exc}")
            verdict = "ERROR"
    except Exception as exc:  # noqa: BLE001 — any agent-launch failure is ERROR
        wall_secs = int(time.time() - start)
        echo(f"  [{task.instance_id} {arm} run{run_idx}] ERROR during run: {exc}")
        verdict = "ERROR"

    cost, turns = runner.extract_metadata(agent_jsonl)

    result = ArtifactArmResult(
        instance_id=task.instance_id,
        arm=arm,
        run_idx=run_idx,
        verdict=verdict,
        grade_result=grade_result,
        budget={
            "max_code_runs": task.execution_budget.max_code_runs,
            "max_wall_seconds": task.execution_budget.max_wall_seconds,
            "enforcement": task.execution_budget.enforcement,
        },
        wall_secs=wall_secs,
        cost_usd=cost,
        num_turns=turns,
        agent_surface=runner.surface,
        agent_version=agent_version,
        agent_jsonl_path=str(agent_jsonl),
    )
    with open(result_json, "w") as f:
        json.dump(result.to_dict(), f, indent=2, sort_keys=True)

    echo(
        f"  [{task.instance_id} {arm} run{run_idx}] {verdict} "
        f"(wall={wall_secs}s, cost={cost}, turns={turns})"
    )
    return result
