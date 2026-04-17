"""Process 2: run — execute baseline and/or onlycode arms on SWE-bench instances."""

from __future__ import annotations

import io
import os
import re
import time
import traceback
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from pathlib import Path
from typing import NamedTuple

import click

from swebench import repo_root
from swebench.harness import (
    apply_test_patch,
    clone_repo,
    find_claude_binary,
    git_reset,
    run_claude,
    run_tests,
    setup_venv,
)
from swebench.models import Problem


class _ArmTask(NamedTuple):
    """Describes one arm execution to schedule."""

    problem: Problem
    arm: str
    run_idx: int
    repo_dir: str
    venv_dir: str


def _run_arm(
    *,
    problem: Problem,
    arm: str,
    run_idx: int,
    repo_dir: str,
    venv_dir: str,
    results_dir: str,
    claude_binary: str,
    mcp_config_path: str,
    root: Path,
    log_buffer: io.StringIO | None = None,
) -> str:
    """Run a single arm (baseline or onlycode) for one instance.

    Returns the verdict string ("PASS", "FAIL", or "ERROR").
    When *log_buffer* is provided, all output is written there instead of
    directly to stdout so that parallel runs don't interleave.
    """

    def _echo(msg: str) -> None:
        if log_buffer is not None:
            log_buffer.write(msg + "\n")
        else:
            click.echo(msg)

    _echo(f"  [{arm} run {run_idx}] Starting...")

    # Reset repo to base commit
    git_reset(repo_dir, problem.base_commit)

    # Apply test patch
    if problem.patch_file:
        patch_path = str(root / problem.patch_file)
        if apply_test_patch(repo_dir, patch_path):
            _echo(f"  [{arm} run {run_idx}] Applied test patch.")
        else:
            _echo(f"  [{arm} run {run_idx}] WARNING: test patch failed to apply.")

    # Build prompt from problem_statement — eliminates hardcoded text bug
    prompt = (
        f"You are working in the repository at: {repo_dir}\n\n"
        f"Fix the following bug. Make the minimal change needed.\n\n"
        f"{problem.problem_statement}"
    )

    result_file = os.path.join(results_dir, f"{problem.instance_id}_{arm}_run{run_idx}.jsonl")

    # Build tools flags based on arm
    tools_flags: list[str] = []
    if arm == "onlycode":
        tools_flags = [
            "--mcp-config", mcp_config_path,
            "--strict-mcp-config",
            "--tools", "mcp__codebox__execute_code,mcp__codebox__list_tools",
        ]

    start_time = time.time()

    run_claude(
        prompt=prompt,
        repo_dir=repo_dir,
        system_prompt="You are a helpful assistant.",
        tools_flags=tools_flags,
        result_file=result_file,
        claude_binary=claude_binary,
    )

    wall_secs = int(time.time() - start_time)

    # Run tests
    test_result_file = os.path.join(
        results_dir, f"{problem.instance_id}_{arm}_run{run_idx}_test.txt"
    )

    _echo(f"  [{arm} run {run_idx}] Running test suite...")

    verdict = run_tests(
        repo_dir=repo_dir,
        test_cmd=problem.test_cmd,
        venv_dir=venv_dir,
        result_file=test_result_file,
    )

    _echo(f"  [{arm} run {run_idx}] Tests: {verdict} ({wall_secs}s wall)")

    # Extract cost and turns from stream-json output
    cost = "N/A"
    turns = "N/A"
    try:
        with open(result_file) as f:
            content = f.read()
        cost_matches = re.findall(r'"total_cost_usd":\s*([\d.]+)', content)
        turns_matches = re.findall(r'"num_turns":\s*(\d+)', content)
        if cost_matches:
            cost = f"${cost_matches[-1]}"
        if turns_matches:
            turns = turns_matches[-1]
    except (OSError, ValueError):
        pass

    _echo(f"  [{arm} run {run_idx}] Cost: {cost}, Turns: {turns}, Wall: {wall_secs}s")
    return verdict


def _setup_problem(problem: Problem, clone_base: str) -> tuple[str, str]:
    """Clone repo and set up venv for a single problem. Returns (repo_dir, venv_dir)."""
    repo_dir = os.path.join(clone_base, problem.instance_id)
    venv_dir = os.path.join(clone_base, "venvs", problem.instance_id)
    clone_repo(problem.repo_slug, repo_dir)
    git_reset(repo_dir, problem.base_commit)
    setup_venv(venv_dir, repo_dir)
    return repo_dir, venv_dir


# Global lock for serialised stdout flushing.
_print_lock = threading.Lock()


def _flush_buffer(header: str, buf: io.StringIO) -> None:
    """Write buffered output to stdout atomically under a lock."""
    text = buf.getvalue()
    with _print_lock:
        click.echo(header)
        if text:
            click.echo(text, nl=False)
        click.echo()


@click.command("run")
@click.option(
    "--filter",
    "filter_ids",
    default=None,
    help="Comma-separated instance IDs to run (default: all in problems/).",
)
@click.option(
    "--arms",
    type=click.Choice(["baseline", "onlycode", "both"]),
    default="both",
    help="Which arms to run (default: both).",
)
@click.option(
    "--runs",
    "num_runs",
    type=int,
    default=1,
    help="Number of runs per arm (default: 1).",
)
@click.option(
    "--parallel",
    "parallel",
    type=int,
    default=1,
    help="Max problems to run concurrently (default: 1 = serial).",
)
@click.option(
    "--fail-fast",
    "fail_fast",
    is_flag=True,
    default=False,
    help="Stop on first FAIL verdict. Cancels queued tasks; already-running Claude invocations finish.",
)
def run_command(
    filter_ids: str | None,
    arms: str,
    num_runs: int,
    parallel: int,
    fail_fast: bool,
) -> None:
    """Run SWE-bench evaluation arms on problem instances."""
    if parallel < 1:
        click.echo("ERROR: --parallel must be >= 1", err=True)
        raise SystemExit(1)

    root = repo_root()
    problems_dir = root / "problems"
    results_dir = root / "results_swebench"
    mcp_config_path = str(root / "mcp-config.json")
    clone_base = "/tmp/swebench"

    results_dir.mkdir(parents=True, exist_ok=True)
    os.makedirs(clone_base, exist_ok=True)

    # Find claude binary
    try:
        claude_binary = find_claude_binary()
    except FileNotFoundError as e:
        click.echo(f"ERROR: {e}", err=True)
        raise SystemExit(1)

    # Load problems (recurse into subfolders so curated sets in e.g.
    # problems/swebench-verified-mini/ and problems/adhoc/ are all picked up).
    yaml_files = sorted(problems_dir.rglob("*.yaml"))
    if not yaml_files:
        click.echo("ERROR: No problem files found in problems/. Run 'python -m swebench add' first.", err=True)
        raise SystemExit(1)

    problems = [Problem.from_yaml(f) for f in yaml_files]

    # Apply filter
    if filter_ids:
        ids = {s.strip() for s in filter_ids.split(",")}
        problems = [p for p in problems if p.instance_id in ids]
        if not problems:
            click.echo(f"ERROR: No matching problems for filter: {filter_ids}", err=True)
            raise SystemExit(1)

    # Determine arms to run
    arm_list: list[str] = []
    if arms in ("baseline", "both"):
        arm_list.append("baseline")
    if arms in ("onlycode", "both"):
        arm_list.append("onlycode")

    click.echo(f"=== SWE-bench Evaluation ===")
    click.echo(f"Problems: {len(problems)}")
    click.echo(f"Arms: {', '.join(arm_list)}")
    click.echo(f"Runs per arm: {num_runs}")
    click.echo(f"Parallel: {parallel}")
    click.echo(f"Fail-fast: {fail_fast}")
    click.echo(f"Claude binary: {claude_binary}")
    click.echo()

    # --- Phase 1: parallel clone + venv setup -----------------------------------
    click.echo("Phase 1: Setting up repos and venvs...")
    setup_map: dict[str, tuple[str, str]] = {}

    if parallel == 1:
        # Serial setup — no thread overhead
        for problem in problems:
            click.echo(f"  Setting up {problem.instance_id}...")
            setup_map[problem.instance_id] = _setup_problem(problem, clone_base)
    else:
        with ThreadPoolExecutor(max_workers=parallel) as pool:
            future_to_id: dict[Future[tuple[str, str]], str] = {}
            for problem in problems:
                fut = pool.submit(_setup_problem, problem, clone_base)
                future_to_id[fut] = problem.instance_id
            for fut in as_completed(future_to_id):
                pid = future_to_id[fut]
                try:
                    setup_map[pid] = fut.result()
                    click.echo(f"  {pid}: setup complete")
                except Exception as exc:
                    click.echo(f"  {pid}: setup FAILED ({exc})", err=True)
                    raise SystemExit(1)

    click.echo()

    # --- Phase 2: run arms -------------------------------------------------------
    click.echo("Phase 2: Running evaluation arms...")
    click.echo()

    # Build arm tasks grouped by problem.  Each problem's arms must run
    # serially because they share one repo_dir (git working tree).
    problem_tasks: dict[str, list[_ArmTask]] = {}
    for problem in problems:
        repo_dir, venv_dir = setup_map[problem.instance_id]
        tasks: list[_ArmTask] = []
        for run_idx in range(1, num_runs + 1):
            for arm in arm_list:
                tasks.append(_ArmTask(
                    problem=problem,
                    arm=arm,
                    run_idx=run_idx,
                    repo_dir=repo_dir,
                    venv_dir=venv_dir,
                ))
        problem_tasks[problem.instance_id] = tasks

    if parallel == 1:
        # Serial execution — matches original behaviour exactly
        last_instance: str | None = None
        for pid, tasks in problem_tasks.items():
            for task in tasks:
                if task.problem.instance_id != last_instance:
                    click.echo(f"--- Instance: {task.problem.instance_id} ---")
                    click.echo(f"  Repo: {task.problem.repo_slug}")
                    click.echo(f"  Base commit: {task.problem.base_commit}")
                    click.echo(f"  Test cmd: {task.problem.test_cmd}")
                    last_instance = task.problem.instance_id
                verdict = _run_arm(
                    problem=task.problem,
                    arm=task.arm,
                    run_idx=task.run_idx,
                    repo_dir=task.repo_dir,
                    venv_dir=task.venv_dir,
                    results_dir=str(results_dir),
                    claude_binary=claude_binary,
                    mcp_config_path=mcp_config_path,
                    root=root,
                )
                click.echo()
                if fail_fast and verdict == "FAIL":
                    click.echo("FAIL detected with --fail-fast; stopping early.")
                    raise SystemExit(1)
    else:
        # Parallel execution — one thread per problem.  Arms within each
        # problem run serially to avoid repo_dir race conditions.
        _fail_event = threading.Event()

        def _run_problem_tasks(tasks: list[_ArmTask]) -> list[tuple[str, str]]:
            """Run all arm tasks for one problem serially; returns list of (id, verdict)."""
            results: list[tuple[str, str]] = []
            for task in tasks:
                if _fail_event.is_set():
                    results.append((task.problem.instance_id, "CANCELLED"))
                    continue

                buf = io.StringIO()
                try:
                    verdict = _run_arm(
                        problem=task.problem,
                        arm=task.arm,
                        run_idx=task.run_idx,
                        repo_dir=task.repo_dir,
                        venv_dir=task.venv_dir,
                        results_dir=str(results_dir),
                        claude_binary=claude_binary,
                        mcp_config_path=mcp_config_path,
                        root=root,
                        log_buffer=buf,
                    )
                except Exception as exc:
                    buf.write(f"\nERROR: {exc}\n")
                    buf.write(traceback.format_exc())
                    verdict = "ERROR"

                header = (
                    f"--- Instance: {task.problem.instance_id} "
                    f"[{task.arm} run {task.run_idx}] ---"
                )
                _flush_buffer(header, buf)

                if fail_fast and verdict == "FAIL":
                    _fail_event.set()

                results.append((task.problem.instance_id, verdict))
            return results

        with ThreadPoolExecutor(max_workers=parallel) as pool:
            futures = {
                pool.submit(_run_problem_tasks, tasks): pid
                for pid, tasks in problem_tasks.items()
            }

            had_failure = False
            for fut in as_completed(futures):
                try:
                    for instance_id, verdict in fut.result():
                        if verdict == "FAIL" and fail_fast:
                            had_failure = True
                except Exception:
                    had_failure = True

                # Cancel remaining unstarted futures on failure
                if had_failure and fail_fast:
                    for other_fut in futures:
                        other_fut.cancel()

            if had_failure:
                click.echo("FAIL detected with --fail-fast; stopping early.")
                raise SystemExit(1)

    click.echo(f"=== Done. Results in {results_dir}/ ===")
