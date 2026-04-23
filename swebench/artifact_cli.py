"""Click CLI group for ``python -m swebench artifact <subcommand>``.

Additive-only: does not touch the existing ``run`` / ``add`` / ``analyze`` /
``cache`` groups. Wired into the dispatcher in ``swebench.cli``.

Subcommands:

- ``artifact run``     — execute code_only / tool_rich arms against artifact tasks.
- ``artifact analyze`` — summarise ``runs/artifact/`` as a flat table + aggregates.
- ``artifact verify``  — placeholder for the ``tools/verify_graders.py``
  functionality shipped in a later slice (#96). Declared here so the command
  namespace exists; invoking it prints a pointer message and exits 2.
"""

from __future__ import annotations

import csv
import json
import statistics
from pathlib import Path
from typing import Any

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
    help="Directory for result files [default: <repo>/runs/artifact/].",
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
    results_dir = Path(output_dir) if output_dir else (root / "runs" / "artifact")

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


_ANALYZE_COLUMNS = [
    "task",
    "category",
    "difficulty",
    "arm",
    "run",
    "verdict",
    "turns",
    "cost_usd",
    "wall_secs",
]


def _collect_artifact_rows(
    results_dir: Path,
    tasks_dir: Path,
) -> list[dict[str, Any]]:
    """Walk ``results_dir`` and return one row per (task, arm, run) triple.

    Joins with task metadata loaded from ``tasks_dir`` for category/difficulty.
    Runs that exist as a directory but lack a canonical ``result.json`` are
    surfaced with ``verdict="MISSING"`` rather than silently dropped. Rows whose
    ``task`` instance_id is not present on disk under ``tasks_dir`` still
    surface with ``category`` / ``difficulty`` rendered as ``"unknown"``.

    The canonical result path is exactly
    ``results_dir/<instance_id>/<arm>/run<N>/result.json`` — deeper matches
    (including ``scratch/result.json``) are ignored.
    """
    # Build {instance_id: (category, difficulty)} from on-disk tasks. We don't
    # use filter_ids here because the results dir may reference tasks that
    # were renamed or removed; missing lookups render as "unknown".
    meta: dict[str, tuple[str, str]] = {}
    if tasks_dir.is_dir():
        try:
            for task in load_tasks(tasks_dir):
                meta[task.instance_id] = (task.category, task.difficulty)
        except ValueError:
            # Malformed task.yaml — fall back to "unknown" for all rows rather
            # than crashing the analyze command. The run-time command already
            # surfaces such errors at `artifact run` time.
            meta = {}

    rows: list[dict[str, Any]] = []
    if not results_dir.is_dir():
        return rows

    # runs/artifact/<instance_id>/<arm>/run<N>/
    for instance_dir in sorted(p for p in results_dir.iterdir() if p.is_dir()):
        instance_id = instance_dir.name
        # Skip the analysis sidecar used by SWE-bench mode if it ever leaks
        # into the artifact results layout.
        if instance_id.startswith("_"):
            continue
        category, difficulty = meta.get(instance_id, ("unknown", "unknown"))
        for arm_dir in sorted(p for p in instance_dir.iterdir() if p.is_dir()):
            arm = arm_dir.name
            for run_dir in sorted(p for p in arm_dir.iterdir() if p.is_dir()):
                name = run_dir.name
                if not name.startswith("run"):
                    continue
                try:
                    run_idx = int(name[len("run"):])
                except ValueError:
                    continue

                result_path = run_dir / "result.json"
                # Exact path only — scratch/result.json is intentionally ignored.
                verdict = "MISSING"
                cost_usd: float | None = None
                num_turns: int | None = None
                wall_secs: int | None = None
                if result_path.is_file():
                    try:
                        data = json.loads(result_path.read_text())
                        verdict = str(data.get("verdict") or "MISSING")
                        raw_cost = data.get("cost_usd")
                        cost_usd = (
                            float(raw_cost) if isinstance(raw_cost, (int, float)) else None
                        )
                        raw_turns = data.get("num_turns")
                        num_turns = (
                            int(raw_turns) if isinstance(raw_turns, int) else None
                        )
                        raw_wall = data.get("wall_secs")
                        wall_secs = (
                            int(raw_wall) if isinstance(raw_wall, (int, float)) else None
                        )
                    except (OSError, json.JSONDecodeError, ValueError):
                        verdict = "MISSING"

                rows.append({
                    "task": instance_id,
                    "category": category,
                    "difficulty": difficulty,
                    "arm": arm,
                    "run": run_idx,
                    "verdict": verdict,
                    "turns": num_turns,
                    "cost_usd": cost_usd,
                    "wall_secs": wall_secs,
                })
    rows.sort(key=lambda r: (r["task"], r["arm"], r["run"]))
    return rows


def _fmt_cost(val: float | None) -> str:
    return f"${val:.3f}" if isinstance(val, (int, float)) else "N/A"


def _fmt_num(val: Any) -> str:
    return str(val) if val is not None else "N/A"


def _emit_table(rows: list[dict[str, Any]], echo: Any) -> None:
    """Print the flat table using ``tabulate`` when available (with fallback)."""
    headers = _ANALYZE_COLUMNS
    display_rows = [
        [
            r["task"],
            r["category"],
            r["difficulty"],
            r["arm"],
            r["run"],
            r["verdict"],
            _fmt_num(r["turns"]),
            _fmt_cost(r["cost_usd"]),
            _fmt_num(r["wall_secs"]),
        ]
        for r in rows
    ]
    try:
        from tabulate import tabulate

        echo(tabulate(display_rows, headers=headers, tablefmt="plain"))
    except ImportError:
        widths = []
        for i, h in enumerate(headers):
            col_widths = [len(h)] + [len(str(dr[i])) for dr in display_rows]
            widths.append(max(col_widths))
        echo("  ".join(headers[i].ljust(widths[i]) for i in range(len(headers))))
        for dr in display_rows:
            echo("  ".join(str(dr[i]).ljust(widths[i]) for i in range(len(headers))))


def _aggregate(rows: list[dict[str, Any]]) -> list[str]:
    """Compute the aggregate summary block as a list of output lines."""
    lines: list[str] = ["", "== Aggregate =="]

    # Collect arms present + full canonical set so both show up even if one is empty.
    arms_present = sorted({r["arm"] for r in rows} | set(ARMS))

    # Per-arm pass rate
    lines.append("")
    lines.append("Per-arm pass rate:")
    for arm in arms_present:
        arm_rows = [r for r in rows if r["arm"] == arm]
        total = len(arm_rows)
        passed = sum(1 for r in arm_rows if r["verdict"] == "PASS")
        pct = f"{(100.0 * passed / total):.1f}%" if total else "N/A"
        lines.append(f"  {arm}: {passed}/{total} PASS ({pct})")

    # Per-category pass rate
    cats = sorted({r["category"] for r in rows})
    lines.append("")
    lines.append("Per-category pass rate:")
    for cat in cats:
        cat_rows = [r for r in rows if r["category"] == cat]
        total = len(cat_rows)
        passed = sum(1 for r in cat_rows if r["verdict"] == "PASS")
        pct = f"{(100.0 * passed / total):.1f}%" if total else "N/A"
        lines.append(f"  {cat}: {passed}/{total} PASS ({pct})")

    # Per-arm median cost + turns (compute only over non-None values)
    lines.append("")
    lines.append("Per-arm median cost / turns:")
    arm_cost_totals: dict[str, float] = {}
    for arm in arms_present:
        arm_rows = [r for r in rows if r["arm"] == arm]
        costs = [r["cost_usd"] for r in arm_rows if isinstance(r["cost_usd"], (int, float))]
        turns = [r["turns"] for r in arm_rows if isinstance(r["turns"], int)]
        med_cost = f"${statistics.median(costs):.3f}" if costs else "N/A"
        med_turns = f"{statistics.median(turns):.1f}" if turns else "N/A"
        lines.append(f"  {arm}: median_cost={med_cost}, median_turns={med_turns}")
        arm_cost_totals[arm] = float(sum(costs)) if costs else 0.0

    # Cost ratio: code_only / tool_rich (fail-safe if tool_rich sum == 0)
    lines.append("")
    co_sum = arm_cost_totals.get("code_only", 0.0)
    tr_sum = arm_cost_totals.get("tool_rich", 0.0)
    if tr_sum and tr_sum > 0.0:
        ratio = co_sum / tr_sum
        lines.append(f"code_only / tool_rich cost ratio: {ratio:.3f}")
    else:
        lines.append("code_only / tool_rich cost ratio: N/A")

    return lines


def _write_csv(rows: list[dict[str, Any]], out_path: Path) -> None:
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_ANALYZE_COLUMNS)
        writer.writeheader()
        for r in rows:
            writer.writerow({
                "task": r["task"],
                "category": r["category"],
                "difficulty": r["difficulty"],
                "arm": r["arm"],
                "run": r["run"],
                "verdict": r["verdict"],
                "turns": r["turns"] if r["turns"] is not None else "",
                "cost_usd": r["cost_usd"] if r["cost_usd"] is not None else "",
                "wall_secs": r["wall_secs"] if r["wall_secs"] is not None else "",
            })


@artifact_group.command("analyze")
@click.option(
    "--results-dir",
    "results_dir",
    type=click.Path(file_okay=False, dir_okay=True, resolve_path=False),
    default=None,
    help="Directory with artifact run results [default: <repo>/runs/artifact/].",
)
@click.option(
    "--tasks-dir",
    "tasks_dir",
    type=click.Path(file_okay=False, dir_okay=True, resolve_path=False),
    default=None,
    help="Directory with task.yaml manifests [default: <repo>/problems/artifact/].",
)
@click.option(
    "--out",
    "out_path",
    type=click.Path(file_okay=True, dir_okay=False, resolve_path=False),
    default=None,
    help="Optional: write the full flat table to this CSV path.",
)
def artifact_analyze_command(
    results_dir: str | None,
    tasks_dir: str | None,
    out_path: str | None,
) -> None:
    """Summarise runs/artifact/ as a flat table + aggregates."""
    root = repo_root()
    rdir = Path(results_dir) if results_dir else (root / "runs" / "artifact")
    tdir = Path(tasks_dir) if tasks_dir else (root / "problems" / "artifact")

    if not rdir.is_dir():
        click.echo(f"ERROR: Results directory not found: {rdir}", err=True)
        click.echo(
            "Run 'python -m swebench artifact run' first, or specify --results-dir.",
            err=True,
        )
        raise SystemExit(1)

    rows = _collect_artifact_rows(rdir, tdir)

    if not rows:
        click.echo(f"No artifact run results found under {rdir}/")
        return

    _emit_table(rows, click.echo)
    for line in _aggregate(rows):
        click.echo(line)

    if out_path:
        _write_csv(rows, Path(out_path))
        click.echo(f"\nCSV written to {out_path}")


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
