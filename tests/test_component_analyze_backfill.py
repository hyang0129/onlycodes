"""Component test: analyze/__init__.py → analyze/backfill.py CLI registration.

Boundary: ``analyze/__init__.py`` registers ``backfill`` as a subcommand on the
``analyze_command`` Click group via ``_register_backfill(analyze_command)``
(added in Issue #238).  This test exercises the contract that the two real
modules cooperate correctly: ``analyze_command`` must expose the backfill
subcommand, accept ``--dry-run``, and correctly reclassify ``FAIL`` files that
contain a zero-collection marker phrase.

No doubles are used — the real ``analyze_command`` group and the real backfill
implementation run together.  The only seam doubled is the filesystem, which is
already the canonical medium between CLI and results files.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from swebench.analyze import analyze_command


@pytest.mark.component
class TestAnalyzeBackfillRegistration:
    """Verify that analyze_command exposes the backfill subcommand correctly."""

    def test_backfill_subcommand_is_reachable_through_analyze_group(self):
        """``analyze backfill --help`` must exit 0 — the subcommand is registered."""
        runner = CliRunner()
        result = runner.invoke(analyze_command, ["backfill", "--help"], catch_exceptions=False)
        assert result.exit_code == 0, f"backfill --help failed:\n{result.output}"
        assert "backfill" in result.output.lower(), (
            f"'backfill' not mentioned in its own help text: {result.output}"
        )

    def test_backfill_dry_run_flag_accepted(self, tmp_path: Path):
        """``--dry-run`` must be an accepted flag (not an 'Error: no such option')."""
        runner = CliRunner()
        result = runner.invoke(
            analyze_command,
            ["backfill", "--results-dir", str(tmp_path), "--dry-run"],
            catch_exceptions=False,
        )
        # An empty dir → "No FAIL→env_fail rewrites needed" — exit 0.
        assert result.exit_code == 0, f"Unexpected exit:\n{result.output}"
        assert "No FAIL" in result.output or "No" in result.output, (
            f"Expected no-op message; got: {result.output}"
        )

    def test_backfill_dry_run_reports_candidates_without_modifying(self, tmp_path: Path):
        """With ``--dry-run``, files that need rewriting are listed but NOT changed."""
        test_file = tmp_path / "repo__repo-1_baseline_run1_test.txt"
        original = (
            "collected 0 items / no tests ran\n"
            "\n"
            "FAIL\n"
        )
        test_file.write_text(original)

        runner = CliRunner()
        result = runner.invoke(
            analyze_command,
            ["backfill", "--results-dir", str(tmp_path), "--dry-run"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0, f"Unexpected exit:\n{result.output}"
        # dry-run output must mention the file.
        assert test_file.name in result.output, (
            f"Dry-run did not name the candidate file; output:\n{result.output}"
        )
        # File must NOT have been modified.
        assert test_file.read_text() == original, (
            "Dry-run must not modify files on disk."
        )

    def test_backfill_rewrites_fail_to_env_fail(self, tmp_path: Path):
        """Live run (no --dry-run): FAIL + zero-collection marker → env_fail."""
        test_file = tmp_path / "repo__repo-2_baseline_run1_test.txt"
        test_file.write_text(
            "--- pytest --collect-only output ---\n"
            "no tests ran in 0.05s\n"
            "--- end ---\n"
            "\n"
            "FAIL\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            analyze_command,
            ["backfill", "--results-dir", str(tmp_path)],
            catch_exceptions=False,
        )
        assert result.exit_code == 0, f"Unexpected exit:\n{result.output}"

        # Last non-empty line of the rewritten file must be "env_fail".
        lines = [ln for ln in test_file.read_text().splitlines() if ln.strip()]
        assert lines, "File is empty after rewrite"
        assert lines[-1].strip() == "env_fail", (
            f"Expected last non-empty line 'env_fail'; got {lines[-1]!r}"
        )

    def test_backfill_does_not_touch_pass_files(self, tmp_path: Path):
        """Files whose last line is PASS must be left entirely unchanged."""
        pass_file = tmp_path / "repo__repo-3_onlycode_run1_test.txt"
        original = "tests ran fine\n\nPASS\n"
        pass_file.write_text(original)

        runner = CliRunner()
        result = runner.invoke(
            analyze_command,
            ["backfill", "--results-dir", str(tmp_path)],
            catch_exceptions=False,
        )
        assert result.exit_code == 0, f"Unexpected exit:\n{result.output}"
        assert pass_file.read_text() == original, (
            "PASS file was incorrectly modified by backfill."
        )

    def test_backfill_idempotent_on_already_env_fail(self, tmp_path: Path):
        """Re-running backfill on an already-rewritten file is a no-op."""
        already_done = tmp_path / "repo__repo-4_baseline_run1_test.txt"
        already_done.write_text(
            "0 items collected\n"
            "\n"
            "env_fail\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            analyze_command,
            ["backfill", "--results-dir", str(tmp_path)],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        # Should report no rewrites needed.
        assert "No FAIL" in result.output or "0 file" in result.output, (
            f"Expected idempotent no-op message; got: {result.output}"
        )
