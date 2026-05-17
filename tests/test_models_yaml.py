"""Round-trip tests for ``Problem.to_yaml`` / ``Problem.from_yaml``.

Issue #262: PyYAML's default ``width=80`` folded long plain scalars across
lines. When a downstream consumer lost a continuation line, the on-disk
``test_cmd`` ended up truncated (sphinx-doc__sphinx-8265 was committed broken
this way). The writer now passes ``width=10**6`` to keep every scalar on one
line; this test locks that contract.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from swebench.models import Problem


def _make_problem(test_cmd: str) -> Problem:
    return Problem(
        instance_id="repo__repo-1",
        repo_slug="repo/repo",
        base_commit="0" * 40,
        test_cmd=test_cmd,
        patch_file=None,
        problem_statement="a problem",
        added_at="2026-05-17",
        hf_split="test",
    )


def test_to_yaml_does_not_fold_long_test_cmd(tmp_path: Path) -> None:
    """A ``test_cmd`` longer than PyYAML's default 80-col width must round-trip
    unchanged. Without ``width=10**6`` the dumper inserts a continuation line
    and a fragile consumer can truncate at the fold point.
    """
    long_cmd = (
        'python -m pytest '
        '"tests/test_pycode_ast.py::test_unparse[(1, 2, 3)-(1, 2, 3)]" '
        "-x --tb=short"
    )
    assert len(long_cmd) > 80  # precondition: would fold without the fix
    out = tmp_path / "problem.yaml"
    _make_problem(long_cmd).to_yaml(out)

    # On-disk: the value must appear on a single line (no continuation indent).
    text = out.read_text()
    cmd_line = next(
        line for line in text.splitlines() if line.startswith("test_cmd:")
    )
    # The full string (everything after ``test_cmd: ``) must be on this one
    # line; assert no follow-on indented continuation.
    assert long_cmd in cmd_line, (
        f"test_cmd was folded across lines:\n{text!r}"
    )

    # Round-trip via PyYAML safe-loader must yield the original value.
    parsed = yaml.safe_load(out.read_text())
    assert parsed["test_cmd"] == long_cmd
