"""Tests for swebench.artifact_loader."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from swebench.artifact_loader import load_tasks


def _write_task(
    tasks_dir: Path,
    category: str,
    slug: str,
    overrides: dict | None = None,
) -> Path:
    """Create a minimal valid task at tasks/<category>/<slug>/ and return its dir."""
    task_dir = tasks_dir / category / slug
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "workspace").mkdir(exist_ok=True)
    (task_dir / "grader").mkdir(exist_ok=True)
    (task_dir / "prompt.md").write_text("do the thing\n")
    (task_dir / "grader" / "hidden.py").write_text(
        "def grade(d):\n    class R:\n        passed=True\n        score=1.0\n        detail='ok'\n    return R()\n"
    )
    (task_dir / "grader" / "reference_output.txt").write_text("ref\n")

    data = {
        "instance_id": f"{category}__{slug}",
        "category": category,
        "difficulty": "easy",
        "problem_statement": "prompt.md",
        "workspace_dir": "workspace/",
        "output_artifact": "answer.txt",
        "hidden_grader": "grader/hidden.py",
        "reference_output": "grader/reference_output.txt",
        "execution_budget": {"max_code_runs": 0, "max_wall_seconds": 0},
    }
    if overrides:
        data.update(overrides)
    with open(task_dir / "task.yaml", "w") as f:
        yaml.safe_dump(data, f, sort_keys=False)
    return task_dir


def test_load_empty_tasks_dir(tmp_path: Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    assert load_tasks(tasks_dir) == []


def test_load_missing_tasks_dir(tmp_path: Path) -> None:
    assert load_tasks(tmp_path / "does_not_exist") == []


def test_load_single_task(tmp_path: Path) -> None:
    tasks_dir = tmp_path / "tasks"
    _write_task(tasks_dir, "data_processing", "p95_latency_easy")
    tasks = load_tasks(tasks_dir)
    assert len(tasks) == 1
    t = tasks[0]
    assert t.instance_id == "data_processing__p95_latency_easy"
    assert t.category == "data_processing"
    assert t.difficulty == "easy"
    assert t.execution_budget.max_code_runs == 0
    assert t.execution_budget.max_wall_seconds == 0
    assert t.execution_budget.is_unlimited
    assert t.task_dir is not None and t.task_dir.is_dir()


def test_filter_exact_match(tmp_path: Path) -> None:
    tasks_dir = tmp_path / "tasks"
    _write_task(tasks_dir, "data_processing", "p95_latency_easy")
    _write_task(tasks_dir, "algorithmic", "makespan_scheduling")
    tasks = load_tasks(tasks_dir, filter_ids={"data_processing__p95_latency_easy"})
    assert len(tasks) == 1
    assert tasks[0].instance_id == "data_processing__p95_latency_easy"


def test_filter_no_match_raises(tmp_path: Path) -> None:
    tasks_dir = tmp_path / "tasks"
    _write_task(tasks_dir, "data_processing", "p95_latency_easy")
    with pytest.raises(ValueError, match="No matching tasks"):
        load_tasks(tasks_dir, filter_ids={"nope__nada"})


def test_unknown_field_rejected(tmp_path: Path) -> None:
    tasks_dir = tmp_path / "tasks"
    _write_task(
        tasks_dir,
        "data_processing",
        "bad_extra",
        overrides={"unknown_key": "oops"},
    )
    with pytest.raises(ValueError, match="unknown field"):
        load_tasks(tasks_dir)


def test_missing_required_field_rejected(tmp_path: Path) -> None:
    tasks_dir = tmp_path / "tasks"
    task_dir = _write_task(tasks_dir, "data_processing", "missing_cat")
    # Strip a required field
    with open(task_dir / "task.yaml") as f:
        data = yaml.safe_load(f)
    data.pop("difficulty")
    with open(task_dir / "task.yaml", "w") as f:
        yaml.safe_dump(data, f)
    with pytest.raises(ValueError, match="missing required field"):
        load_tasks(tasks_dir)


def test_instance_id_category_prefix_mismatch(tmp_path: Path) -> None:
    tasks_dir = tmp_path / "tasks"
    _write_task(
        tasks_dir,
        "data_processing",
        "wrong_prefix",
        overrides={"instance_id": "algorithmic__wrong_prefix"},
    )
    with pytest.raises(ValueError, match="category prefix mismatch"):
        load_tasks(tasks_dir)


def test_unknown_category_rejected(tmp_path: Path) -> None:
    tasks_dir = tmp_path / "tasks"
    _write_task(
        tasks_dir,
        "data_processing",
        "fine",
        overrides={"category": "not_a_category",
                   "instance_id": "not_a_category__fine"},
    )
    with pytest.raises(ValueError, match="unknown category"):
        load_tasks(tasks_dir)


def test_hard_difficulty_accepted(tmp_path: Path) -> None:
    """Issue #128: `hard` is admitted to the difficulty whitelist."""
    tasks_dir = tmp_path / "tasks"
    _write_task(
        tasks_dir,
        "data_processing",
        "hard_task",
        overrides={"difficulty": "hard"},
    )
    tasks = load_tasks(tasks_dir)
    assert len(tasks) == 1
    assert tasks[0].difficulty == "hard"


def test_invalid_difficulty_rejected(tmp_path: Path) -> None:
    """Any value outside {easy, medium, hard} is still rejected."""
    tasks_dir = tmp_path / "tasks"
    _write_task(
        tasks_dir,
        "data_processing",
        "impossible_difficulty",
        overrides={"difficulty": "impossible"},
    )
    with pytest.raises(ValueError, match="difficulty must be"):
        load_tasks(tasks_dir)


def test_negative_budget_rejected(tmp_path: Path) -> None:
    tasks_dir = tmp_path / "tasks"
    _write_task(
        tasks_dir,
        "data_processing",
        "neg_budget",
        overrides={"execution_budget": {"max_code_runs": -1, "max_wall_seconds": 0}},
    )
    with pytest.raises(ValueError, match="must be int >= 0"):
        load_tasks(tasks_dir)


def test_tasks_sorted_by_instance_id(tmp_path: Path) -> None:
    tasks_dir = tmp_path / "tasks"
    _write_task(tasks_dir, "algorithmic", "zebra")
    _write_task(tasks_dir, "data_processing", "alpha")
    tasks = load_tasks(tasks_dir)
    assert [t.instance_id for t in tasks] == [
        "algorithmic__zebra",
        "data_processing__alpha",
    ]


def test_workspace_generator_accepted(tmp_path: Path) -> None:
    """Issue #118: loader must accept the new optional workspace_generator field."""
    tasks_dir = tmp_path / "tasks"
    _write_task(
        tasks_dir,
        "data_processing",
        "with_gen",
        overrides={"workspace_generator": "workspace/generator.py"},
    )
    tasks = load_tasks(tasks_dir)
    assert len(tasks) == 1
    assert tasks[0].workspace_generator == "workspace/generator.py"


def test_workspace_generator_omitted_defaults_none(tmp_path: Path) -> None:
    tasks_dir = tmp_path / "tasks"
    _write_task(tasks_dir, "data_processing", "no_gen")
    tasks = load_tasks(tasks_dir)
    assert tasks[0].workspace_generator is None


def test_workspace_generator_wrong_type_rejected(tmp_path: Path) -> None:
    tasks_dir = tmp_path / "tasks"
    _write_task(
        tasks_dir,
        "data_processing",
        "bad_gen",
        overrides={"workspace_generator": 42},
    )
    with pytest.raises(ValueError, match="workspace_generator must be a string"):
        load_tasks(tasks_dir)
