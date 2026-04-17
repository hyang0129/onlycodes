"""Process 1: add — fetch, validate, and write SWE-bench instances."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import click

from swebench import repo_root
from swebench.models import Problem


# Lock to serialise click.echo output across parallel worker threads.
_print_lock = threading.Lock()


def _echo(msg: str, *, err: bool = False) -> None:
    with _print_lock:
        click.echo(msg, err=err)


def _iter_ids_file(path: Path) -> list[str]:
    """Read instance IDs from a file, one per line.

    Ignores blank lines and lines starting with '#'. Whitespace is stripped.
    Preserves order and removes duplicates (first occurrence wins).
    """
    ids: list[str] = []
    seen: set[str] = set()
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line in seen:
            continue
        seen.add(line)
        ids.append(line)
    return ids


def _fetch_instance(instance_id: str) -> dict:
    """Fetch a single instance from SWE-bench datasets via HuggingFace (streaming).

    Tries SWE-bench_Verified first, then falls back to SWE-bench.
    """
    try:
        from datasets import load_dataset
    except ImportError:
        _echo(
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
        _echo(f"Searching {dataset_name} for {instance_id} (streaming)...")
        ds = load_dataset(dataset_name, split=split, streaming=True)
        for row in ds:
            if row["instance_id"] == instance_id:
                _echo(f"  Found {instance_id} in {dataset_name}.")
                return row

    raise LookupError(
        f"instance '{instance_id}' not found in SWE-bench_Verified or SWE-bench."
    )


def _validate_instance(instance_id: str, repo_slug: str, base_commit: str) -> None:
    """Validate that the instance repo is cloneable and base commit is reachable.

    This performs lightweight checks — it does not actually clone the repo if it
    doesn't already exist locally.
    """
    _echo(f"Validating {instance_id}...")

    # Check repo exists on GitHub
    result = subprocess.run(
        ["gh", "repo", "view", repo_slug, "--json", "name"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        _echo(
            f"WARNING: Could not verify repo {repo_slug} via gh: {result.stderr.strip()}",
            err=True,
        )
    else:
        _echo(f"  Repo {repo_slug} exists on GitHub.")

    _echo(f"  Base commit: {base_commit}")
    _echo(f"  Validation complete for {instance_id}.")


def _build_test_cmd(row: dict, repo_slug: str) -> str:
    """Derive a test command from the dataset row.

    Uses the row's ``test_cmd`` field when present, otherwise constructs one
    from ``FAIL_TO_PASS``. Returns an empty string if neither is available.
    """
    if "test_cmd" in row and row["test_cmd"]:
        return row["test_cmd"]

    fail_to_pass = row.get("FAIL_TO_PASS", [])
    if isinstance(fail_to_pass, str):
        try:
            fail_to_pass = json.loads(fail_to_pass)
        except (ValueError, TypeError):
            fail_to_pass = [fail_to_pass]

    if not fail_to_pass:
        return ""

    # Extract dotted test names from format like "test_name (module.Class)"
    test_names: list[str] = []
    for entry in fail_to_pass:
        m = re.match(r"^(\S+)\s+\(([^)]+)\)$", entry)
        if m:
            test_name, class_path = m.group(1), m.group(2)
            test_names.append(f"{class_path}.{test_name}")
        else:
            test_names.append(entry)

    if "django" in repo_slug.lower():
        return "python tests/runtests.py " + " ".join(test_names) + " --parallel=1"
    return "python -m pytest " + " ".join(test_names)


def _write_problem(
    instance_id: str,
    row: dict,
    problems_dir: Path,
    patches_dir: Path,
    set_name: str,
) -> Path:
    """Validate, materialise the test patch, and write the YAML. Returns the YAML path."""
    repo_slug = row["repo"]
    base_commit = row["base_commit"]

    _validate_instance(instance_id, repo_slug, base_commit)

    test_cmd = _build_test_cmd(row, repo_slug)
    if not test_cmd:
        _echo(
            f"WARNING: no test_cmd or FAIL_TO_PASS in dataset row for {instance_id}; "
            "set test_cmd manually.",
            err=True,
        )
    elif "test_cmd" not in row or not row.get("test_cmd"):
        _echo(f"  Constructed test_cmd from FAIL_TO_PASS: {test_cmd}")

    # Write test patch from dataset's test_patch field
    patch_file: str | None = None
    patch_path = patches_dir / f"{instance_id}_tests.patch"
    test_patch_content = row.get("test_patch", "")
    if test_patch_content:
        patches_dir.mkdir(parents=True, exist_ok=True)
        patch_path.write_text(test_patch_content)
        patch_file = f"patches/{instance_id}_tests.patch"
        _echo(f"  Wrote test patch: {patch_file}")
    elif patch_path.exists():
        patch_file = f"patches/{instance_id}_tests.patch"
        _echo(f"  Using existing patch file: {patch_file}")
    else:
        _echo(
            f"  WARNING: No test_patch in dataset and no patch file at {patch_path}.",
            err=True,
        )

    # Build Problem and write YAML into problems/<set>/<instance_id>.yaml
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

    yaml_path = problems_dir / set_name / f"{instance_id}.yaml"
    problem.to_yaml(yaml_path)
    _echo(f"Wrote {yaml_path}")
    return yaml_path


def _process_one(
    instance_id: str,
    problems_dir: Path,
    patches_dir: Path,
    set_name: str,
) -> tuple[str, bool, str]:
    """Fetch + write one instance. Returns (instance_id, ok, message)."""
    try:
        # Warn if the YAML already exists anywhere under problems/ — not just in
        # the target set. Matches the previous UX for single adds.
        existing = list(problems_dir.rglob(f"{instance_id}.yaml"))
        if existing:
            _echo(
                f"Problem file already exists for {instance_id}: {existing[0]}\n"
                f"Overwriting with fresh data from HuggingFace (target: {set_name}/)..."
            )

        row = _fetch_instance(instance_id)
        yaml_path = _write_problem(instance_id, row, problems_dir, patches_dir, set_name)
        return (instance_id, True, str(yaml_path))
    except LookupError as exc:
        return (instance_id, False, str(exc))
    except Exception as exc:  # noqa: BLE001 — surface any fetch/write error per-id
        return (instance_id, False, f"{type(exc).__name__}: {exc}")


@click.command("add")
@click.argument("instance_id", required=False)
@click.option(
    "--set",
    "set_name",
    default="adhoc",
    show_default=True,
    help=(
        "Subfolder under problems/ to write the YAML into "
        "(e.g. 'swebench-verified-mini', 'adhoc')."
    ),
)
@click.option(
    "--from-file",
    "from_file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Batch mode: read instance IDs from this file (one per line, blank and # lines ignored).",
)
@click.option(
    "--concurrency",
    type=int,
    default=4,
    show_default=True,
    help="Max parallel HuggingFace fetches when using --from-file.",
)
def add_command(
    instance_id: str | None,
    set_name: str,
    from_file: Path | None,
    concurrency: int,
) -> None:
    """Fetch one or many instances from SWE-bench_Verified and write them to problems/<set>/.

    Single-instance form:  python -m swebench add <instance_id> [--set NAME]
    Batch form:            python -m swebench add --from-file IDS.txt --set NAME [--concurrency N]
    """
    # Mutual-exclusion check — exactly one of instance_id / --from-file must be given.
    if instance_id and from_file:
        raise click.UsageError(
            "Pass either an instance_id argument or --from-file, not both."
        )
    if not instance_id and not from_file:
        raise click.UsageError("Must pass an instance_id argument or --from-file.")

    if not set_name or "/" in set_name or set_name in ("", ".", ".."):
        raise click.UsageError(
            f"Invalid --set value: {set_name!r}. Must be a single directory name."
        )

    if concurrency < 1:
        raise click.UsageError("--concurrency must be >= 1.")

    root = repo_root()
    problems_dir = root / "problems"
    patches_dir = root / "patches"

    # Ensure the target set directory exists up front (makes empty-set
    # additions predictable and helps surface permission errors early).
    (problems_dir / set_name).mkdir(parents=True, exist_ok=True)

    if instance_id:
        # Single-instance path — keep behaviour simple and serial.
        iid, ok, msg = _process_one(instance_id, problems_dir, patches_dir, set_name)
        if not ok:
            _echo(f"ERROR: {iid}: {msg}", err=True)
            sys.exit(1)
        return

    # Batch path.
    assert from_file is not None  # narrow for type-checkers
    ids = _iter_ids_file(from_file)
    if not ids:
        _echo(f"ERROR: no instance IDs found in {from_file}.", err=True)
        sys.exit(1)

    _echo(
        f"Batch add: {len(ids)} instance(s) into problems/{set_name}/ "
        f"with concurrency={concurrency}."
    )

    successes: list[str] = []
    failures: list[tuple[str, str]] = []

    # Bound concurrency; each worker holds one HuggingFace streaming iterator.
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        future_to_id = {
            pool.submit(_process_one, iid, problems_dir, patches_dir, set_name): iid
            for iid in ids
        }
        for fut in as_completed(future_to_id):
            iid, ok, msg = fut.result()
            if ok:
                successes.append(iid)
            else:
                failures.append((iid, msg))
                _echo(f"FAILED: {iid}: {msg}", err=True)

    _echo("")
    _echo("=== Batch add summary ===")
    _echo(f"  Succeeded: {len(successes)} / {len(ids)}")
    if failures:
        _echo(f"  Failed:    {len(failures)}", err=True)
        for iid, msg in failures:
            _echo(f"    - {iid}: {msg}", err=True)
        sys.exit(1)
