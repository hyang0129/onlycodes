"""Cache warm-up and teardown CLI.

Exposes two subcommands under ``python -m swebench cache``:

- ``setup``: iterate every problem YAML, build the bare-repo cache, clone +
  checkout + venv + editable install, scrub, and write a pip-freeze lockfile.
  Safe to run overnight. Skips instances that are already cached unless
  ``--force`` is passed.
- ``clean``: remove cached instance snapshots.

The commands only depend on ``swebench.cache`` and ``swebench.harness`` — they
do NOT import ``swebench.run`` (which would introduce a circular dependency
once ``run`` starts calling into the cache).
"""

from __future__ import annotations

import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import click

from swebench import repo_root
from swebench.cache import (
    bare_repo_path,
    cache_paths,
    has_cached_instance,
    instances_dir,
    repos_dir,
    scrub_cache_dir,
    write_lockfile,
)
from swebench.harness import (
    clone_bare_repo,
    clone_from_bare,
    git_reset,
    setup_venv,
)
from swebench.models import Problem


# Serialise stdout across parallel workers.
_print_lock = threading.Lock()


def _echo(msg: str, *, err: bool = False) -> None:
    with _print_lock:
        click.echo(msg, err=err)


def _load_problems(filter_ids: str | None) -> list[Problem]:
    root = repo_root()
    problems_dir = root / "problems" / "swe"
    yaml_files = sorted(problems_dir.rglob("*.yaml"))
    if not yaml_files:
        click.echo(
            "ERROR: No problem files found in problems/swe/. "
            "Run 'python -m swebench add' first.",
            err=True,
        )
        sys.exit(1)

    problems = [Problem.from_yaml(f) for f in yaml_files]
    if filter_ids:
        wanted = {s.strip() for s in filter_ids.split(",") if s.strip()}
        problems = [p for p in problems if p.instance_id in wanted]
        if not problems:
            click.echo(
                f"ERROR: No matching problems for --filter: {filter_ids}",
                err=True,
            )
            sys.exit(1)
    return problems


def _setup_one(problem: Problem, *, force: bool) -> tuple[str, bool, str]:
    """Build the cache for one instance. Returns (id, ok, message)."""
    instance_id = problem.instance_id
    paths = cache_paths(instance_id)

    if not force and has_cached_instance(instance_id):
        return (instance_id, True, "already cached (skip)")

    started = time.time()
    try:
        # On --force, clear any stale lockfile up front so a half-rebuilt
        # cache never looks valid to verify_lockfile on a later run.
        if force:
            Path(paths["lockfile"]).unlink(missing_ok=True)

        # 1. Bare repo
        bare = str(bare_repo_path(problem.repo_slug))
        clone_bare_repo(problem.repo_slug, bare)

        # 2. Working tree from bare
        repo_dir = paths["repo"]
        # If --force and repo exists, nuke it first
        if force and Path(repo_dir).exists():
            shutil.rmtree(repo_dir, ignore_errors=True)
        clone_from_bare(bare, repo_dir)

        # 3. Checkout base commit
        git_reset(repo_dir, problem.base_commit)

        # 4. Venv + editable install
        venv_dir = paths["venv"]
        if force and Path(venv_dir).exists():
            shutil.rmtree(venv_dir, ignore_errors=True)
        setup_venv(venv_dir, repo_dir)

        # 5. Scrub transient artifacts
        scrub_cache_dir(repo_dir)

        # 6. Write lockfile
        write_lockfile(venv_dir, paths["lockfile"])

        elapsed = int(time.time() - started)
        return (instance_id, True, f"built in {elapsed}s")
    except Exception as exc:  # noqa: BLE001 — per-instance isolation
        return (instance_id, False, f"{type(exc).__name__}: {exc}")


@click.group("cache")
def cache_group() -> None:
    """Manage the OverlayFS instance cache."""


@cache_group.command("setup")
@click.option(
    "--filter",
    "filter_ids",
    default=None,
    help="Comma-separated instance IDs to warm up (default: every problem in problems/swe/).",
)
@click.option(
    "--concurrency",
    type=int,
    default=4,
    show_default=True,
    help="Max instances to build in parallel.",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Rebuild even if a cache entry already exists.",
)
def setup(filter_ids: str | None, concurrency: int, force: bool) -> None:
    """Pre-build the instance cache.

    Produces ``/workspaces/.swebench-cache/instances/<id>/`` for each problem,
    each containing ``repo/`` (scrubbed working tree at base commit),
    ``venv/`` (python3.11 + editable install), and ``lockfile.txt``.
    """
    if concurrency < 1:
        click.echo("ERROR: --concurrency must be >= 1.", err=True)
        sys.exit(1)

    problems = _load_problems(filter_ids)

    # Ensure top-level dirs exist so first-run errors surface clearly.
    repos_dir().mkdir(parents=True, exist_ok=True)
    instances_dir().mkdir(parents=True, exist_ok=True)

    _echo(
        f"cache setup: {len(problems)} instance(s), concurrency={concurrency}, "
        f"force={force}"
    )

    successes: list[str] = []
    failures: list[tuple[str, str]] = []

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {
            pool.submit(_setup_one, p, force=force): p.instance_id for p in problems
        }
        for fut in as_completed(futures):
            iid, ok, msg = fut.result()
            if ok:
                successes.append(iid)
                _echo(f"  {iid}: {msg}")
            else:
                failures.append((iid, msg))
                _echo(f"FAILED: {iid}: {msg}", err=True)

    _echo("")
    _echo("=== cache setup summary ===")
    _echo(f"  Succeeded: {len(successes)} / {len(problems)}")
    if failures:
        _echo(f"  Failed:    {len(failures)}", err=True)
        for iid, msg in failures:
            _echo(f"    - {iid}: {msg}", err=True)
        sys.exit(1)


@cache_group.command("clean")
@click.option(
    "--filter",
    "filter_ids",
    default=None,
    help="Comma-separated instance IDs to remove (default: every cached instance).",
)
@click.option(
    "--yes",
    is_flag=True,
    default=False,
    help="Skip confirmation prompt.",
)
@click.option(
    "--include-bare",
    is_flag=True,
    default=False,
    help="Also remove the bare-repo cache under repos/ (frees disk but forces re-download).",
)
def clean(filter_ids: str | None, yes: bool, include_bare: bool) -> None:
    """Remove cached instance snapshots."""
    targets: list[Path] = []
    inst_root = instances_dir()
    if not inst_root.is_dir():
        click.echo(f"No cache at {inst_root}; nothing to clean.")
        return

    if filter_ids:
        wanted = {s.strip() for s in filter_ids.split(",") if s.strip()}
        for name in wanted:
            p = inst_root / name
            if p.is_dir():
                targets.append(p)
            else:
                click.echo(f"  {name}: not cached (skip)")
    else:
        targets = [p for p in inst_root.iterdir() if p.is_dir()]

    if not targets and not include_bare:
        click.echo("Nothing to remove.")
        return

    # Guard: refuse to remove the bare-repo cache while any instance caches
    # still reference it via .git/objects/info/alternates (written by
    # `git clone --shared`).  Removing the bare repo first would make every
    # subsequent git operation on those instances fail with "object not found".
    # We allow --include-bare only when the clean operation also removes ALL
    # instance directories (i.e. no --filter was given).
    if include_bare and filter_ids is not None:
        # Check whether any instance dirs remain after the targeted removal.
        all_instance_dirs = {p for p in inst_root.iterdir() if p.is_dir()} if inst_root.is_dir() else set()
        remaining = all_instance_dirs - set(targets)
        if remaining:
            click.echo(
                "ERROR: Cannot remove bare-repo cache while instance caches still "
                "reference it via git alternates.\n"
                "Run `cache clean --yes` (without --filter) first to remove all "
                "instance caches, or omit --include-bare.",
                err=True,
            )
            sys.exit(1)

    if not yes:
        click.echo(f"About to remove {len(targets)} cached instance(s):")
        for t in targets:
            click.echo(f"  - {t}")
        if include_bare:
            click.echo(f"  (also removing bare repos under {repos_dir()})")
        click.confirm("Proceed?", abort=True)

    for t in targets:
        shutil.rmtree(t, ignore_errors=True)
        click.echo(f"  removed {t}")

    if include_bare:
        br = repos_dir()
        if br.is_dir():
            shutil.rmtree(br, ignore_errors=True)
            click.echo(f"  removed {br}")

    click.echo("Done.")
