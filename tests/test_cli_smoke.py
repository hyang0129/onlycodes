"""CLI smoke tests — `--help` on every top-level command must exit 0.

Guards against import-time regressions in the `swebench` Click tree. If any
submodule fails to import, Click dispatch will surface a non-zero exit code
from `--help`, making this a cheap canary.

Sub-issue #70 of epic #62 (log analysis pipeline).
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from swebench.cli import cli


@pytest.mark.parametrize("subcommand", ["add", "run", "analyze", "cache"])
def test_top_level_help_exits_zero(subcommand: str) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, [subcommand, "--help"], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    assert "Usage:" in result.output


def test_root_help_exits_zero() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    for sub in ("add", "run", "analyze", "cache"):
        assert sub in result.output


def test_analyze_summary_help_exits_zero() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["analyze", "summary", "--help"], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    assert "--results-dir" in result.output
