"""`analyze backfill` — reclassify historical ``FAIL`` results as ``env_fail``.

Issue #238 / #234: before the pre-flight ``pytest --collect-only`` check was
added, a run that collected 0 items was scored ``FAIL`` because pytest exited
non-zero.  Those runs were never failures in the sense the benchmark cares
about — there were simply no tests to run.  This subcommand walks
``*_test.txt`` files in a results dir, identifies the ones where the body
contains ``0 items collected`` (or pytest's "no tests ran" / "no tests
collected" phrases) **and** the last non-empty line is ``FAIL``, and rewrites
the last line to ``env_fail``.

The rewrite is idempotent — files whose last line is already ``env_fail`` are
skipped — and supports ``--dry-run`` so an operator can preview the change set
before committing.
"""

from __future__ import annotations

import re
from pathlib import Path

import click

from swebench import repo_root


# Phrases pytest emits when zero items are collected.  We match any of them
# in the body of the test file to gate the FAIL→env_fail rewrite.  All
# matches are case-insensitive against the verbatim text — these are pytest's
# own strings and have not changed across recent releases.
_ZERO_COLLECTION_MARKERS: tuple[str, ...] = (
    "0 items collected",
    "no tests ran",
    "no tests collected",
    "collected 0 items",
)


def _body_signals_zero_collection(text: str) -> bool:
    """Return True if *text* contains any zero-collection marker phrase."""
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in _ZERO_COLLECTION_MARKERS)


def _last_non_empty_line(lines: list[str]) -> tuple[int, str] | None:
    """Return ``(index, stripped)`` of the last non-empty line, or None."""
    for i in range(len(lines) - 1, -1, -1):
        s = lines[i].strip()
        if s:
            return i, s
    return None


def _should_rewrite(text: str) -> bool:
    """Return True if *text* should be rewritten FAIL → env_fail."""
    lines = text.splitlines()
    last = _last_non_empty_line(lines)
    if last is None:
        return False
    _, stripped = last
    if stripped != "FAIL":
        return False
    return _body_signals_zero_collection(text)


def _rewrite_text(text: str) -> str:
    """Return *text* with the last ``FAIL`` line replaced by ``env_fail``.

    Assumes :func:`_should_rewrite` returned True for *text*.  The trailing
    newline (if any) is preserved.
    """
    # Replace the last FAIL token in the text.  We rsplit on newlines so the
    # final terminator (``\n`` or absent) is preserved.
    # Find the last index of a line equal to ``FAIL`` (stripped).
    lines = text.splitlines(keepends=True)
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip() == "FAIL":
            # Preserve original line ending if present.
            terminator = "\n" if lines[i].endswith("\n") else ""
            lines[i] = "env_fail" + terminator
            break
    return "".join(lines)


def scan_results_dir(rdir: Path) -> list[Path]:
    """Return ``*_test.txt`` files in *rdir* that need FAIL→env_fail rewrite."""
    candidates: list[Path] = []
    for test_file in sorted(rdir.glob("*_test.txt")):
        try:
            text = test_file.read_text()
        except OSError:
            continue
        if _should_rewrite(text):
            candidates.append(test_file)
    return candidates


def _register(analyze_command: click.Group) -> None:
    """Register the `backfill` subcommand on the given analyze group."""

    @analyze_command.command("backfill")
    @click.option(
        "--results-dir",
        type=click.Path(exists=True, file_okay=False, path_type=Path),
        default=None,
        help="Path to results directory (default: auto-detect runs/swebench/).",
    )
    @click.option(
        "--dry-run",
        is_flag=True,
        default=False,
        help="Print which files would be rewritten without modifying them.",
    )
    def backfill_command(results_dir: Path | None, dry_run: bool) -> None:
        """Reclassify historical 0-items-collected FAILs as env_fail.

        Walks ``*_test.txt`` files under ``--results-dir`` (default:
        ``runs/swebench/``).  A file is rewritten iff its body contains a
        zero-collection marker (``0 items collected`` / ``no tests ran`` /
        ``no tests collected``) AND its last non-empty line is ``FAIL``.
        The rewrite replaces that last ``FAIL`` with ``env_fail``.
        """
        rdir = Path(results_dir) if results_dir else (repo_root() / "runs" / "swebench")
        if not rdir.is_dir():
            click.echo(f"ERROR: Results directory not found: {rdir}", err=True)
            raise SystemExit(1)

        candidates = scan_results_dir(rdir)
        if not candidates:
            click.echo(f"No FAIL→env_fail rewrites needed in {rdir}/")
            return

        action = "Would rewrite" if dry_run else "Rewrote"
        for test_file in candidates:
            if dry_run:
                click.echo(f"  [dry-run] {test_file.name}")
            else:
                original = test_file.read_text()
                test_file.write_text(_rewrite_text(original))
                click.echo(f"  rewrote {test_file.name}")

        click.echo(f"\n{action} {len(candidates)} file(s).")
        if dry_run:
            click.echo("(Run without --dry-run to apply.)")
