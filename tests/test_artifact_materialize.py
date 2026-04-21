"""Tests for swebench.artifact_materialize (no-leak invariant)."""

from __future__ import annotations

from pathlib import Path

import pytest

from swebench.artifact_materialize import (
    MaterializationError,
    _seed_for_instance,
    materialize,
    scratch_dir_for,
)
from swebench.artifact_models import ExecutionBudget, Task


def _make_task(task_dir: Path, with_grader: bool = True) -> Task:
    (task_dir / "workspace").mkdir(parents=True, exist_ok=True)
    (task_dir / "workspace" / "input.txt").write_text("hello\n")
    (task_dir / "workspace" / "sub").mkdir(exist_ok=True)
    (task_dir / "workspace" / "sub" / "nested.txt").write_text("deep\n")
    if with_grader:
        (task_dir / "grader").mkdir(exist_ok=True)
        (task_dir / "grader" / "hidden.py").write_text("def grade(d): ...")
        (task_dir / "grader" / "reference_output.txt").write_text("secret\n")
    return Task(
        instance_id="test_fixture__trivial",
        category="test_fixture",
        difficulty="easy",
        problem_statement="prompt.md",
        workspace_dir="workspace/",
        output_artifact="out.txt",
        hidden_grader="grader/hidden.py",
        reference_output="grader/reference_output.txt",
        execution_budget=ExecutionBudget(0, 0),
        task_dir=task_dir.resolve(),
    )


def test_materialize_copies_workspace(tmp_path: Path) -> None:
    task = _make_task(tmp_path / "task")
    scratch = tmp_path / "scratch"
    materialize(task, scratch)
    assert (scratch / "input.txt").read_text() == "hello\n"
    assert (scratch / "sub" / "nested.txt").read_text() == "deep\n"


def test_materialize_never_copies_grader(tmp_path: Path) -> None:
    task = _make_task(tmp_path / "task")
    scratch = tmp_path / "scratch"
    materialize(task, scratch)
    # Absolute invariant: no hidden.py, no reference_output* anywhere in scratch.
    assert not any(scratch.rglob("hidden.py"))
    assert not any(scratch.rglob("reference_output*"))
    assert not (scratch / "grader").exists()


def test_materialize_detects_leak(tmp_path: Path) -> None:
    """If a task author accidentally put a grader file inside workspace/,
    the post-copy scan must flag it."""
    task = _make_task(tmp_path / "task")
    (task.task_dir / "workspace" / "reference_output.jsonl").write_text("leaked\n")
    scratch = tmp_path / "scratch"
    with pytest.raises(MaterializationError, match="No-leak invariant"):
        materialize(task, scratch)


def test_materialize_detects_hidden_py_leak(tmp_path: Path) -> None:
    task = _make_task(tmp_path / "task")
    (task.task_dir / "workspace" / "hidden.py").write_text("def grade(d): ...")
    scratch = tmp_path / "scratch"
    with pytest.raises(MaterializationError):
        materialize(task, scratch)


def test_scratch_dir_for_layout() -> None:
    results = Path("/r")
    p = scratch_dir_for(results, "cat__slug", "code_only", 3)
    assert p == Path("/r/cat__slug/code_only/run3/scratch")


# --- workspace_generator (issue #118) -----------------------------------------


def _make_gen_task(task_dir: Path, gen_body: str, with_grader: bool = True) -> Task:
    """Build a task that declares workspace_generator: workspace/generator.py."""
    (task_dir / "workspace").mkdir(parents=True, exist_ok=True)
    (task_dir / "workspace" / "static.txt").write_text("hand-curated\n")
    (task_dir / "workspace" / "generator.py").write_text(gen_body)
    if with_grader:
        (task_dir / "grader").mkdir(exist_ok=True)
        (task_dir / "grader" / "hidden.py").write_text("def grade(d): ...")
        (task_dir / "grader" / "reference_output.txt").write_text("secret\n")
    return Task(
        instance_id="test_fixture__gen",
        category="test_fixture",
        difficulty="easy",
        problem_statement="prompt.md",
        workspace_dir="workspace/",
        output_artifact="out.txt",
        hidden_grader="grader/hidden.py",
        reference_output="grader/reference_output.txt",
        execution_budget=ExecutionBudget(0, 0),
        workspace_generator="workspace/generator.py",
        task_dir=task_dir.resolve(),
    )


_GEN_WRITES_DATA = """\
import argparse, pathlib
ap = argparse.ArgumentParser()
ap.add_argument("--seed", type=int, required=True)
ap.add_argument("--output-dir", type=pathlib.Path, required=True)
ap.add_argument("--instance-id", required=False, default="")
args = ap.parse_args()
(args.output_dir / "generated.jsonl").write_text(f"seed={args.seed}\\n")
"""


def test_generator_runs_and_writes_data(tmp_path: Path) -> None:
    task = _make_gen_task(tmp_path / "task", _GEN_WRITES_DATA)
    scratch = tmp_path / "scratch"
    materialize(task, scratch)
    # The generated file is present.
    gen = scratch / "generated.jsonl"
    assert gen.is_file()
    # Seed is stable and non-zero for the instance_id.
    content = gen.read_text()
    assert content.startswith("seed=") and content.strip() != "seed=0"
    # Hand-curated files were copied in.
    assert (scratch / "static.txt").read_text() == "hand-curated\n"


def test_generator_not_copied_into_scratch(tmp_path: Path) -> None:
    task = _make_gen_task(tmp_path / "task", _GEN_WRITES_DATA)
    scratch = tmp_path / "scratch"
    materialize(task, scratch)
    assert not (scratch / "generator.py").exists()
    assert not any(scratch.rglob("generator.py"))


def test_generator_skipped_when_marker_present(tmp_path: Path) -> None:
    """Second call on a populated scratch dir must be a no-op."""
    gen_body = _GEN_WRITES_DATA.replace(
        '"seed={args.seed}\\n"', '"seed={args.seed} call={open(args.output_dir / \'calls.txt\', \'a\').write(\'x\') or 1}\\n"'
    )
    # Simpler: track invocations via an external file sibling to workspace.
    call_log_body = """\
import argparse, pathlib
ap = argparse.ArgumentParser()
ap.add_argument("--seed", type=int, required=True)
ap.add_argument("--output-dir", type=pathlib.Path, required=True)
ap.add_argument("--instance-id", required=False, default="")
args = ap.parse_args()
calls = args.output_dir / "calls.txt"
with open(calls, "a") as f:
    f.write("x")
(args.output_dir / "generated.jsonl").write_text("ok\\n")
"""
    task = _make_gen_task(tmp_path / "task", call_log_body)
    scratch = tmp_path / "scratch"
    materialize(task, scratch)
    assert (scratch / "calls.txt").read_text() == "x"
    # Second materialize call: generator should NOT run again (marker gates it).
    materialize(task, scratch)
    assert (scratch / "calls.txt").read_text() == "x"


def test_generator_failure_raises(tmp_path: Path) -> None:
    bad_gen = "import sys; sys.exit(7)\n"
    task = _make_gen_task(tmp_path / "task", bad_gen)
    scratch = tmp_path / "scratch"
    with pytest.raises(MaterializationError, match="workspace_generator"):
        materialize(task, scratch)


def test_generator_leak_into_scratch_is_flagged(tmp_path: Path) -> None:
    """If a generator.py file somehow lands in scratch, the leak scan flags it."""
    # Generator writes a second copy of itself into scratch.
    gen_body = """\
import argparse, pathlib
ap = argparse.ArgumentParser()
ap.add_argument("--seed", type=int, required=True)
ap.add_argument("--output-dir", type=pathlib.Path, required=True)
ap.add_argument("--instance-id", required=False, default="")
args = ap.parse_args()
(args.output_dir / "generator.py").write_text("oops\\n")
"""
    task = _make_gen_task(tmp_path / "task", gen_body)
    scratch = tmp_path / "scratch"
    with pytest.raises(MaterializationError, match="No-leak invariant"):
        materialize(task, scratch)


def test_no_generator_task_behaves_as_before(tmp_path: Path) -> None:
    """Tasks without workspace_generator must behave bit-identically to pre-refactor."""
    task = _make_task(tmp_path / "task")
    assert task.workspace_generator is None
    scratch = tmp_path / "scratch"
    materialize(task, scratch)
    assert (scratch / "input.txt").read_text() == "hello\n"
    assert not (scratch / ".workspace_generator_done").exists()


def test_ignore_is_path_based_not_name_based(tmp_path: Path) -> None:
    """F-4: a helper file that happens to share the generator's filename but
    lives at a different path inside workspace/ MUST still be copied into
    scratch. The ignore callable must key on absolute path identity, never on
    basename."""
    task_dir = tmp_path / "task"
    task = _make_gen_task(task_dir, _GEN_WRITES_DATA)
    # Create a same-named helper at a different path in workspace/. The agent
    # is entitled to see this file; only the declared generator must be dropped.
    helper_dir = task_dir / "workspace" / "helpers"
    helper_dir.mkdir(parents=True, exist_ok=True)
    (helper_dir / "generator.py").write_text("# hand-curated helper\n")

    scratch = tmp_path / "scratch"
    materialize(task, scratch)

    # The declared generator is NOT in scratch, anywhere.
    assert not (scratch / "generator.py").exists()
    # The same-named helper at a different path IS in scratch.
    assert (scratch / "helpers" / "generator.py").read_text() == "# hand-curated helper\n"


def test_seed_for_instance_is_stable(tmp_path: Path) -> None:
    """F-5: pin the seed derivation to known values so any future refactor of
    _seed_for_instance (prefix length, hash algorithm, encoding) is caught
    immediately — otherwise every committed reference_output.* becomes silently
    wrong and only the pre-merge grader sanity gate surfaces it."""
    # Golden values computed from the canonical sha256(instance_id)[:8] algorithm.
    assert _seed_for_instance("data_processing__p95_latency_easy") == 3478982464
    assert _seed_for_instance("stateful_reasoning__event_ledger") == 361668686
    # Determinism across repeat calls.
    assert _seed_for_instance("x") == _seed_for_instance("x")
    # Different ids give different seeds (with overwhelming probability for sha256).
    assert _seed_for_instance("a") != _seed_for_instance("b")
