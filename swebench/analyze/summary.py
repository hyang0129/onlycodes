"""`analyze summary` — parse results and print summary table."""

from __future__ import annotations

import csv
import re
from pathlib import Path

import click

from swebench import repo_root
from swebench.models import ArmResult
from swebench.runner import CodexRunner


def _parse_results(results_dir: Path) -> list[ArmResult]:
    """Scan results_dir for test and jsonl file pairs, extract verdicts and stats."""
    results: list[ArmResult] = []

    # Find all *_test.txt files
    test_files = sorted(results_dir.glob("*_test.txt"))

    for test_file in test_files:
        # Parse filename: {instance_id}_{arm}_run{N}_test.txt
        name = test_file.stem  # e.g. django__django-16379_baseline_run1_test
        if not name.endswith("_test"):
            continue
        name = name[: -len("_test")]  # django__django-16379_baseline_run1

        # Extract run index (supports baseline | onlycode | bash_only arms).
        match = re.match(r"^(.+)_(baseline|onlycode|bash_only)_run(\d+)$", name)
        if not match:
            continue

        instance_id = match.group(1)
        arm = match.group(2)
        run_idx = int(match.group(3))

        # Read verdict from last non-empty line.  ``env_fail`` (Issue #238) is
        # treated as a first-class verdict here so it can be displayed as its
        # own column and excluded from pass-rate aggregates.
        verdict = "ERROR"
        try:
            lines = test_file.read_text().strip().splitlines()
            if lines:
                last_line = lines[-1].strip()
                if last_line in ("PASS", "FAIL", "env_fail"):
                    verdict = last_line
        except OSError:
            pass

        # Find matching jsonl file
        jsonl_name = f"{instance_id}_{arm}_run{run_idx}.jsonl"
        jsonl_path = results_dir / jsonl_name

        cost_usd: float | None = None
        num_turns: int | None = None
        wall_secs = 0
        # Default surface for backward compat with old result files that lack
        # the agent_surface field in their meta line.
        agent_surface = "claude_code"

        if jsonl_path.exists():
            # Detect agent_surface from the meta line so we can route cost
            # parsing to the right path (Claude's total_cost_usd vs. Codex's
            # turn.completed usage + price-table estimate).
            try:
                first_line = jsonl_path.read_text().splitlines()[0] if jsonl_path.stat().st_size else ""
                if first_line:
                    import json as _json
                    try:
                        meta = _json.loads(first_line)
                        if isinstance(meta, dict) and meta.get("type") == "meta":
                            _surface = meta.get("agent_surface")
                            if isinstance(_surface, str):
                                agent_surface = _surface
                    except (_json.JSONDecodeError, ValueError):
                        pass
            except (OSError, IndexError):
                pass

            if agent_surface == "codex_cli":
                # Reuse the runner's extract_metadata so the cost formula and
                # price-table loader stay in one place. The model is in the
                # meta line; the runner instance's own model attr is unused.
                try:
                    cost_usd, num_turns = CodexRunner().extract_metadata(jsonl_path)
                except Exception:
                    cost_usd, num_turns = None, None
            else:
                try:
                    content = jsonl_path.read_text()
                    cost_matches = re.findall(r'"total_cost_usd":\s*([\d.]+)', content)
                    turns_matches = re.findall(r'"num_turns":\s*(\d+)', content)
                    if cost_matches:
                        cost_usd = float(cost_matches[-1])
                    if turns_matches:
                        num_turns = int(turns_matches[-1])
                except (OSError, ValueError):
                    pass

        results.append(
            ArmResult(
                instance_id=instance_id,
                arm=arm,
                run_idx=run_idx,
                verdict=verdict,
                cost_usd=cost_usd,
                num_turns=num_turns,
                wall_secs=wall_secs,
                jsonl_path=str(jsonl_path),
                test_txt_path=str(test_file),
                agent_surface=agent_surface,
            )
        )

    return results


def _format_cost(r: ArmResult) -> str:
    """Format the cost column for a single ArmResult row.

    Claude rows show the authoritative ``total_cost_usd`` from the agent's
    own metering — display as ``$0.123``. Codex rows show a price-table
    estimate derived from token counts — prepend ``~`` so reviewers know it
    is not an exact billed amount.

    Issue #253: ``~`` is a display-only marker. ``ArmResult.cost_usd`` stays
    a plain ``float | None`` for CSV/JSON consumers, which simply gives the
    estimate as the number (one source of truth).
    """
    if r.cost_usd is None:
        return "N/A"
    prefix = "~$" if r.agent_surface == "codex_cli" else "$"
    return f"{prefix}{r.cost_usd:.3f}"


def _emit_arm_aggregates(results: list[ArmResult]) -> None:
    """Print a per-arm aggregate footer with pass/fail/env_fail counts.

    The pass-rate excludes ``env_fail`` (Issue #238): runs that never had any
    tests to collect are not counted in either the numerator or the denominator.
    ``ERROR`` rows are likewise excluded from the rate but reported separately.
    The aggregate line is intentionally appended to stdout below the per-row
    table so existing golden fixtures that pin the table format continue to
    match prefix-wise; new fixtures should pin the aggregate too.
    """
    per_arm: dict[str, dict[str, int]] = {}
    for r in results:
        bucket = per_arm.setdefault(
            r.arm, {"PASS": 0, "FAIL": 0, "env_fail": 0, "ERROR": 0}
        )
        if r.verdict in bucket:
            bucket[r.verdict] += 1
        else:
            bucket["ERROR"] += 1

    if not per_arm:
        return

    click.echo("")
    click.echo("Per-arm aggregates (env_fail excluded from pass rate):")
    for arm in sorted(per_arm):
        counts = per_arm[arm]
        passes = counts["PASS"]
        fails = counts["FAIL"]
        env_fails = counts["env_fail"]
        errors = counts["ERROR"]
        denom = passes + fails  # excludes env_fail AND ERROR
        rate = f"{(passes / denom * 100):.1f}%" if denom > 0 else "n/a"
        click.echo(
            f"  {arm:<12} pass={passes:<3} fail={fails:<3} "
            f"env_fail={env_fails:<3} error={errors:<3} "
            f"pass_rate={rate} (denominator={denom})"
        )


def _register(analyze_command: click.Group) -> None:
    """Register the `summary` subcommand on the given analyze group."""

    @analyze_command.command("summary")
    @click.option(
        "--results-dir",
        type=click.Path(exists=True, file_okay=False),
        default=None,
        help="Path to results directory (default: auto-detect runs/swebench/).",
    )
    @click.option(
        "--out",
        "out_path",
        type=click.Path(),
        default=None,
        help="Write summary to CSV file.",
    )
    def summary_command(results_dir: str | None, out_path: str | None) -> None:
        """Analyze SWE-bench results and print a summary table."""
        if results_dir:
            rdir = Path(results_dir)
        else:
            rdir = repo_root() / "runs" / "swebench"

        if not rdir.is_dir():
            click.echo(f"ERROR: Results directory not found: {rdir}", err=True)
            click.echo("Run 'python -m swebench run' first, or specify --results-dir.", err=True)
            raise SystemExit(1)

        results = _parse_results(rdir)

        if not results:
            click.echo(f"No result files found in {rdir}/")
            return

        # Print table using tabulate if available, otherwise manual formatting
        try:
            from tabulate import tabulate

            headers = ["instance_id", "arm", "run", "verdict", "cost", "turns"]
            rows = [
                [
                    r.instance_id,
                    r.arm,
                    r.run_idx,
                    r.verdict,
                    _format_cost(r),
                    r.num_turns if r.num_turns is not None else "N/A",
                ]
                for r in results
            ]
            click.echo(tabulate(rows, headers=headers, tablefmt="plain"))
        except ImportError:
            # Fallback: manual column formatting
            header = f"{'instance_id':<30} {'arm':<12} {'run':<5} {'verdict':<8} {'cost':<10} {'turns':<7}"
            click.echo(header)
            for r in results:
                cost_str = _format_cost(r)
                turns_str = str(r.num_turns) if r.num_turns is not None else "N/A"
                click.echo(
                    f"{r.instance_id:<30} {r.arm:<12} {r.run_idx:<5} {r.verdict:<8} "
                    f"{cost_str:<10} {turns_str:<7}"
                )

        # ----------------------------------------------------------------
        # Per-arm aggregate footer (Issue #238)
        # ----------------------------------------------------------------
        # env_fail is excluded from the pass-rate numerator *and* denominator
        # — those runs never had any tests to pass or fail.  ERROR rows
        # (missing/incomplete verdict) are likewise excluded from the rate
        # but still surfaced for visibility.
        _emit_arm_aggregates(results)

        # Optional CSV output
        if out_path:
            fieldnames = [
                "instance_id", "arm", "run_idx", "verdict",
                "cost_usd", "num_turns", "wall_secs",
                "jsonl_path", "test_txt_path",
            ]
            with open(out_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for r in results:
                    writer.writerow({
                        "instance_id": r.instance_id,
                        "arm": r.arm,
                        "run_idx": r.run_idx,
                        "verdict": r.verdict,
                        "cost_usd": r.cost_usd,
                        "num_turns": r.num_turns,
                        "wall_secs": r.wall_secs,
                        "jsonl_path": r.jsonl_path,
                        "test_txt_path": r.test_txt_path,
                    })
            click.echo(f"\nCSV written to {out_path}")
