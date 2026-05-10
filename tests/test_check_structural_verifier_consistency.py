"""Tests for tools/check_structural_verifier_consistency.py.

Mirrors the style of test_verify_graders.py — runs the tool as a
subprocess so the CLI exit-code contract is exercised end-to-end.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path


_TOOL = (
    Path(__file__).resolve().parent.parent
    / "tools"
    / "check_structural_verifier_consistency.py"
)


def _run_tool(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_TOOL), "--root", str(root)],
        capture_output=True,
        text=True,
    )


def _make_task(
    root: Path,
    slug: str,
    *,
    has_verify: bool,
    declares: bool,
    declared_path: str = "workspace/verify.py",
) -> Path:
    task_dir = root / "problems" / "artifact" / "test_fixture" / slug
    (task_dir / "workspace").mkdir(parents=True)
    if has_verify:
        (task_dir / "workspace" / "verify.py").write_text("def verify(p): pass\n")
    yaml_lines = [
        f"instance_id: test_fixture__{slug}",
        "category: test_fixture",
        "difficulty: easy",
        "problem_statement: prompt.md",
        "workspace_dir: workspace/",
        "output_artifact: out.txt",
    ]
    if declares:
        yaml_lines.append(f"structural_verifier: {declared_path}")
    yaml_lines += [
        "hidden_grader: grader/hidden.py",
        "reference_output: grader/reference_output.txt",
        "execution_budget:",
        "  max_code_runs: 0",
        "  max_wall_seconds: 0",
    ]
    (task_dir / "task.yaml").write_text("\n".join(yaml_lines) + "\n")
    return task_dir


def test_self_test_passes() -> None:
    """The bundled --self-test must always pass."""
    res = subprocess.run(
        [sys.executable, str(_TOOL), "--self-test"],
        capture_output=True, text=True,
    )
    assert res.returncode == 0, (
        f"self-test failed (code {res.returncode}):\n"
        f"stdout: {res.stdout}\nstderr: {res.stderr}"
    )


def test_clean_repo_returns_zero(tmp_path: Path) -> None:
    """A repo where every (verify.py, declaration) pair agrees is clean."""
    _make_task(tmp_path, "both_present", has_verify=True, declares=True)
    _make_task(tmp_path, "neither_present", has_verify=False, declares=False)

    res = _run_tool(tmp_path)
    assert res.returncode == 0, (
        f"expected exit 0, got {res.returncode}\n"
        f"stdout: {res.stdout}\nstderr: {res.stderr}"
    )
    assert "no structural_verifier inconsistencies" in res.stdout


def test_missing_declaration_is_flagged(tmp_path: Path) -> None:
    """workspace/verify.py without a task.yaml declaration → exit 1."""
    _make_task(tmp_path, "needs_decl", has_verify=True, declares=False)

    res = _run_tool(tmp_path)
    assert res.returncode == 1
    assert "MISSING_DECLARATION" in res.stderr
    assert "needs_decl" in res.stderr


def test_missing_file_is_flagged(tmp_path: Path) -> None:
    """task.yaml declaration without a real file → exit 1."""
    _make_task(tmp_path, "dangling_decl", has_verify=False, declares=True)

    res = _run_tool(tmp_path)
    assert res.returncode == 1
    assert "MISSING_FILE" in res.stderr
    assert "dangling_decl" in res.stderr


def test_empty_tasks_dir_returns_two(tmp_path: Path) -> None:
    """Discovery error: no task.yaml files → exit 2."""
    (tmp_path / "problems" / "artifact").mkdir(parents=True)

    res = _run_tool(tmp_path)
    assert res.returncode == 2
    assert "no task.yaml files found" in res.stderr


def test_real_repo_is_consistent() -> None:
    """The real onlycodes repo must satisfy the lint at HEAD.

    This is the regression guard for issue #167: any future task that
    ships workspace/verify.py without declaring structural_verifier
    (or vice versa) will fail this test.
    """
    repo = Path(__file__).resolve().parent.parent
    res = _run_tool(repo)
    assert res.returncode == 0, (
        f"real repo failed structural_verifier lint:\n"
        f"stdout: {res.stdout}\nstderr: {res.stderr}"
    )
