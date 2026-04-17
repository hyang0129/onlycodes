"""`analyze summary` — parse results and print summary table."""

from __future__ import annotations

import csv
import re
from pathlib import Path

import click

from swebench import repo_root
from swebench.models import ArmResult


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

        # Extract run index
        match = re.match(r"^(.+)_(baseline|onlycode)_run(\d+)$", name)
        if not match:
            continue

        instance_id = match.group(1)
        arm = match.group(2)
        run_idx = int(match.group(3))

        # Read verdict from last non-empty line
        verdict = "ERROR"
        try:
            lines = test_file.read_text().strip().splitlines()
            if lines:
                last_line = lines[-1].strip()
                if last_line in ("PASS", "FAIL"):
                    verdict = last_line
        except OSError:
            pass

        # Find matching jsonl file
        jsonl_name = f"{instance_id}_{arm}_run{run_idx}.jsonl"
        jsonl_path = results_dir / jsonl_name

        cost_usd: float | None = None
        num_turns: int | None = None
        wall_secs = 0

        if jsonl_path.exists():
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
            )
        )

    return results


def _register(analyze_command: click.Group) -> None:
    """Register the `summary` subcommand on the given analyze group."""

    @analyze_command.command("summary")
    @click.option(
        "--results-dir",
        type=click.Path(exists=True, file_okay=False),
        default=None,
        help="Path to results directory (default: auto-detect results_swebench/).",
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
            rdir = repo_root() / "results_swebench"

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
                    f"${r.cost_usd:.3f}" if r.cost_usd is not None else "N/A",
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
                cost_str = f"${r.cost_usd:.3f}" if r.cost_usd is not None else "N/A"
                turns_str = str(r.num_turns) if r.num_turns is not None else "N/A"
                click.echo(
                    f"{r.instance_id:<30} {r.arm:<12} {r.run_idx:<5} {r.verdict:<8} "
                    f"{cost_str:<10} {turns_str:<7}"
                )

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
