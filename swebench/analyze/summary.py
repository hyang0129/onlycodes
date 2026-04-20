"""`analyze summary` — parse results and print summary table.

Supports two result layouts:

1. SWE-bench mode (historic): flat ``<iid>_<arm>_run<N>_test.txt`` + ``*.jsonl``
   pairs under ``results_swebench/``.
2. Artifact mode (issue #108): nested ``<iid>/<arm>/run<N>/result.json`` tree
   produced by ``python -m swebench artifact run``.

The summary command auto-detects which layout it is looking at. Artifact-mode
rows carry a ``leak`` column (Y / .) surfacing runs where the per-run grader
leak auditor flagged a fingerprint match in the agent transcript. Tainted rows
are excluded from the headline pass-rate and counted separately.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
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


@dataclass
class ArtifactRow:
    """Row shape for artifact-mode summary entries (issue #108)."""

    instance_id: str
    arm: str
    run_idx: int
    verdict: str
    cost_usd: float | None
    num_turns: int | None
    wall_secs: int
    leak_detected: bool
    result_json_path: str


def _parse_artifact_results(results_dir: Path) -> list[ArtifactRow]:
    """Walk ``<iid>/<arm>/run<N>/result.json`` and return one row per run.

    Unknown / missing fields are tolerated — older result.json files without
    ``leak_detected`` default to ``False`` (pre-audit data is treated as clean).
    """
    rows: list[ArtifactRow] = []
    for result_path in sorted(results_dir.glob("*/*/run*/result.json")):
        try:
            data = json.loads(result_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        rows.append(
            ArtifactRow(
                instance_id=str(data.get("instance_id", result_path.parts[-4])),
                arm=str(data.get("arm", result_path.parts[-3])),
                run_idx=int(data.get("run_idx", _run_idx_from_name(result_path.parts[-2]))),
                verdict=str(data.get("verdict", "ERROR")),
                cost_usd=(
                    float(data["cost_usd"])
                    if data.get("cost_usd") is not None
                    else None
                ),
                num_turns=(
                    int(data["num_turns"])
                    if data.get("num_turns") is not None
                    else None
                ),
                wall_secs=int(data.get("wall_secs", 0)),
                leak_detected=bool(data.get("leak_detected", False)),
                result_json_path=str(result_path),
            )
        )
    return rows


def _run_idx_from_name(name: str) -> int:
    m = re.match(r"run(\d+)$", name)
    return int(m.group(1)) if m else 0


def _detect_artifact_layout(results_dir: Path) -> bool:
    """Return True if ``results_dir`` contains any artifact-mode result.json."""
    for _ in results_dir.glob("*/*/run*/result.json"):
        return True
    return False


def _print_artifact_table(rows: list[ArtifactRow], echo) -> None:
    try:
        from tabulate import tabulate

        headers = ["instance_id", "arm", "run", "verdict", "leak", "cost", "turns"]
        body = [
            [
                r.instance_id,
                r.arm,
                r.run_idx,
                r.verdict,
                "Y" if r.leak_detected else ".",
                f"${r.cost_usd:.3f}" if r.cost_usd is not None else "N/A",
                r.num_turns if r.num_turns is not None else "N/A",
            ]
            for r in rows
        ]
        echo(tabulate(body, headers=headers, tablefmt="plain"))
    except ImportError:  # pragma: no cover — tabulate is a hard dep in this repo
        header = (
            f"{'instance_id':<30} {'arm':<12} {'run':<5} {'verdict':<8} "
            f"{'leak':<5} {'cost':<10} {'turns':<7}"
        )
        echo(header)
        for r in rows:
            cost_str = f"${r.cost_usd:.3f}" if r.cost_usd is not None else "N/A"
            turns_str = str(r.num_turns) if r.num_turns is not None else "N/A"
            echo(
                f"{r.instance_id:<30} {r.arm:<12} {r.run_idx:<5} "
                f"{r.verdict:<8} {('Y' if r.leak_detected else '.'):<5} "
                f"{cost_str:<10} {turns_str:<7}"
            )

    # Pass-rate with and without tainted runs.
    total = len(rows)
    clean = [r for r in rows if not r.leak_detected]
    tainted = total - len(clean)
    passes_clean = sum(1 for r in clean if r.verdict == "PASS")
    echo("")
    echo(
        f"Clean runs: {len(clean)}; PASS={passes_clean} "
        f"({(passes_clean / len(clean) * 100):.1f}% pass-rate excluding tainted)"
        if clean else
        f"Clean runs: 0; PASS=0"
    )
    if tainted:
        echo(
            f"Tainted runs (leak_detected=true): {tainted} — excluded from pass-rate."
        )


def _write_artifact_csv(rows: list[ArtifactRow], out_path: str) -> None:
    fieldnames = [
        "instance_id", "arm", "run_idx", "verdict", "leak_detected",
        "cost_usd", "num_turns", "wall_secs", "result_json_path",
    ]
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow({
                "instance_id": r.instance_id,
                "arm": r.arm,
                "run_idx": r.run_idx,
                "verdict": r.verdict,
                "leak_detected": r.leak_detected,
                "cost_usd": r.cost_usd,
                "num_turns": r.num_turns,
                "wall_secs": r.wall_secs,
                "result_json_path": r.result_json_path,
            })


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

        # Issue #108: auto-detect artifact-mode results layout and surface a
        # leak column + tainted-run counter when the layout matches. Falls back
        # to the SWE-bench flat layout otherwise.
        if _detect_artifact_layout(rdir):
            artifact_rows = _parse_artifact_results(rdir)
            if not artifact_rows:
                click.echo(f"No result files found in {rdir}/")
                return
            _print_artifact_table(artifact_rows, click.echo)
            if out_path:
                _write_artifact_csv(artifact_rows, out_path)
                click.echo(f"\nCSV written to {out_path}")
            return

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
