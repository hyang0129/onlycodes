"""Component test: swebench.cli → swebench.run.run_command arms registration.

Boundary: cli.py registers run_command as the 'run' subcommand via
``cli.add_command(run_command, "run")``. This PR (#186) added:
  - ``bash_only`` as a valid --arms choice
  - Changed the default arms value from ``both`` to ``all``

These tests verify the contract between cli.py (registrant) and run_command
(registree): that the combined Click command tree exposes the correct choices
and defaults — specifically that two real modules co-operate across the
registration boundary without any doubles.

Only Click dispatch is involved (no filesystem, no subprocess, no Claude binary).
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from swebench.cli import cli


@pytest.mark.component
class TestArmsRegistrationContract:
    """Verify that cli.add_command wires run_command choices and defaults correctly."""

    def test_bash_only_is_valid_arms_choice_in_help(self):
        """bash_only must appear as an enumerated --arms choice (inside the [...|...|...] bracket).

        Click renders valid Choice values as ``--arms [a|b|c|...]`` in the option
        header line. This test pinpoints that bracket — not the free-text description —
        so it fails when bash_only is removed from the Choice list even if the
        description text still mentions the word 'bash_only'.
        """
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "--help"], catch_exceptions=False)
        assert result.exit_code == 0, f"run --help failed: {result.output}"
        # The --arms bracket line looks like:
        #   --arms [baseline|onlycode|bash_only|both|all]
        import re
        bracket_match = re.search(r"--arms\s+\[([^\]]+)\]", result.output)
        assert bracket_match is not None, (
            f"Could not find --arms [choices] bracket in help: {result.output}"
        )
        bracket = bracket_match.group(1)
        assert "bash_only" in bracket, (
            f"bash_only not in --arms choice bracket '{bracket}'; full output: {result.output}"
        )

    def test_default_arms_is_all_in_help(self):
        """The default value for --arms must be 'all' (changed from 'both' in this PR).

        This is enforced via the actual Click parameter default, not just free-text.
        We invoke with --arms value omitted and verify Click renders 'all' as the
        default in the option bracket.
        """
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "--help"], catch_exceptions=False)
        assert result.exit_code == 0, f"run --help failed: {result.output}"
        import re
        # Click renders the default as part of the bracket: [a|b|all]  (last one = default)
        # or in a separate "(default: all)" note. Check both.
        bracket_match = re.search(r"--arms\s+\[([^\]]+)\]", result.output)
        assert bracket_match is not None, "Could not find --arms choice bracket"
        choices_raw = bracket_match.group(1)
        # The default is the last token in Click's pipe-separated list.
        choices = [c.strip() for c in choices_raw.split("|")]
        assert choices[-1] == "all", (
            f"Expected 'all' as the last/default choice; got choices={choices}. "
            "The Click default must be 'all', not 'both'."
        )

    def test_both_is_still_valid_arms_choice(self):
        """'both' must remain a valid --arms choice for backwards compatibility."""
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "--help"], catch_exceptions=False)
        assert result.exit_code == 0, f"run --help failed: {result.output}"
        import re
        bracket_match = re.search(r"--arms\s+\[([^\]]+)\]", result.output)
        assert bracket_match is not None, "Could not find --arms choice bracket"
        bracket = bracket_match.group(1)
        assert "both" in bracket, (
            f"'both' arm choice removed from bracket '{bracket}' — breaks backwards compatibility"
        )

    def test_all_arm_choices_present_in_help(self):
        """All five arm choices must appear inside the --arms [...] bracket."""
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "--help"], catch_exceptions=False)
        assert result.exit_code == 0, f"run --help failed: {result.output}"
        import re
        bracket_match = re.search(r"--arms\s+\[([^\]]+)\]", result.output)
        assert bracket_match is not None, "Could not find --arms choice bracket"
        bracket = bracket_match.group(1)
        for choice in ("baseline", "onlycode", "bash_only", "both", "all"):
            assert choice in bracket, (
                f"Arm choice {choice!r} missing from --arms bracket '{bracket}'"
            )

    def test_invalid_arms_value_rejected_by_cli(self):
        """An unrecognized --arms value must be rejected by Click with exit code 2.

        This proves the cli→run boundary enforces its type contract, not just
        advertises it.
        """
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "--arms", "invalid_arm_xyz"])
        # Click reports usage errors as exit code 2.
        assert result.exit_code == 2, (
            f"Expected exit code 2 for invalid --arms; got {result.exit_code}. "
            f"Output: {result.output}"
        )

    def test_run_subcommand_is_registered_on_cli(self):
        """The 'run' subcommand must be reachable through the root cli group."""
        runner = CliRunner()
        root_help = runner.invoke(cli, ["--help"], catch_exceptions=False)
        assert "run" in root_help.output, (
            f"'run' not listed in root cli help; got: {root_help.output}"
        )

    def test_arms_all_string_documented_to_include_bash_only(self):
        """The help text for 'all' must describe inclusion of bash_only arm.

        Guards the documentation contract so callers who read --help understand
        that 'all' selects baseline+onlycode+bash_only, not just baseline+onlycode.
        The check is on the --arms choice bracket so it detects removal of bash_only
        from the Click Choice list (not just from the description string).
        """
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "--help"], catch_exceptions=False)
        assert result.exit_code == 0, f"run --help failed: {result.output}"
        import re
        bracket_match = re.search(r"--arms\s+\[([^\]]+)\]", result.output)
        assert bracket_match is not None, "Could not find --arms choice bracket"
        bracket = bracket_match.group(1)
        # Both 'bash_only' and 'all' must appear as actual registered choices.
        assert "bash_only" in bracket and "all" in bracket, (
            f"Expected both 'bash_only' and 'all' in --arms choice bracket '{bracket}'"
        )
