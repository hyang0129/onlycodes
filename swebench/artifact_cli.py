"""Click CLI group for ``python -m swebench artifact <subcommand>``.

Additive-only: does not touch the existing ``run`` / ``add`` / ``analyze`` /
``cache`` groups. Wired into the dispatcher in ``swebench.cli``.

Subcommands:

- ``artifact run``    — execute code_only / tool_rich arms against artifact tasks.
- ``artifact verify`` — placeholder for the ``tools/verify_graders.py``
  functionality shipped in a later slice (#96). Declared here so the command
  namespace exists; invoking it prints a pointer message and exits 2.
"""

from __future__ import annotations

from pathlib import Path

import click

from swebench import repo_root
from swebench.artifact_loader import load_tasks
from swebench.artifact_run import (
    ARMS,
    is_run_complete,
    run_artifact_arm,
    run_dir_for,
)
from swebench.harness import find_claude_binary


@click.group()
def artifact_group() -> None:
    """Artifact-graded benchmark: run tasks, verify graders (future)."""


@artifact_group.command("run")
@click.option(
    "--filter",
    "filter_ids",
    default=None,
    help="Comma-separated instance IDs to run (default: all in problems/artifact/).",
)
@click.option(
    "--arms",
    type=click.Choice(["code_only", "tool_rich", "both"]),
    default="both",
    show_default=True,
    help="Which arms to run.",
)
@click.option(
    "--runs",
    "num_runs",
    type=int,
    default=1,
    show_default=True,
    help="Number of runs per arm per task.",
)
@click.option(
    "--output-dir",
    "output_dir",
    type=click.Path(file_okay=False, dir_okay=True, resolve_path=False),
    default=None,
    help="Directory for result files [default: <repo>/results_artifact/].",
)
@click.option(
    "--resume/--no-resume",
    "resume",
    default=True,
    show_default=True,
    help=(
        "Skip (task, arm, run) triples with an existing result.json whose "
        "verdict is PASS or FAIL."
    ),
)
@click.option(
    "--tasks-dir",
    "tasks_dir",
    type=click.Path(file_okay=False, dir_okay=True, resolve_path=False),
    default=None,
    help="Directory containing <category>/<slug>/task.yaml [default: <repo>/problems/artifact/].",
)
@click.option(
    "--mcp-config",
    "mcp_config",
    type=click.Path(file_okay=True, dir_okay=False, resolve_path=False),
    default=None,
    help="MCP config path for the code_only arm [default: <repo>/mcp-config.json if present].",
)
def artifact_run_command(
    filter_ids: str | None,
    arms: str,
    num_runs: int,
    output_dir: str | None,
    resume: bool,
    tasks_dir: str | None,
    mcp_config: str | None,
) -> None:
    """Run artifact-graded benchmark arms on one or more tasks."""
    if num_runs < 1:
        click.echo("ERROR: --runs must be >= 1", err=True)
        raise SystemExit(1)

    root = repo_root()
    tasks_root = Path(tasks_dir) if tasks_dir else (root / "problems" / "artifact")
    results_dir = Path(output_dir) if output_dir else (root / "results_artifact")

    filter_set: set[str] | None = None
    if filter_ids:
        filter_set = {s.strip() for s in filter_ids.split(",") if s.strip()}

    try:
        tasks = load_tasks(tasks_root, filter_ids=filter_set)
    except ValueError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        raise SystemExit(1)

    if not tasks:
        click.echo(
            f"ERROR: No tasks found under {tasks_root}. "
            "Add a task at problems/artifact/<category>/<slug>/task.yaml.",
            err=True,
        )
        raise SystemExit(1)

    try:
        claude_binary = find_claude_binary()
    except FileNotFoundError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        raise SystemExit(1)

    arm_list: list[str]
    if arms == "both":
        arm_list = list(ARMS)
    else:
        arm_list = [arms]

    mcp_path = mcp_config
    if mcp_path is None:
        candidate = root / "mcp-config.json"
        if candidate.is_file():
            mcp_path = str(candidate)

    results_dir.mkdir(parents=True, exist_ok=True)

    click.echo(
        f"Loaded {len(tasks)} task(s); arms={arm_list}; runs={num_runs}; "
        f"results_dir={results_dir}"
    )

    for task in tasks:
        click.echo(f"\n== {task.instance_id} ({task.category}/{task.difficulty}) ==")
        for arm in arm_list:
            for run_idx in range(1, num_runs + 1):
                run_dir = run_dir_for(results_dir, task.instance_id, arm, run_idx)
                if resume and is_run_complete(run_dir):
                    click.echo(
                        f"  [{task.instance_id} {arm} run{run_idx}] "
                        "Skipping — already complete (resume on)."
                    )
                    continue
                run_artifact_arm(
                    task,
                    arm,
                    run_idx,
                    results_dir=results_dir,
                    claude_binary=claude_binary,
                    mcp_config_path=mcp_path,
                    echo=click.echo,
                )


@artifact_group.command("verify")
def artifact_verify_command() -> None:
    """Placeholder for the grader verification tool (future slice #96).

    The full implementation lives in ``tools/verify_graders.py`` and will be
    wired to this subcommand by a later child issue. Declared here so the
    command namespace exists.
    """
    click.echo(
        "artifact verify is a placeholder — the grader verification tool "
        "(tools/verify_graders.py) lands in a future slice.",
        err=True,
    )
    raise SystemExit(2)
