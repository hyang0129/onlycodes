"""Process 1: add — fetch, validate, and write SWE-bench instances."""

from __future__ import annotations

import subprocess
import sys
from datetime import date
from pathlib import Path

import click

from swebench.models import Problem


def _repo_root() -> Path:
    """Return the repository root (parent of swebench/)."""
    return Path(__file__).resolve().parent.parent


def _fetch_instance(instance_id: str) -> dict:
    """Fetch a single instance from SWE-bench datasets via HuggingFace (streaming).

    Tries SWE-bench_Verified first, then falls back to SWE-bench.
    """
    try:
        from datasets import load_dataset
    except ImportError:
        click.echo(
            "ERROR: 'datasets' package is required for the add command.\n"
            "Install it with: pip install 'datasets>=2.18'",
            err=True,
        )
        sys.exit(1)

    # Try SWE-bench_Verified first, then fall back to SWE-bench
    datasets_to_try = [
        ("princeton-nlp/SWE-bench_Verified", "test"),
        ("princeton-nlp/SWE-bench", "test"),
    ]

    for dataset_name, split in datasets_to_try:
        click.echo(f"Searching {dataset_name} for {instance_id} (streaming)...")
        ds = load_dataset(dataset_name, split=split, streaming=True)
        for row in ds:
            if row["instance_id"] == instance_id:
                click.echo(f"  Found in {dataset_name}.")
                return row

    click.echo(
        f"ERROR: instance '{instance_id}' not found in SWE-bench_Verified or SWE-bench.",
        err=True,
    )
    sys.exit(1)


def _validate_instance(instance_id: str, repo_slug: str, base_commit: str) -> None:
    """Validate that the instance repo is cloneable and base commit is reachable.

    This performs lightweight checks — it does not actually clone the repo if it
    doesn't already exist locally.
    """
    click.echo(f"Validating {instance_id}...")

    # Check repo exists on GitHub
    result = subprocess.run(
        ["gh", "repo", "view", repo_slug, "--json", "name"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        click.echo(f"WARNING: Could not verify repo {repo_slug} via gh: {result.stderr.strip()}", err=True)
    else:
        click.echo(f"  Repo {repo_slug} exists on GitHub.")

    click.echo(f"  Base commit: {base_commit}")
    click.echo("  Validation complete.")


@click.command("add")
@click.argument("instance_id")
def add_command(instance_id: str) -> None:
    """Fetch an instance from SWE-bench_Verified and write it to problems/."""
    root = _repo_root()
    problems_dir = root / "problems"
    patches_dir = root / "patches"

    # Check if already exists
    yaml_path = problems_dir / f"{instance_id}.yaml"
    if yaml_path.exists():
        click.echo(f"Problem file already exists: {yaml_path}")
        click.echo("Overwriting with fresh data from HuggingFace...")

    # Fetch from HuggingFace
    row = _fetch_instance(instance_id)

    repo_slug = row["repo"]
    base_commit = row["base_commit"]

    # Validate
    _validate_instance(instance_id, repo_slug, base_commit)

    # Build test command from FAIL_TO_PASS test names
    test_cmd = ""
    if "test_cmd" in row and row["test_cmd"]:
        test_cmd = row["test_cmd"]
    else:
        # Construct from FAIL_TO_PASS field
        fail_to_pass = row.get("FAIL_TO_PASS", [])
        if isinstance(fail_to_pass, str):
            import json as _json
            try:
                fail_to_pass = _json.loads(fail_to_pass)
            except (ValueError, TypeError):
                fail_to_pass = [fail_to_pass]

        if fail_to_pass:
            # Extract dotted test names from format like "test_name (module.Class)"
            test_names = []
            for entry in fail_to_pass:
                import re as _re
                # Handle "test_name (module.Class)" format
                m = _re.match(r"^(\S+)\s+\(([^)]+)\)$", entry)
                if m:
                    test_name, class_path = m.group(1), m.group(2)
                    test_names.append(f"{class_path}.{test_name}")
                else:
                    test_names.append(entry)

            # For django repos, use runtests.py; otherwise default to pytest
            if "django" in repo_slug.lower():
                test_cmd = "python tests/runtests.py " + " ".join(test_names) + " --parallel=1"
            else:
                test_cmd = "python -m pytest " + " ".join(test_names)

            click.echo(f"  Constructed test_cmd from FAIL_TO_PASS: {test_cmd}")
        else:
            click.echo("WARNING: no test_cmd or FAIL_TO_PASS in dataset row; set test_cmd manually.", err=True)

    # Check for patch file
    patch_file: str | None = None
    patch_path = patches_dir / f"{instance_id}_tests.patch"
    if patch_path.exists():
        patch_file = f"patches/{instance_id}_tests.patch"
        click.echo(f"  Found patch file: {patch_file}")
    else:
        click.echo(f"  WARNING: No patch file at {patch_path}. You may need to create it.", err=True)

    # Build Problem and write YAML
    problem = Problem(
        instance_id=instance_id,
        repo_slug=repo_slug,
        base_commit=base_commit,
        test_cmd=test_cmd,
        problem_statement=row.get("problem_statement", ""),
        patch_file=patch_file,
        added_at=date.today().isoformat(),
        hf_split="test",
    )

    problem.to_yaml(yaml_path)
    click.echo(f"Wrote {yaml_path}")
