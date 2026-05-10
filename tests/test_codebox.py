"""Tests for the ``codebox`` helper module.

Covers: outline / read_lines / peek / grep / source_of / edit_replace return
value / run shell wrapper / failing-test source detection.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# codebox.py lives in exec_server/ and is staged into agent cwds at runtime.
# Add it to sys.path so we can import it directly here.
_EXEC_SERVER = Path(__file__).resolve().parent.parent / "exec_server"
sys.path.insert(0, str(_EXEC_SERVER))

import codebox  # noqa: E402


SAMPLE = '''\
"""module docstring."""

import os


CONST = 1


def helper(x):
    """top-level helper."""
    return x + 1


class Widget:
    """A widget."""

    def __init__(self, name):
        self.name = name

    def render(self):
        return f"<{self.name}>"


def main():
    w = Widget("x")
    return w.render()
'''


@pytest.fixture
def sample_file(tmp_path: Path) -> Path:
    p = tmp_path / "sample.py"
    p.write_text(SAMPLE)
    return p


# -------- A1: read removed --------


def test_read_removed():
    """codebox.read should not exist (A1)."""
    assert not hasattr(codebox, "read")


# -------- A2: outline --------


def test_outline_lists_top_level_and_methods(sample_file: Path):
    out = codebox.outline(str(sample_file))
    assert str(sample_file) in out
    assert "lines)" in out  # header includes line count
    assert "def helper" in out
    assert "class Widget" in out
    # Methods of top-level classes are included (depth 1)
    assert "def __init__" in out
    assert "def render" in out
    assert "def main" in out


def test_outline_handles_syntax_error(tmp_path: Path):
    p = tmp_path / "bad.py"
    p.write_text("def broken(\n  pass\n")  # syntax error
    out = codebox.outline(str(p))
    # Falls back to regex; still surfaces the def line.
    assert "def broken" in out


# -------- A3: edit_replace returns diff preview --------


def test_edit_replace_returns_diff_preview(sample_file: Path):
    preview = codebox.edit_replace(str(sample_file), "x + 1", "x + 2")
    assert preview.startswith("edited ")
    assert "x + 2" in preview
    # The preview includes line numbers around the change
    assert "lines " in preview.splitlines()[0]


def test_edit_replace_zero_matches_raises(sample_file: Path):
    with pytest.raises(ValueError, match="not found"):
        codebox.edit_replace(str(sample_file), "no-such-string", "X")


def test_edit_replace_multi_match_raises(tmp_path: Path):
    p = tmp_path / "m.py"
    p.write_text("a\na\n")
    with pytest.raises(ValueError, match=r"matched 2x"):
        codebox.edit_replace(str(p), "a\n", "b\n")


# -------- A4: run shell wrapper --------


def test_run_returns_raw_stdout_on_success():
    out = codebox.run("echo hello")
    assert out.strip() == "hello"


def test_run_includes_envelope_on_failure():
    out = codebox.run("false; echo done")
    # Successful "false" run: exits 1 because echo done masks it? Actually
    # bash sets $? from the last command (echo done). Use explicit fail.
    out = codebox.run("exit 7")
    assert "exit 7" in out


def test_run_tails_long_output():
    # 100 lines, tail=5 should keep only last 5 + an elision note.
    cmd = "for i in $(seq 1 100); do echo line$i; done"
    out = codebox.run(cmd, tail=5)
    assert "line100" in out
    assert "line96" in out
    assert "line1\n" not in out
    assert "earlier lines elided" in out


# -------- A5: peek --------


def test_peek_includes_line_numbers_and_context(sample_file: Path):
    # def helper is somewhere in the middle; find it via grep first.
    hits = codebox.grep(r"^def helper", str(sample_file))
    assert hits
    line = int(hits.split(":", 2)[1])
    out = codebox.peek(str(sample_file), line, around=2)
    # Output is line-numbered.
    lines = out.splitlines()
    assert any(line_str in ln.split("  ")[0] for line_str, ln in [(str(line), l) for l in lines])
    # Includes the def line itself.
    assert "def helper" in out


# -------- A6: source_of --------


def test_source_of_finds_function(sample_file: Path):
    body = codebox.source_of("helper", str(sample_file))
    assert "def helper" in body
    assert "x + 1" in body or "x + 2" in body  # depending on prior tests
    assert str(sample_file) in body  # location header


def test_source_of_finds_class(sample_file: Path):
    body = codebox.source_of("Widget", str(sample_file))
    assert "class Widget" in body
    assert "def render" in body  # class body included


def test_source_of_searches_directory(tmp_path: Path):
    (tmp_path / "a.py").write_text("def alpha():\n    pass\n")
    (tmp_path / "b.py").write_text("def beta():\n    return 'b'\n")
    body = codebox.source_of("beta", str(tmp_path))
    assert "def beta" in body
    assert "return 'b'" in body


def test_source_of_missing_raises(tmp_path: Path):
    (tmp_path / "x.py").write_text("def nope():\n    pass\n")
    with pytest.raises(ValueError, match="not found"):
        codebox.source_of("absent", str(tmp_path))


# -------- D1: failing-test source on test command failure --------


def test_run_test_failure_appends_failing_test_source(tmp_path: Path):
    """Simulate a Django-style runtests.py invocation that emits a unittest
    failure line, and assert codebox.run pulls in the test method's source.
    """
    # Create a fake test file at the conventional location.
    tests_dir = tmp_path / "tests" / "utils_tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "__init__.py").write_text("")
    (tests_dir / "test_http.py").write_text(
        "import unittest\n"
        "\n"
        "class HttpDateProcessingTests(unittest.TestCase):\n"
        "    def test_parsing_rfc850(self):\n"
        "        self.fail('mock failure')\n"
        "\n"
        "    def test_other(self):\n"
        "        pass\n"
    )
    # Fake runtests.py that emits a unittest-style FAIL line and exits 1.
    (tmp_path / "runtests.py").write_text(
        "import sys\n"
        "print('Creating test database for alias \\'default\\'...')\n"
        "print('F.')\n"
        "print('=' * 70)\n"
        "print('FAIL: test_parsing_rfc850 (utils_tests.test_http.HttpDateProcessingTests)')\n"
        "print('-' * 70)\n"
        "sys.exit(1)\n"
    )
    out = codebox.run(
        "python runtests.py",
        tail=20,
        cwd=str(tmp_path),
    )
    # The failing test source is appended.
    assert "failing test source" in out
    assert "def test_parsing_rfc850" in out
    assert "mock failure" in out
    # And we did NOT pull in the unrelated passing test.
    assert "def test_other" not in out


def test_run_non_test_failure_does_not_search_tests(tmp_path: Path):
    """A plain command that exits non-zero should not trigger test-source lookup."""
    out = codebox.run("ls /nonexistent-dir-xyz", cwd=str(tmp_path))
    assert "failing test source" not in out


# -------- read_lines / grep regression checks (already existed, keep them) --------


def test_read_lines_inclusive(sample_file: Path):
    out = codebox.read_lines(str(sample_file), 1, 1)
    assert out.startswith('"""module docstring."""')


def test_grep_returns_path_lineno_text(sample_file: Path):
    out = codebox.grep(r"def\s+helper", str(sample_file))
    assert ":" in out
    parts = out.split(":", 2)
    assert parts[0] == str(sample_file)
    assert parts[1].isdigit()
