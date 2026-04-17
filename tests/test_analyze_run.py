"""Offline tests for ``swebench analyze pathology``.

These cover the ``--dry-run`` path, resume/skip semantics, option surface,
and Stage 3's composed synthesizer command. They never invoke the
``claude`` binary — ``find_claude_binary`` is tolerated via ``--dry-run``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from swebench.analyze import analyze_command


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "analyze" / "both_arms"


def _run(args: list[str]):
    runner = CliRunner()
    return runner.invoke(analyze_command, args, catch_exceptions=False)


def test_pathology_help_lists_all_options() -> None:
    result = _run(["pathology", "--help"])
    assert result.exit_code == 0, result.output
    out = result.output
    for opt in ("--results-dir", "--concurrency", "--force", "--dry-run",
                "--stage", "--run-id"):
        assert opt in out, f"missing {opt} in help output:\n{out}"


def test_pathology_dry_run_emits_commands_and_previews(tmp_path: Path) -> None:
    # Copy fixture jsonls into an isolated dir so we don't write _analysis/ to
    # the repo tree (even in dry-run we only read, but tmp_path keeps it tidy).
    work = tmp_path / "results"
    work.mkdir()
    for p in FIXTURES_DIR.glob("*.jsonl"):
        (work / p.name).write_text(p.read_text())

    result = _run([
        "pathology",
        "--results-dir", str(work),
        "--dry-run",
        "--run-id", "test-run",
    ])
    assert result.exit_code == 0, result.output
    out = result.output

    # Dry-run must surface composed cmd + preview but not actually invoke.
    assert "DRY RUN" in out
    assert "claude" in out  # binary path (or <claude>) appears
    assert "--allowedTools" in out
    assert "compressed preview" in out
    # Stage 3 synthesizer should also emit its own dry-run banner.
    assert "stage3 synthesizer" in out

    # Dry-run must NOT create sidecars on disk.
    analysis = work / "_analysis" / "test-run"
    assert not analysis.exists(), (
        f"dry-run unexpectedly created {analysis}"
    )


def test_pathology_resume_skip_on_second_run(tmp_path: Path) -> None:
    work = tmp_path / "results"
    work.mkdir()
    for p in FIXTURES_DIR.glob("*.jsonl"):
        (work / p.name).write_text(p.read_text())

    args = [
        "pathology",
        "--results-dir", str(work),
        "--stage", "mechanical",
        "--run-id", "resume-test",
    ]
    first = _run(args)
    assert first.exit_code == 0, first.output
    assert "[stage1] extracted" in first.output

    mech_dir = work / "_analysis" / "resume-test" / "mechanical"
    sidecars = sorted(mech_dir.glob("*.json"))
    assert sidecars, "stage 1 produced no sidecars"

    # Snapshot mtimes; the second run must not rewrite them.
    mtimes_before = {p: p.stat().st_mtime_ns for p in sidecars}

    second = _run(args)
    assert second.exit_code == 0, second.output
    assert "[stage1] skip (cached)" in second.output
    assert "[stage1] extracted" not in second.output

    mtimes_after = {p: p.stat().st_mtime_ns for p in sidecars}
    assert mtimes_before == mtimes_after, (
        "resume should be a no-op but sidecars were rewritten"
    )


def test_pathology_force_rewrites_sidecars(tmp_path: Path) -> None:
    work = tmp_path / "results"
    work.mkdir()
    for p in FIXTURES_DIR.glob("*.jsonl"):
        (work / p.name).write_text(p.read_text())

    base_args = [
        "pathology",
        "--results-dir", str(work),
        "--stage", "mechanical",
        "--run-id", "force-test",
    ]
    assert _run(base_args).exit_code == 0
    forced = _run(base_args + ["--force"])
    assert forced.exit_code == 0
    assert "[stage1] extracted" in forced.output
    assert "skip (cached)" not in forced.output


def test_pathology_triage_json_written(tmp_path: Path) -> None:
    work = tmp_path / "results"
    work.mkdir()
    for p in FIXTURES_DIR.glob("*.jsonl"):
        (work / p.name).write_text(p.read_text())

    result = _run([
        "pathology",
        "--results-dir", str(work),
        "--stage", "mechanical",
        "--run-id", "triage-test",
    ])
    assert result.exit_code == 0, result.output
    triage_path = work / "_analysis" / "triage-test" / "triage.json"
    assert triage_path.exists()
    data = json.loads(triage_path.read_text())
    assert "ranked" in data
    assert data["cutoff_count"] >= 1
    assert any(entry.get("flagged") for entry in data["ranked"])


def test_pathology_stage_synthesize_dry_run(tmp_path: Path) -> None:
    """Stage 3 synthesizer prints its composed claude command under --dry-run.

    Runs with ``--stage synthesize`` only (skipping stages 1 and 2), which
    means the synthesizer sees zero subagent outputs — but should still
    compose + display its command against the seeded repo-root registry.
    """
    work = tmp_path / "results"
    work.mkdir()
    for p in FIXTURES_DIR.glob("*.jsonl"):
        (work / p.name).write_text(p.read_text())
    result = _run([
        "pathology",
        "--results-dir", str(work),
        "--stage", "synthesize",
        "--run-id", "synth-test",
        "--dry-run",
    ])
    assert result.exit_code == 0, result.output
    assert "stage3 synthesizer" in result.output
    assert "--system-prompt" in result.output or "synthesizer_prompt" in result.output
    # Stage 3 dry-run must not mutate the repo-root patterns.json; the
    # autouse guard in conftest.py enforces this.


def test_pathology_rejects_bad_concurrency(tmp_path: Path) -> None:
    work = tmp_path / "results"
    work.mkdir()
    (work / "noop_onlycode_run1.jsonl").write_text("")
    result = _run([
        "pathology",
        "--results-dir", str(work),
        "--concurrency", "0",
    ])
    assert result.exit_code != 0
    assert "concurrency" in result.output.lower()
