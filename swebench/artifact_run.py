"""Arm executor for artifact-graded benchmark tasks.

Orchestrates a single (task, arm, run) triple end-to-end:

1. Materialise workspace into scratch dir (no-leak invariant enforced).
2. Build prompt from ``prompt.md``.
3. Run Claude via ``harness.run_claude`` with cwd=scratch_dir.
4. Invoke the grader on the populated scratch dir.
5. Write ``result.json`` + ``agent.jsonl``.

Mirrors the matched-arm pattern from ``swebench.run._run_arm`` (lines 135–329)
but with artifact primitives. Does NOT import ``swebench.cache``.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Callable

from swebench.artifact_grade import GraderInvocationError, invoke_grader
from swebench.artifact_materialize import materialize, scratch_dir_for
from swebench.artifact_models import ArtifactArmResult, GradeResult, Task
from swebench.harness import get_claude_version, run_claude

# Matched verbatim with ``run.py:_BLOCKED_BUILTINS`` (lines 248–256). Duplication
# is intentional: refined spec §3 calls for no shared state between SWE-bench
# and artifact modes. If the SWE-bench list drifts, the artifact arm stays pinned
# to the version that was validated against the artifact-mode invariants.
_BLOCKED_BUILTINS = (
    "Agent,AskUserQuestion,Bash,CronCreate,CronDelete,CronList,"
    "Edit,EnterPlanMode,EnterWorktree,ExitPlanMode,ExitWorktree,"
    "Glob,Grep,ListMcpResourcesTool,LSP,Monitor,NotebookEdit,"
    "PowerShell,PushNotification,Read,ReadMcpResourceTool,"
    "RemoteTrigger,SendMessage,Skill,"
    "TaskCreate,TaskGet,TaskList,TaskOutput,TaskStop,TaskUpdate,"
    "TeamCreate,TeamDelete,TodoWrite,ToolSearch,WebFetch,WebSearch,Write"
)

ARMS = ("code_only", "tool_rich")


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

    parts = [
        f"You are working in the directory: {scratch_dir}",
        f"Write your output artifact to the relative path: {task.output_artifact}",
        "",
        prompt_body,
    ]
    return "\n".join(parts)


def _build_tools_flags(arm: str, mcp_config_path: str | None) -> list[str]:
    """Construct ``--tools`` / ``--disallowedTools`` flags for the chosen arm.

    ``code_only`` mirrors the ``onlycode`` arm (restricts to two MCP tools).
    ``tool_rich`` mirrors ``baseline`` (no restriction).
    """
    if arm == "tool_rich":
        return []
    if arm == "code_only":
        flags = []
        if mcp_config_path:
            flags.extend([
                "--mcp-config", mcp_config_path,
                "--strict-mcp-config",
            ])
        flags.extend([
            "--tools", "mcp__codebox__execute_code,mcp__codebox__list_tools",
            "--disallowedTools", _BLOCKED_BUILTINS,
        ])
        return flags
    raise ValueError(f"Unknown arm: {arm!r}")


def _log_budget(task: Task, echo: Callable[[str], None]) -> None:
    b = task.execution_budget
    if b.is_unlimited:
        echo(
            f"  [{task.instance_id}] budget enforcement OFF (0 = unlimited)"
        )
    else:
        echo(
            f"  [{task.instance_id}] budget declared: "
            f"max_code_runs={b.max_code_runs}, "
            f"max_wall_seconds={b.max_wall_seconds} "
            f"(enforcement OFF — future epic)"
        )


def _extract_cost_and_turns(jsonl_path: Path) -> tuple[float | None, int | None]:
    """Parse the last ``total_cost_usd`` / ``num_turns`` values from a stream-json log."""
    try:
        content = jsonl_path.read_text()
    except OSError:
        return (None, None)
    cost: float | None = None
    turns: int | None = None
    cost_match = re.findall(r'"total_cost_usd":\s*([\d.]+)', content)
    if cost_match:
        try:
            cost = float(cost_match[-1])
        except ValueError:
            cost = None
    turns_match = re.findall(r'"num_turns":\s*(\d+)', content)
    if turns_match:
        try:
            turns = int(turns_match[-1])
        except ValueError:
            turns = None
    return (cost, turns)


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
    claude_binary: str,
    mcp_config_path: str | None = None,
    echo: Callable[[str], None] | None = None,
) -> ArtifactArmResult:
    """Run one (task, arm, run_idx) triple and write result.json + agent.jsonl.

    Returns the ``ArtifactArmResult`` (also serialised to disk).
    """
    if arm not in ARMS:
        raise ValueError(f"arm must be one of {ARMS}, got {arm!r}")
    if echo is None:
        echo = print

    run_dir = run_dir_for(results_dir, task.instance_id, arm, run_idx)
    run_dir.mkdir(parents=True, exist_ok=True)
    scratch_dir = scratch_dir_for(results_dir, task.instance_id, arm, run_idx)

    agent_jsonl = run_dir / "agent.jsonl"
    result_json = run_dir / "result.json"

    echo(f"  [{task.instance_id} {arm} run{run_idx}] Materializing workspace...")
    materialize(task, scratch_dir)
    _log_budget(task, echo)

    # Seed the agent.jsonl with a self-describing meta record — mirrors
    # run.py lines 274–284 so analysis tooling can reuse the same shape.
    claude_version = get_claude_version(claude_binary)
    with open(agent_jsonl, "w") as f:
        f.write(json.dumps({
            "type": "meta",
            "mode": "artifact",
            "instance_id": task.instance_id,
            "arm": arm,
            "run": run_idx,
            "claude_binary": claude_binary,
            "claude_version": claude_version,
        }) + "\n")

    prompt = _build_prompt(task, scratch_dir, arm)
    tools_flags = _build_tools_flags(arm, mcp_config_path)

    # TODO(budget): increment code_run counter here — enforcement is OFF.
    # The hook is intentionally a no-op in seed-v1 per the STRONG invariant:
    # declare + store fields now, flip enforcement in a later epic.

    start = time.time()
    verdict: str
    grade_result: GradeResult | None = None
    try:
        run_claude(
            prompt=prompt,
            repo_dir=str(scratch_dir),
            system_prompt="You are a helpful assistant.",
            tools_flags=tools_flags,
            result_file=str(agent_jsonl),
            claude_binary=claude_binary,
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

    cost, turns = _extract_cost_and_turns(agent_jsonl)

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
        claude_version=claude_version,
        agent_jsonl_path=str(agent_jsonl),
    )
    with open(result_json, "w") as f:
        json.dump(result.to_dict(), f, indent=2, sort_keys=True)

    echo(
        f"  [{task.instance_id} {arm} run{run_idx}] {verdict} "
        f"(wall={wall_secs}s, cost={cost}, turns={turns})"
    )
    return result
