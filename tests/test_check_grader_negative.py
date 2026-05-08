"""Tests for the negative-sanity-check framework (SCHEMA §5.5).

Covers two layers:

* The library helpers in ``swebench.artifact_negative`` — default
  mutations, custom-case discovery, the per-case runner.
* The CLI tool ``tools/check_grader_negative.py`` — exit codes for the
  pass / fail / unexpected-pass scenarios.

The CLI tests build synthetic tasks at temp paths so we don't rely on the
real ``problems/artifact/`` tree (which can have real bugs we don't want
to assert against in unit tests).
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from swebench.artifact_loader import load_tasks
from swebench.artifact_negative import (
    NegativeCase,
    NegativeCaseOutcome,
    _mutate_empty,
    _mutate_off_by_one,
    _mutate_rename_one_field,
    _mutate_reverse_lines,
    _mutate_truncate_half,
    _mutate_wrap_in_list,
    default_negative_cases,
    load_task_negative_cases,
    run_negative_case,
)


_REPO_ROOT = Path(__file__).resolve().parent.parent
_TOOL = _REPO_ROOT / "tools" / "check_grader_negative.py"


# ─────────────────────── default-mutation unit tests ──────────────────────


def test_mutate_empty_returns_empty():
    assert _mutate_empty("anything") == ""


def test_mutate_truncate_half_keeps_prefix():
    assert _mutate_truncate_half("abcdefgh") == "abcd"
    assert _mutate_truncate_half("") == ""


def test_mutate_reverse_lines_swaps_order():
    src = "a\nb\nc\n"
    out = _mutate_reverse_lines(src)
    assert out.endswith("\n")
    # Order of non-empty lines is reversed.
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert lines == ["c", "b", "a"]


def test_mutate_reverse_lines_handles_singleton():
    """Single-line input: reverse is a no-op, so the helper must produce
    something visibly different (the runner rejects no-op mutations)."""
    out = _mutate_reverse_lines("only-one\n")
    assert out != "only-one\n"


def test_mutate_rename_one_field_renames_quoted_key():
    src = '{"product_id": "P001", "value": 3}'
    out = _mutate_rename_one_field(src)
    assert '"product_id_renamed"' in out
    assert '"product_id"' not in out


def test_mutate_rename_one_field_plain_text_fallback():
    src = "no JSON here\n"
    out = _mutate_rename_one_field(src)
    assert out != src  # something changed


def test_mutate_off_by_one_increments_first_number():
    assert _mutate_off_by_one("answer is 42") == "answer is 43"
    assert _mutate_off_by_one("pi=3.14") == "pi=4.14"
    # No numerics → fallback appends a digit so output differs from input.
    assert _mutate_off_by_one("none here") != "none here"


def test_mutate_wrap_in_list_wraps_text():
    assert _mutate_wrap_in_list("payload") == "[payload]"


def test_default_negative_cases_includes_six_cases():
    cases = default_negative_cases()
    assert len(cases) == 6
    names = [c.name for c in cases]
    assert names == [
        "empty",
        "truncated_half",
        "reversed_lines",
        "renamed_field",
        "off_by_one",
        "wrap_in_list",
    ]
    assert all(isinstance(c, NegativeCase) for c in cases)
    assert all(c.currently_caught for c in cases)


# ───────────────────────── per-task discovery tests ───────────────────────


def _make_minimal_task(
    task_dir: Path,
    grader_src: str,
    ref_content: str,
    *,
    custom_cases_src: str | None = None,
    instance_suffix: str | None = None,
) -> None:
    """Build a minimal artifact task at ``task_dir``."""
    suffix = instance_suffix or task_dir.name
    (task_dir / "workspace").mkdir(parents=True, exist_ok=True)
    (task_dir / "workspace" / "input.txt").write_text("# empty\n")
    (task_dir / "grader").mkdir(parents=True, exist_ok=True)
    (task_dir / "grader" / "hidden.py").write_text(textwrap.dedent(grader_src))
    (task_dir / "grader" / "reference_output.txt").write_text(ref_content)
    if custom_cases_src is not None:
        (task_dir / "grader" / "negative_cases.py").write_text(
            textwrap.dedent(custom_cases_src)
        )
    (task_dir / "prompt.md").write_text("produce answer.txt\n")
    (task_dir / "task.yaml").write_text(textwrap.dedent(f"""\
        instance_id: test_fixture__neg_{suffix}
        category: test_fixture
        difficulty: easy
        problem_statement: prompt.md
        workspace_dir: workspace/
        output_artifact: answer.txt
        hidden_grader: grader/hidden.py
        reference_output: grader/reference_output.txt
        execution_budget:
          max_code_runs: 0
          max_wall_seconds: 0
    """))


_GRADER_LENGTH_8 = """
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class GradeResult:
        passed: bool
        score: float
        detail: str

    def grade(scratch_dir):
        from pathlib import Path
        artifact = Path(scratch_dir) / "answer.txt"
        if not artifact.exists():
            return GradeResult(False, 0.0, "output artifact not produced")
        text = artifact.read_text()
        if not text.strip():
            return GradeResult(False, 0.0, "output artifact is empty")
        if len(text) != 8:
            return GradeResult(False, 0.0, f"length is {len(text)}, want 8")
        return GradeResult(True, 1.0, "ok")
"""


_GRADER_ALWAYS_PASSES = """
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class GradeResult:
        passed: bool
        score: float
        detail: str

    def grade(scratch_dir):
        return GradeResult(True, 1.0, "always pass")
"""


def test_load_negative_cases_falls_back_to_defaults(tmp_path):
    task_dir = tmp_path / "tasks" / "test_fixture" / "fallback_task"
    _make_minimal_task(task_dir, _GRADER_LENGTH_8, "01234567")
    [task] = load_tasks(tmp_path / "tasks")
    cases, is_custom = load_task_negative_cases(task)
    assert is_custom is False
    assert [c.name for c in cases] == [c.name for c in default_negative_cases()]


def test_load_negative_cases_picks_custom_module(tmp_path):
    custom = '''\
        from swebench.artifact_negative import NegativeCase

        NEGATIVE_CASES = [
            NegativeCase(name="custom_only", mutate=lambda t: "WRONG", expected_substring=""),
        ]
    '''
    task_dir = tmp_path / "tasks" / "test_fixture" / "custom_task"
    _make_minimal_task(
        task_dir,
        _GRADER_LENGTH_8,
        "01234567",
        custom_cases_src=custom,
    )
    [task] = load_tasks(tmp_path / "tasks")
    cases, is_custom = load_task_negative_cases(task)
    assert is_custom is True
    assert [c.name for c in cases] == ["custom_only"]


def test_load_negative_cases_rejects_wrong_type(tmp_path):
    bad = '''\
        NEGATIVE_CASES = "not a list"
    '''
    task_dir = tmp_path / "tasks" / "test_fixture" / "bad_task"
    _make_minimal_task(
        task_dir,
        _GRADER_LENGTH_8,
        "01234567",
        custom_cases_src=bad,
    )
    [task] = load_tasks(tmp_path / "tasks")
    with pytest.raises(TypeError):
        load_task_negative_cases(task)


# ─────────────────────────── run_negative_case ─────────────────────────────


def test_run_negative_case_pass_when_grader_rejects(tmp_path):
    task_dir = tmp_path / "tasks" / "test_fixture" / "ok_task"
    _make_minimal_task(task_dir, _GRADER_LENGTH_8, "01234567")
    [task] = load_tasks(tmp_path / "tasks")

    case = NegativeCase(
        name="empty",
        mutate=_mutate_empty,
        expected_substring="empty",
    )
    outcome = run_negative_case(task, case)
    assert outcome.status == "PASS", outcome


def test_run_negative_case_miss_when_grader_passes(tmp_path):
    task_dir = tmp_path / "tasks" / "test_fixture" / "broken_task"
    _make_minimal_task(task_dir, _GRADER_ALWAYS_PASSES, "01234567")
    [task] = load_tasks(tmp_path / "tasks")

    case = NegativeCase(
        name="empty",
        mutate=_mutate_empty,
    )
    outcome = run_negative_case(task, case)
    assert outcome.status == "MISS", outcome
    assert outcome.is_failure


def test_run_negative_case_weak_miss_for_default_mutation(tmp_path):
    """A default-mutation MISS is a diagnostic WEAK_MISS, not a hard MISS."""
    task_dir = tmp_path / "tasks" / "test_fixture" / "default_miss_task"
    _make_minimal_task(task_dir, _GRADER_ALWAYS_PASSES, "01234567")
    [task] = load_tasks(tmp_path / "tasks")

    case = NegativeCase(
        name="empty",
        mutate=_mutate_empty,
    )
    outcome = run_negative_case(task, case, from_defaults=True)
    assert outcome.status == "WEAK_MISS", outcome
    # WEAK_MISS does NOT fail the CLI gate.
    assert not outcome.is_failure


def test_run_negative_case_expected_miss_for_known_bug(tmp_path):
    task_dir = tmp_path / "tasks" / "test_fixture" / "known_bug_task"
    _make_minimal_task(task_dir, _GRADER_ALWAYS_PASSES, "01234567")
    [task] = load_tasks(tmp_path / "tasks")

    case = NegativeCase(
        name="empty",
        mutate=_mutate_empty,
        currently_caught=False,
        notes="documented in issue #999",
    )
    outcome = run_negative_case(task, case)
    assert outcome.status == "EXPECTED_MISS", outcome
    # EXPECTED_MISS is not a CLI failure.
    assert not outcome.is_failure


def test_run_negative_case_wrong_reason(tmp_path):
    task_dir = tmp_path / "tasks" / "test_fixture" / "wrong_reason_task"
    _make_minimal_task(task_dir, _GRADER_LENGTH_8, "01234567")
    [task] = load_tasks(tmp_path / "tasks")

    # Empty triggers the grader's "is empty" branch — detail says "empty",
    # not "wrong magic phrase".
    case = NegativeCase(
        name="empty",
        mutate=_mutate_empty,
        expected_substring="wrong magic phrase",
    )
    outcome = run_negative_case(task, case)
    assert outcome.status == "WRONG_REASON", outcome


def test_run_negative_case_no_op_mutation_is_error(tmp_path):
    task_dir = tmp_path / "tasks" / "test_fixture" / "noop_task"
    _make_minimal_task(task_dir, _GRADER_LENGTH_8, "01234567")
    [task] = load_tasks(tmp_path / "tasks")

    case = NegativeCase(
        name="noop",
        mutate=lambda t: t,  # returns input unchanged
    )
    outcome = run_negative_case(task, case)
    assert outcome.status == "ERROR"
    assert "no-op" in outcome.detail


# ───────────────────────────── CLI tests ──────────────────────────────────


def _run_cli(tasks_dir: Path, *extra_args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(_TOOL),
            "--tasks-dir",
            str(tasks_dir),
            *extra_args,
        ],
        capture_output=True,
        text=True,
    )


def test_cli_exit_zero_when_grader_catches_everything(tmp_path):
    tasks_dir = tmp_path / "tasks"
    task_dir = tasks_dir / "test_fixture" / "catches_task"
    custom = '''\
        from swebench.artifact_negative import NegativeCase, _mutate_empty

        NEGATIVE_CASES = [
            NegativeCase(name="empty", mutate=_mutate_empty),
        ]
    '''
    _make_minimal_task(
        task_dir,
        _GRADER_LENGTH_8,
        "01234567",
        custom_cases_src=custom,
    )
    proc = _run_cli(tasks_dir)
    assert proc.returncode == 0, proc.stderr
    assert "PASS" in proc.stdout
    assert "test_fixture__neg_catches_task" in proc.stdout


def test_cli_exit_one_when_grader_misses(tmp_path):
    tasks_dir = tmp_path / "tasks"
    task_dir = tasks_dir / "test_fixture" / "misses_task"
    custom = '''\
        from swebench.artifact_negative import NegativeCase, _mutate_empty

        NEGATIVE_CASES = [
            NegativeCase(name="empty", mutate=_mutate_empty),
        ]
    '''
    _make_minimal_task(
        task_dir,
        _GRADER_ALWAYS_PASSES,
        "01234567",
        custom_cases_src=custom,
    )
    proc = _run_cli(tasks_dir)
    assert proc.returncode == 1, proc.stdout
    assert "MISS" in proc.stdout
    assert "missed-by-grader" in proc.stdout


def test_cli_exit_zero_when_known_bug_warns(tmp_path):
    tasks_dir = tmp_path / "tasks"
    task_dir = tasks_dir / "test_fixture" / "knownbug_task"
    custom = '''\
        from swebench.artifact_negative import NegativeCase, _mutate_empty

        NEGATIVE_CASES = [
            NegativeCase(
                name="empty",
                mutate=_mutate_empty,
                currently_caught=False,
                notes="issue #foo",
            ),
        ]
    '''
    _make_minimal_task(
        task_dir,
        _GRADER_ALWAYS_PASSES,
        "01234567",
        custom_cases_src=custom,
    )
    proc = _run_cli(tasks_dir)
    assert proc.returncode == 0, proc.stdout
    assert "WARN" in proc.stdout
    assert "known-bug" in proc.stdout


def test_cli_exit_two_when_no_tasks(tmp_path):
    empty = tmp_path / "tasks"
    empty.mkdir()
    proc = _run_cli(empty)
    assert proc.returncode == 2


def test_cli_filter_runs_only_named_task(tmp_path):
    tasks_dir = tmp_path / "tasks"
    custom_pass = '''\
        from swebench.artifact_negative import NegativeCase, _mutate_empty
        NEGATIVE_CASES = [NegativeCase(name="empty", mutate=_mutate_empty)]
    '''
    custom_miss = '''\
        from swebench.artifact_negative import NegativeCase, _mutate_empty
        NEGATIVE_CASES = [NegativeCase(name="empty", mutate=_mutate_empty)]
    '''
    _make_minimal_task(
        tasks_dir / "test_fixture" / "selected",
        _GRADER_LENGTH_8,
        "01234567",
        custom_cases_src=custom_pass,
        instance_suffix="selected",
    )
    _make_minimal_task(
        tasks_dir / "test_fixture" / "skipped",
        _GRADER_ALWAYS_PASSES,
        "01234567",
        custom_cases_src=custom_miss,
        instance_suffix="skipped",
    )

    # Without filter: skipped task fails → exit 1.
    proc_all = _run_cli(tasks_dir)
    assert proc_all.returncode == 1

    # With filter targeting only the passing task → exit 0.
    proc_one = _run_cli(tasks_dir, "--filter", "test_fixture__neg_selected")
    assert proc_one.returncode == 0
    assert "test_fixture__neg_skipped" not in proc_one.stdout


def test_cli_tasks_with_custom_cases_only(tmp_path):
    tasks_dir = tmp_path / "tasks"
    # One task with custom cases, one without.
    custom = '''\
        from swebench.artifact_negative import NegativeCase, _mutate_empty
        NEGATIVE_CASES = [NegativeCase(name="empty", mutate=_mutate_empty)]
    '''
    _make_minimal_task(
        tasks_dir / "test_fixture" / "with_custom",
        _GRADER_LENGTH_8,
        "01234567",
        custom_cases_src=custom,
        instance_suffix="with_custom",
    )
    _make_minimal_task(
        tasks_dir / "test_fixture" / "no_custom",
        _GRADER_LENGTH_8,
        "01234567",
        instance_suffix="no_custom",
    )

    proc = _run_cli(tasks_dir, "--tasks-with-custom-cases-only")
    assert proc.returncode == 0
    assert "test_fixture__neg_with_custom" in proc.stdout
    assert "test_fixture__neg_no_custom" not in proc.stdout
