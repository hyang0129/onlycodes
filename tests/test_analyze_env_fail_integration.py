"""Integration tests for the env_fail verdict flow — Issue #238.

Scenario: slice-analyze-env-fail-cli
Tier: wiring

Verifies the full vertical slice from CLI registration through output
for the two new CLI surfaces added in issue #238:

  1. ``swebench analyze backfill`` — rewrites historical FAIL→env_fail in
     a results directory.
  2. ``swebench analyze summary`` — renders env_fail as its own column
     and excludes it from the pass-rate denominator.

The tests exercise:
  - CLI schema wiring: ``analyze backfill`` is registered under ``analyze``,
    ``--help`` is reachable, required options are present, invalid args
    are rejected.
  - End-to-end backfill → summary flow: running ``analyze backfill`` on a
    synthetic results dir with a historical FAIL file, then running
    ``analyze summary`` on the same dir, produces the env_fail column.
  - Cross-command contract: the env_fail verdict written by ``backfill``
    is consumed correctly by ``summary`` — both commands agree on the
    verdict string ``env_fail``.
  - Idempotency: running ``backfill`` twice does not double-rewrite;
    ``summary`` output is stable.

These tests are fully offline — no ``claude`` binary, no subprocess I/O to
real repos, no Docker containers. CliRunner invokes the Click tree directly.
Per-test budget is well under 5 s.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from swebench.analyze import analyze_command
from swebench.cli import cli


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SYMPY_INSTANCE = "sympy__sympy-14180"
ARM = "baseline"
RUN = 1


def _make_historical_fail_file(results_dir: Path) -> Path:
    """Create a synthetic *_test.txt that looks like a pre-#238 env failure."""
    test_txt = results_dir / f"{SYMPY_INSTANCE}_{ARM}_run{RUN}_test.txt"
    test_txt.write_text(
        "=== pytest ===\n"
        "no tests ran in 0.05s\n"
        "0 items collected\n"
        "FAIL\n"
    )
    return test_txt


def _make_historical_fail_jsonl(results_dir: Path) -> Path:
    """Create a minimal companion JSONL for the synthetic failure."""
    jsonl = results_dir / f"{SYMPY_INSTANCE}_{ARM}_run{RUN}.jsonl"
    jsonl.write_text('{"type": "result", "total_cost_usd": 0.42, "num_turns": 5}\n')
    return jsonl


def _make_historical_real_fail(results_dir: Path, instance_id: str) -> None:
    """Create a genuine FAIL test file (no zero-collection marker)."""
    test_txt = results_dir / f"{instance_id}_{ARM}_run{RUN}_test.txt"
    test_txt.write_text(
        "=== pytest ===\n"
        "test_something FAILED - AssertionError\n"
        "FAIL\n"
    )
    jsonl = results_dir / f"{instance_id}_{ARM}_run{RUN}.jsonl"
    jsonl.write_text('{"type": "result", "total_cost_usd": 0.10, "num_turns": 3}\n')


# ---------------------------------------------------------------------------
# Step 1 — CLI Schema Wiring (analyze backfill registration)
# ---------------------------------------------------------------------------


class TestBackfillCliSchema:
    """Wiring: verify analyze backfill is registered and schema is correct."""

    def test_analyze_help_lists_backfill_command(self):
        """``swebench analyze --help`` must list ``backfill`` as a subcommand."""
        runner = CliRunner()
        result = runner.invoke(analyze_command, ["--help"], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        assert "backfill" in result.output

    def test_analyze_backfill_help_exits_zero(self):
        """``swebench analyze backfill --help`` must succeed."""
        runner = CliRunner()
        result = runner.invoke(
            analyze_command, ["backfill", "--help"], catch_exceptions=False
        )
        assert result.exit_code == 0, result.output
        assert "Usage:" in result.output

    def test_analyze_backfill_help_shows_results_dir_option(self):
        """``--results-dir`` option must be documented in backfill --help."""
        runner = CliRunner()
        result = runner.invoke(
            analyze_command, ["backfill", "--help"], catch_exceptions=False
        )
        assert result.exit_code == 0, result.output
        assert "--results-dir" in result.output

    def test_analyze_backfill_help_shows_dry_run_option(self):
        """``--dry-run`` option must be documented in backfill --help."""
        runner = CliRunner()
        result = runner.invoke(
            analyze_command, ["backfill", "--help"], catch_exceptions=False
        )
        assert result.exit_code == 0, result.output
        assert "--dry-run" in result.output

    def test_backfill_reachable_via_top_level_cli(self):
        """``python -m swebench analyze backfill --help`` via the root CLI."""
        runner = CliRunner()
        result = runner.invoke(
            cli, ["analyze", "backfill", "--help"], catch_exceptions=False
        )
        assert result.exit_code == 0, result.output
        assert "backfill" in result.output.lower() or "results-dir" in result.output

    def test_backfill_nonexistent_results_dir_fails(self, tmp_path: Path):
        """``--results-dir`` pointing to a non-existent path must fail."""
        runner = CliRunner()
        missing = tmp_path / "does-not-exist"
        result = runner.invoke(
            analyze_command,
            ["backfill", "--results-dir", str(missing)],
            catch_exceptions=False,
        )
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Step 2 — End-to-End Backfill → Summary Flow
# ---------------------------------------------------------------------------


class TestBackfillToSummaryFlow:
    """Wiring: verify backfill rewrites FAIL→env_fail and summary renders it."""

    def test_backfill_rewrites_zero_collection_fail(self, tmp_path: Path):
        """After backfill runs, the historical FAIL file ends with env_fail."""
        _make_historical_fail_file(tmp_path)
        _make_historical_fail_jsonl(tmp_path)

        runner = CliRunner()
        result = runner.invoke(
            analyze_command,
            ["backfill", "--results-dir", str(tmp_path)],
            catch_exceptions=False,
        )
        assert result.exit_code == 0, result.output

        test_txt = tmp_path / f"{SYMPY_INSTANCE}_{ARM}_run{RUN}_test.txt"
        lines = [ln for ln in test_txt.read_text().splitlines() if ln.strip()]
        assert lines[-1].strip() == "env_fail", (
            f"Last non-empty line must be env_fail; got {lines[-1]!r}"
        )

    def test_summary_after_backfill_shows_env_fail(self, tmp_path: Path):
        """After backfill, ``analyze summary`` must include env_fail in output."""
        _make_historical_fail_file(tmp_path)
        _make_historical_fail_jsonl(tmp_path)

        runner = CliRunner()
        # Run backfill first.
        runner.invoke(
            analyze_command,
            ["backfill", "--results-dir", str(tmp_path)],
            catch_exceptions=False,
        )
        # Then summary.
        result = runner.invoke(
            analyze_command,
            ["summary", "--results-dir", str(tmp_path)],
            catch_exceptions=False,
        )
        assert result.exit_code == 0, result.output
        assert "env_fail" in result.output

    def test_summary_after_backfill_excludes_env_fail_from_pass_rate(
        self, tmp_path: Path
    ):
        """env_fail must appear in the aggregate footer, excluded from denominator."""
        _make_historical_fail_file(tmp_path)
        _make_historical_fail_jsonl(tmp_path)

        runner = CliRunner()
        runner.invoke(
            analyze_command,
            ["backfill", "--results-dir", str(tmp_path)],
            catch_exceptions=False,
        )
        result = runner.invoke(
            analyze_command,
            ["summary", "--results-dir", str(tmp_path)],
            catch_exceptions=False,
        )
        assert result.exit_code == 0, result.output
        assert "Per-arm aggregates" in result.output
        assert "env_fail=1" in result.output
        assert "denominator=0" in result.output

    def test_backfill_does_not_touch_genuine_fail(self, tmp_path: Path):
        """A genuine test failure (no zero-collection marker) must not be rewritten."""
        real_fail_id = "django__django-99999"
        _make_historical_real_fail(tmp_path, real_fail_id)

        runner = CliRunner()
        runner.invoke(
            analyze_command,
            ["backfill", "--results-dir", str(tmp_path)],
            catch_exceptions=False,
        )

        test_txt = tmp_path / f"{real_fail_id}_{ARM}_run{RUN}_test.txt"
        lines = [ln for ln in test_txt.read_text().splitlines() if ln.strip()]
        assert lines[-1].strip() == "FAIL", (
            f"Genuine FAIL must not be rewritten; got {lines[-1]!r}"
        )

    def test_summary_after_backfill_preserves_genuine_fail_count(
        self, tmp_path: Path
    ):
        """Genuine FAILs must still appear in the pass-rate denominator after backfill."""
        # One zero-collection historical FAIL + one genuine FAIL.
        _make_historical_fail_file(tmp_path)
        _make_historical_fail_jsonl(tmp_path)
        real_fail_id = "django__django-99999"
        _make_historical_real_fail(tmp_path, real_fail_id)

        runner = CliRunner()
        runner.invoke(
            analyze_command,
            ["backfill", "--results-dir", str(tmp_path)],
            catch_exceptions=False,
        )
        result = runner.invoke(
            analyze_command,
            ["summary", "--results-dir", str(tmp_path)],
            catch_exceptions=False,
        )
        assert result.exit_code == 0, result.output
        # The genuine FAIL contributes to the denominator.
        assert "fail=1" in result.output
        assert "denominator=1" in result.output

    def test_summary_output_has_env_fail_column_structure(self, tmp_path: Path):
        """``analyze summary`` stdout must include the per-arm aggregates section."""
        _make_historical_fail_file(tmp_path)
        _make_historical_fail_jsonl(tmp_path)

        runner = CliRunner()
        runner.invoke(
            analyze_command,
            ["backfill", "--results-dir", str(tmp_path)],
            catch_exceptions=False,
        )
        result = runner.invoke(
            analyze_command,
            ["summary", "--results-dir", str(tmp_path)],
            catch_exceptions=False,
        )
        assert result.exit_code == 0, result.output
        # Schema assertions: required structural fields in output.
        assert "instance_id" in result.output
        assert "verdict" in result.output
        assert "pass_rate" in result.output


# ---------------------------------------------------------------------------
# Step 3 — Idempotency
# ---------------------------------------------------------------------------


class TestBackfillIdempotency:
    """Wiring: verify backfill can be run twice without corrupting the result."""

    def test_double_backfill_is_stable(self, tmp_path: Path):
        """Running backfill twice leaves the file in the same env_fail state."""
        _make_historical_fail_file(tmp_path)
        _make_historical_fail_jsonl(tmp_path)
        test_txt = tmp_path / f"{SYMPY_INSTANCE}_{ARM}_run{RUN}_test.txt"

        runner = CliRunner()
        runner.invoke(
            analyze_command,
            ["backfill", "--results-dir", str(tmp_path)],
            catch_exceptions=False,
        )
        content_after_first = test_txt.read_text()

        result = runner.invoke(
            analyze_command,
            ["backfill", "--results-dir", str(tmp_path)],
            catch_exceptions=False,
        )
        assert result.exit_code == 0, result.output
        assert "No FAIL" in result.output or "no FAIL" in result.output.lower()
        assert test_txt.read_text() == content_after_first

    def test_summary_stable_after_double_backfill(self, tmp_path: Path):
        """``analyze summary`` output is identical after one and two backfill runs."""
        _make_historical_fail_file(tmp_path)
        _make_historical_fail_jsonl(tmp_path)

        runner = CliRunner()
        runner.invoke(
            analyze_command,
            ["backfill", "--results-dir", str(tmp_path)],
            catch_exceptions=False,
        )
        first_summary = runner.invoke(
            analyze_command,
            ["summary", "--results-dir", str(tmp_path)],
            catch_exceptions=False,
        )
        runner.invoke(
            analyze_command,
            ["backfill", "--results-dir", str(tmp_path)],
            catch_exceptions=False,
        )
        second_summary = runner.invoke(
            analyze_command,
            ["summary", "--results-dir", str(tmp_path)],
            catch_exceptions=False,
        )
        assert first_summary.output == second_summary.output


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
