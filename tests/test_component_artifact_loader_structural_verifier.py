"""Component test: artifact_loader._parse_task_yaml → artifact_models.Task structural_verifier field.

Boundary: swebench.artifact_loader.load_tasks() parses the optional
``structural_verifier`` field from task.yaml and wires it into
``swebench.artifact_models.Task.structural_verifier``.

This PR (#188) removed ``structural_verifier:`` from three task.yaml files
and deleted the corresponding ``workspace/verify.py`` files, making the
absent-field path the common case. These tests pin the loader→Task contract
for the ``structural_verifier`` optional field so any future loader change
that breaks this wiring is caught immediately.

Both real modules cooperate across the parser boundary:
  - ``swebench.artifact_loader`` (parser/validator)
  - ``swebench.artifact_models.Task`` (dataclass receiver)

No doubles: ``tmp_path`` (filesystem) is the only seam — it is the canonical
medium through which the two modules exchange data at load time.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from swebench.artifact_loader import load_tasks
from swebench.artifact_models import Task


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_task(
    tasks_dir: Path,
    slug: str,
    overrides: dict | None = None,
) -> Path:
    """Build a minimal valid task under tasks_dir/stateful_reasoning/<slug>/.

    Returns the task directory.
    """
    category = "stateful_reasoning"
    task_dir = tasks_dir / category / slug
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "workspace").mkdir(exist_ok=True)
    (task_dir / "grader").mkdir(exist_ok=True)
    (task_dir / "prompt.md").write_text("do the thing\n")
    (task_dir / "grader" / "hidden.py").write_text(
        "def grade(d):\n"
        "    class R:\n"
        "        passed=True\n"
        "        score=1.0\n"
        "        detail='ok'\n"
        "    return R()\n"
    )
    (task_dir / "grader" / "reference_output.txt").write_text("ref\n")

    data: dict = {
        "instance_id": f"{category}__{slug}",
        "category": category,
        "difficulty": "medium",
        "problem_statement": "prompt.md",
        "workspace_dir": "workspace/",
        "output_artifact": "output/result.json",
        "hidden_grader": "grader/hidden.py",
        "reference_output": "grader/reference_output.txt",
        "execution_budget": {"max_code_runs": 0, "max_wall_seconds": 0},
    }
    if overrides:
        data.update(overrides)
    with open(task_dir / "task.yaml", "w") as f:
        yaml.safe_dump(data, f, sort_keys=False)
    return task_dir


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.component
class TestArtifactLoaderStructuralVerifierContract:
    """Pin the loader → Task.structural_verifier optional-field contract."""

    def test_absent_field_yields_none(self, tmp_path: Path) -> None:
        """When task.yaml omits structural_verifier the loaded Task must have None.

        This is the post-#188 common case: tasks that had the field removed
        should parse cleanly and expose ``structural_verifier=None``.
        """
        _write_task(tmp_path, "no_verifier")

        tasks = load_tasks(tmp_path)

        assert len(tasks) == 1
        task = tasks[0]
        assert isinstance(task, Task)
        assert task.structural_verifier is None, (
            f"Expected structural_verifier=None for task without field; "
            f"got {task.structural_verifier!r}"
        )

    def test_present_string_field_is_accepted_and_forwarded(self, tmp_path: Path) -> None:
        """When structural_verifier is a string path it must be forwarded verbatim into Task.

        The loader must not strip, normalise, or reject a valid string value.
        """
        _write_task(
            tmp_path,
            "with_verifier",
            overrides={"structural_verifier": "workspace/verify.py"},
        )

        tasks = load_tasks(tmp_path)

        assert len(tasks) == 1
        assert tasks[0].structural_verifier == "workspace/verify.py", (
            f"Expected structural_verifier='workspace/verify.py'; "
            f"got {tasks[0].structural_verifier!r}"
        )

    def test_wrong_type_integer_rejected(self, tmp_path: Path) -> None:
        """An integer structural_verifier must be rejected by the loader with ValueError.

        Guards the type-validation branch: loader raises ValueError before
        constructing a Task, so callers can catch schema errors early.
        """
        _write_task(
            tmp_path,
            "bad_verifier_int",
            overrides={"structural_verifier": 42},
        )

        with pytest.raises(ValueError, match="structural_verifier must be a string"):
            load_tasks(tmp_path)

    def test_structural_verifier_is_independent_of_workspace_generator(
        self, tmp_path: Path
    ) -> None:
        """Both optional fields may coexist; each is forwarded independently.

        Regression guard: the loader processes optional fields in sequence.
        A bug that confused structural_verifier with workspace_generator would
        be caught here.
        """
        _write_task(
            tmp_path,
            "both_optional",
            overrides={
                "structural_verifier": "workspace/verify.py",
                "workspace_generator": "workspace/generator.py",
            },
        )

        tasks = load_tasks(tmp_path)

        assert len(tasks) == 1
        task = tasks[0]
        assert task.structural_verifier == "workspace/verify.py", (
            f"structural_verifier mismatch: {task.structural_verifier!r}"
        )
        assert task.workspace_generator == "workspace/generator.py", (
            f"workspace_generator mismatch: {task.workspace_generator!r}"
        )

    def test_multiple_tasks_some_with_some_without_verifier(self, tmp_path: Path) -> None:
        """The loader handles a mixed batch: some tasks with and some without structural_verifier.

        After #188, the real repo has exactly this mixture. Pin the contract
        that load_tasks returns both correctly without cross-contamination.
        """
        _write_task(tmp_path, "task_with_sv", overrides={"structural_verifier": "workspace/verify.py"})
        _write_task(tmp_path, "task_without_sv")

        tasks = load_tasks(tmp_path)
        tasks_by_id = {t.instance_id: t for t in tasks}

        assert "stateful_reasoning__task_with_sv" in tasks_by_id
        assert "stateful_reasoning__task_without_sv" in tasks_by_id

        assert tasks_by_id["stateful_reasoning__task_with_sv"].structural_verifier == "workspace/verify.py"
        assert tasks_by_id["stateful_reasoning__task_without_sv"].structural_verifier is None
