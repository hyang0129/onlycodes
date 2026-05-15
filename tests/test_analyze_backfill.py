"""Tests for ``analyze backfill`` (Issue #238).

The subcommand rewrites the trailing ``FAIL`` line of any ``*_test.txt`` file
whose body contains a zero-collection marker (``0 items collected``, ``no
tests ran``, ``no tests collected``) into ``env_fail``.  Idempotent and
supports ``--dry-run``.
"""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from swebench.analyze import analyze_command
from swebench.analyze.backfill import (
    _body_signals_zero_collection,
    _rewrite_text,
    _should_rewrite,
    scan_results_dir,
)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_body_marker_recognised():
    assert _body_signals_zero_collection("ran 0 items collected in 0.03s")
    assert _body_signals_zero_collection("no tests ran in 0.05s")
    assert _body_signals_zero_collection("No tests collected")
    assert _body_signals_zero_collection("Collected 0 items / 0 errors")


def test_body_without_marker_not_recognised():
    assert not _body_signals_zero_collection("collected 5 items")
    assert not _body_signals_zero_collection("ERROR: test_something")


def test_should_rewrite_requires_both_marker_and_fail_tail():
    assert _should_rewrite("ran 0 items collected\nFAIL\n")
    # Marker present but tail is PASS → no rewrite.
    assert not _should_rewrite("ran 0 items collected\nPASS\n")
    # FAIL tail but no marker → no rewrite (a real failure).
    assert not _should_rewrite("ERROR: assertion\nFAIL\n")
    # Already env_fail → no rewrite.
    assert not _should_rewrite("ran 0 items collected\nenv_fail\n")


def test_rewrite_replaces_only_the_terminal_fail():
    text = "some FAIL token in middle\n0 items collected\nFAIL\n"
    out = _rewrite_text(text)
    # Only the last FAIL becomes env_fail.
    assert out.count("env_fail") == 1
    assert out.endswith("env_fail\n")
    # The mid-text "FAIL token" is preserved (it's not on its own line).
    assert "FAIL token" in out


def test_rewrite_preserves_trailing_newline_absence():
    text = "0 items collected\nFAIL"
    out = _rewrite_text(text)
    assert out == "0 items collected\nenv_fail"


# ---------------------------------------------------------------------------
# scan_results_dir
# ---------------------------------------------------------------------------


def test_scan_picks_up_only_matching_files(tmp_path: Path):
    # Match: 0 items + FAIL tail
    (tmp_path / "a_baseline_run1_test.txt").write_text(
        "ran 0 items collected\nFAIL\n"
    )
    # No marker → skip
    (tmp_path / "b_baseline_run1_test.txt").write_text(
        "test_x failed: assertion error\nFAIL\n"
    )
    # Marker but PASS tail → skip
    (tmp_path / "c_baseline_run1_test.txt").write_text(
        "ran 0 items collected\nPASS\n"
    )
    # Already env_fail → skip
    (tmp_path / "d_baseline_run1_test.txt").write_text(
        "0 items collected\nenv_fail\n"
    )

    matches = scan_results_dir(tmp_path)
    names = {p.name for p in matches}
    assert names == {"a_baseline_run1_test.txt"}


# ---------------------------------------------------------------------------
# CLI surface — invokes the registered command end-to-end
# ---------------------------------------------------------------------------


def test_backfill_cli_dry_run_does_not_mutate(tmp_path: Path):
    f = tmp_path / "x_baseline_run1_test.txt"
    original = "ran 0 items collected\nFAIL\n"
    f.write_text(original)

    runner = CliRunner()
    result = runner.invoke(
        analyze_command,
        ["backfill", "--results-dir", str(tmp_path), "--dry-run"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert "[dry-run]" in result.output
    assert f.read_text() == original  # untouched


def test_backfill_cli_applies_rewrite(tmp_path: Path):
    f = tmp_path / "x_baseline_run1_test.txt"
    f.write_text("ran 0 items collected\nFAIL\n")

    runner = CliRunner()
    result = runner.invoke(
        analyze_command,
        ["backfill", "--results-dir", str(tmp_path)],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    # File now ends with env_fail.
    last = [line for line in f.read_text().splitlines() if line.strip()][-1]
    assert last.strip() == "env_fail"


def test_backfill_cli_is_idempotent(tmp_path: Path):
    """Running twice doesn't double-rewrite."""
    f = tmp_path / "x_baseline_run1_test.txt"
    f.write_text("ran 0 items collected\nFAIL\n")

    runner = CliRunner()
    runner.invoke(
        analyze_command,
        ["backfill", "--results-dir", str(tmp_path)],
        catch_exceptions=False,
    )
    first = f.read_text()
    result = runner.invoke(
        analyze_command,
        ["backfill", "--results-dir", str(tmp_path)],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert "No FAIL→env_fail rewrites needed" in result.output
    assert f.read_text() == first


def test_backfill_cli_empty_dir(tmp_path: Path):
    runner = CliRunner()
    result = runner.invoke(
        analyze_command,
        ["backfill", "--results-dir", str(tmp_path)],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert "No FAIL→env_fail rewrites needed" in result.output
