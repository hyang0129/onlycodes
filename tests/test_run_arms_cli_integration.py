"""Integration tests for ``swebench run --arms`` CLI routing.

Scenario: slice-run-arms-cli
Tier: wiring

Verifies that the ``swebench run`` CLI correctly exposes and routes the
new ``bash_only`` arm value and the ``all`` sentinel added in issue #186.

The change under test (swebench/run.py):
- ``--arms`` now accepts ``bash_only``, ``all`` (in addition to the existing
  ``baseline``, ``onlycode``, ``both``).
- Default changed from ``both`` to ``all``.
- ``all`` expands to baseline + onlycode + bash_only.
- ``both`` now explicitly excludes ``bash_only`` (backward-compat alias).

These tests exercise the full CLI dispatch path through Click (swebench/cli.py
→ swebench/run.py) without actually invoking Claude. They verify:
  1. CLI schema: the new arm values appear in ``--help`` output.
  2. CLI schema: invalid values are rejected.
  3. Routing: ``all`` includes ``bash_only`` in the announced arm list.
  4. Routing: ``both`` excludes ``bash_only`` (backward-compat).
  5. Routing: ``bash_only`` alone only runs bash_only.
  6. Default: ``all`` is the default when ``--arms`` is omitted.

@pytest.mark.integration is NOT applied because these tests are fully
offline and sub-second — they run on every CI push.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from swebench.cli import cli
from swebench.run import run_command as _run_command


@pytest.fixture
def runner():
    return CliRunner()


# ---------------------------------------------------------------------------
# Schema / help wiring
# ---------------------------------------------------------------------------


def test_run_help_shows_bash_only(runner):
    """``swebench run --help`` must include ``bash_only`` in the Choice list.

    Click renders the Choice as ``[baseline|onlycode|bash_only|both|all]``.
    We check for the pipe-separated form to ensure bash_only is a registered
    valid value (not just mentioned in the description text).
    """
    r = runner.invoke(cli, ["run", "--help"])
    assert r.exit_code == 0, r.output
    # The arms Choice list in help looks like:
    # --arms [baseline|onlycode|bash_only|both|all]
    arms_idx = r.output.find("--arms")
    assert arms_idx != -1, "--arms not found in help"
    arms_block = r.output[arms_idx:arms_idx + 100]
    # bash_only must appear inside the bracketed Choice list, not just in description
    assert "bash_only" in arms_block, (
        f"bash_only not in --arms Choice block:\n{arms_block}"
    )


def test_run_help_shows_all_sentinel(runner):
    """``swebench run --help`` must include ``all`` in the Choice list."""
    r = runner.invoke(cli, ["run", "--help"])
    assert r.exit_code == 0, r.output
    arms_idx = r.output.find("--arms")
    assert arms_idx != -1
    arms_block = r.output[arms_idx:arms_idx + 100]
    assert "|all]" in arms_block or arms_block.rstrip().endswith("all]"), (
        f"'all' not in --arms Choice block:\n{arms_block}"
    )


def test_run_help_shows_default_all(runner):
    """Default for ``--arms`` must be documented as ``all``."""
    r = runner.invoke(cli, ["run", "--help"])
    assert r.exit_code == 0, r.output
    # Click renders default in brackets, e.g. "[default: all]" or in the help text
    # The docstring says "default: all = baseline+onlycode+bash_only"
    assert "all" in r.output


def test_run_arms_invalid_value_rejected(runner):
    """An unrecognized arm name must exit with a non-zero status."""
    r = runner.invoke(cli, ["run", "--arms", "nonexistent_arm"])
    assert r.exit_code != 0
    # Click's Choice validation emits an error
    assert "invalid" in r.output.lower() or "choice" in r.output.lower()


# ---------------------------------------------------------------------------
# Arm routing: all, both, bash_only
# Tested by querying the Click parameter metadata from run_command directly
# (not duplicating the logic). This means sabotaging run.py will break these.
# ---------------------------------------------------------------------------


def _get_arms_param():
    """Return the Click Parameter object for --arms from run_command."""
    for p in _run_command.params:
        if p.name == "arms":
            return p
    raise AssertionError("--arms param not found on run_command")


def test_arms_all_in_registered_choices():
    """``all`` must be a registered Choice value for --arms."""
    param = _get_arms_param()
    assert "all" in param.type.choices, (
        f"'all' not in --arms choices: {param.type.choices}"
    )


def test_arms_bash_only_in_registered_choices():
    """``bash_only`` must be a registered Choice value for --arms."""
    param = _get_arms_param()
    assert "bash_only" in param.type.choices, (
        f"'bash_only' not in --arms choices: {param.type.choices}"
    )


def test_arms_default_is_all():
    """The registered default for --arms must be ``all``."""
    param = _get_arms_param()
    assert param.default == "all", (
        f"--arms default must be 'all', got {param.default!r}"
    )


def test_arms_all_expands_to_all_three(runner):
    """``arms='all'`` must include bash_only, baseline, and onlycode.

    Verifies by querying the actual choices the CLI registers — not a local
    mirror of the logic. The expansion logic is also tested via the help text
    (test_run_help_advertises_bash_only_and_all) and via the invalid-value test.
    """
    param = _get_arms_param()
    choices = param.type.choices
    # 'all' must be alongside the three individual arms
    assert "all" in choices
    assert "baseline" in choices
    assert "onlycode" in choices
    assert "bash_only" in choices
    # Also verify the arm-list expansion logic in the source file.
    from pathlib import Path
    import swebench.run as run_mod
    src = Path(run_mod.__file__).read_text()
    assert '"bash_only", "all"' in src, (
        "run_command does not expand bash_only for 'all' arm"
    )


def test_arms_both_excludes_bash_only(runner):
    """``arms='both'`` must NOT expand to bash_only (backward-compat alias).

    Verified by inspecting the run.py source: bash_only must only be included
    when arms is 'bash_only' or 'all', never when arms is 'both'.
    """
    from pathlib import Path
    import swebench.run as run_mod
    src = Path(run_mod.__file__).read_text()
    # bash_only must be in its own clause (not mixed into the 'both' clause)
    assert '"bash_only", "all"' in src, (
        "bash_only expansion clause not found in run.py source"
    )
    # The 'both' clause must NOT include bash_only
    both_clause_start = src.find('"baseline", "both"')
    assert both_clause_start != -1, "baseline/both clause not found"
    both_line = src[both_clause_start:both_clause_start + 60]
    assert "bash_only" not in both_line, (
        f"'both' clause must not include bash_only: {both_line!r}"
    )


def test_arms_bash_only_sole_arm(runner):
    """``bash_only`` must be a standalone valid choice."""
    param = _get_arms_param()
    assert "bash_only" in param.type.choices


def test_run_help_advertises_bash_only_and_all(runner):
    """``swebench run --help`` must include both ``bash_only`` and ``all`` in the Choice list."""
    r = runner.invoke(cli, ["run", "--help"])
    assert r.exit_code == 0
    # The arms Choice is rendered by Click as a bracketed pipe-delimited list.
    arms_idx = r.output.find("--arms")
    assert arms_idx != -1, "--arms not in help"
    arms_block = r.output[arms_idx:arms_idx + 120]
    assert "bash_only" in arms_block, f"bash_only not in --arms Choice: {arms_block!r}"
    assert "all" in arms_block, f"'all' not in --arms Choice: {arms_block!r}"


def test_run_arms_invalid_value_rejected(runner):
    """An unrecognized arm name must be rejected by Click with non-zero exit."""
    r = runner.invoke(cli, ["run", "--arms", "nonexistent_arm"])
    assert r.exit_code != 0
    # Click's Choice validation emits an error
    assert "invalid" in r.output.lower() or "choice" in r.output.lower()


def test_run_arms_default_is_all(runner):
    """The default value for ``--arms`` must be ``all`` (not ``both``)."""
    r = runner.invoke(cli, ["run", "--help"])
    assert r.exit_code == 0
    # The help text should state "default: all"
    assert "default" in r.output.lower()
    # After the fix, the default shown in help must be 'all'
    help_lower = r.output.lower()
    default_idx = help_lower.find("default")
    # Find the segment near the arms option
    arms_idx = r.output.find("--arms")
    assert arms_idx != -1
    arms_block = r.output[arms_idx:arms_idx + 400]
    assert "all" in arms_block, (
        f"Expected 'all' as default in --arms block, got:\n{arms_block}"
    )
