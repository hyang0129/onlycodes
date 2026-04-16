"""Process 2: run — execute baseline and/or onlycode arms on SWE-bench instances."""

from __future__ import annotations

import os
import time
from pathlib import Path

import click

from swebench import repo_root
from swebench.harness import (
    apply_test_patch,
    clone_repo,
    find_claude_binary,
    generate_mcp_config,
    git_reset,
    run_claude,
    run_tests,
    setup_venv,
)
from swebench.models import Problem


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
) -> None:
    """Run a single arm (baseline or onlycode) for one instance."""
    click.echo(f"  [{arm} run {run_idx}] Starting...")

    # Reset repo to base commit
    git_reset(repo_dir, problem.base_commit)

    # Apply test patch
    if problem.patch_file:
        patch_path = str(root / problem.patch_file)
        if apply_test_patch(repo_dir, patch_path):
            click.echo(f"  [{arm} run {run_idx}] Applied test patch.")
        else:
            click.echo(f"  [{arm} run {run_idx}] WARNING: test patch failed to apply.")

    # Build prompt from problem_statement — eliminates hardcoded text bug
    prompt = (
        f"You are working in the repository at: {repo_dir}\n\n"
        f"Fix the following bug. Make the minimal change needed.\n\n"
        f"{problem.problem_statement}"
    )

    result_file = os.path.join(results_dir, f"{problem.instance_id}_{arm}_run{run_idx}.jsonl")

    # Build tools flags based on arm
    tools_flags: list[str] = []
    effective_mcp_config = mcp_config_path
    if arm == "onlycode":
        effective_mcp_config = generate_mcp_config(mcp_config_path, repo_dir)
        tools_flags = [
            "--mcp-config", effective_mcp_config,
            "--strict-mcp-config",
            "--tools", "mcp__codebox__execute_code",
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

    # Clean up temp MCP config
    if arm == "onlycode" and effective_mcp_config != mcp_config_path:
        try:
            os.unlink(effective_mcp_config)
        except OSError:
            pass

    # Run tests
    test_result_file = os.path.join(
        results_dir, f"{problem.instance_id}_{arm}_run{run_idx}_test.txt"
    )

    click.echo(f"  [{arm} run {run_idx}] Running test suite...")

    verdict = run_tests(
        repo_dir=repo_dir,
        test_cmd=problem.test_cmd,
        venv_dir=venv_dir,
        result_file=test_result_file,
    )

    click.echo(f"  [{arm} run {run_idx}] Tests: {verdict} ({wall_secs}s wall)")

    # Extract cost and turns from stream-json output
    cost = "N/A"
    turns = "N/A"
    try:
        with open(result_file) as f:
            content = f.read()
        import re
        cost_matches = re.findall(r'"total_cost_usd":\s*([\d.]+)', content)
        turns_matches = re.findall(r'"num_turns":\s*(\d+)', content)
        if cost_matches:
            cost = f"${cost_matches[-1]}"
        if turns_matches:
            turns = turns_matches[-1]
    except (OSError, ValueError):
        pass

    click.echo(f"  [{arm} run {run_idx}] Cost: {cost}, Turns: {turns}, Wall: {wall_secs}s")


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
def run_command(filter_ids: str | None, arms: str, num_runs: int) -> None:
    """Run SWE-bench evaluation arms on problem instances."""
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

    # Load problems
    yaml_files = sorted(problems_dir.glob("*.yaml"))
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
    click.echo(f"Claude binary: {claude_binary}")
    click.echo()

    for problem in problems:
        click.echo(f"--- Instance: {problem.instance_id} ---")
        click.echo(f"  Repo: {problem.repo_slug}")
        click.echo(f"  Base commit: {problem.base_commit}")
        click.echo(f"  Test cmd: {problem.test_cmd}")

        repo_dir = os.path.join(clone_base, problem.instance_id)
        venv_dir = os.path.join(clone_base, "venvs", problem.instance_id)

        # Clone and setup
        clone_repo(problem.repo_slug, repo_dir)
        git_reset(repo_dir, problem.base_commit)
        setup_venv(venv_dir, repo_dir)

        for run_idx in range(1, num_runs + 1):
            for arm in arm_list:
                click.echo()
                _run_arm(
                    problem=problem,
                    arm=arm,
                    run_idx=run_idx,
                    repo_dir=repo_dir,
                    venv_dir=venv_dir,
                    results_dir=str(results_dir),
                    claude_binary=claude_binary,
                    mcp_config_path=mcp_config_path,
                    root=root,
                )

        click.echo()

    click.echo(f"=== Done. Results in {results_dir}/ ===")
