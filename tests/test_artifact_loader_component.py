"""Component tests: artifact_loader <-> artifact_models.Task (optional fields).

Boundary: swebench.artifact_loader._parse_task_yaml / load_tasks
  -> swebench.artifact_models.Task (tags, structural_verifier fields)
  -> real task.yaml manifests for verification_heavy category

These tests guard the contract between the YAML-parsing layer and the Task
dataclass for fields added alongside or exercised by the new
verification_heavy tasks introduced in issue #185:

  * tags: list[str] — optional list of free-form label strings
  * structural_verifier: str | None — optional relative path to verify.py
  * verification_heavy category — allowlisted since #128; first real manifests
    appear in this PR

None of these are exercised by the existing test_artifact_loader.py unit tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from swebench.artifact_loader import load_tasks


# ─── helpers ──────────────────────────────────────────────────────────────────

def _write_task(
    tasks_dir: Path,
    category: str,
    slug: str,
    overrides: dict | None = None,
) -> Path:
    """Write a minimal valid task.yaml under tasks_dir/<category>/<slug>/."""
    task_dir = tasks_dir / category / slug
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "workspace").mkdir(exist_ok=True)
    (task_dir / "grader").mkdir(exist_ok=True)
    (task_dir / "prompt.md").write_text("do the thing\n")
    (task_dir / "grader" / "hidden.py").write_text(
        "def grade(d):\n    class R:\n        passed=True\n        score=1.0\n        detail='ok'\n    return R()\n"
    )
    (task_dir / "grader" / "reference_output.txt").write_text("ref\n")

    data: dict = {
        "instance_id": f"{category}__{slug}",
        "category": category,
        "difficulty": "medium",
        "problem_statement": "prompt.md",
        "workspace_dir": "workspace/",
        "output_artifact": "output/result.jsonl",
        "hidden_grader": "grader/hidden.py",
        "reference_output": "grader/reference_output.txt",
        "execution_budget": {"max_code_runs": 10, "max_wall_seconds": 120},
    }
    if overrides:
        data.update(overrides)
    with open(task_dir / "task.yaml", "w") as f:
        yaml.safe_dump(data, f, sort_keys=False)
    return task_dir


# ─── Boundary: tags field round-trip ──────────────────────────────────────────

def test_tags_list_round_trips_through_loader(tmp_path: Path) -> None:
    """Loader must parse a tags list from task.yaml into Task.tags intact."""
    tasks_dir = tmp_path / "tasks"
    _write_task(
        tasks_dir,
        "verification_heavy",
        "tagged_task",
        overrides={
            "tags": [
                "verification_heavy",
                "static_analysis",
                "call_graph",
                "python",
                "realism_checklist_v1",
            ]
        },
    )

    tasks = load_tasks(tasks_dir)

    assert len(tasks) == 1
    task = tasks[0]
    assert task.tags == [
        "verification_heavy",
        "static_analysis",
        "call_graph",
        "python",
        "realism_checklist_v1",
    ], f"unexpected tags: {task.tags}"


def test_tags_absent_defaults_to_empty_list(tmp_path: Path) -> None:
    """When task.yaml has no tags key, Task.tags must be an empty list (not None)."""
    tasks_dir = tmp_path / "tasks"
    _write_task(tasks_dir, "verification_heavy", "no_tags")

    tasks = load_tasks(tasks_dir)

    assert len(tasks) == 1
    assert tasks[0].tags == [], f"expected empty list, got {tasks[0].tags!r}"


def test_tags_wrong_type_rejected(tmp_path: Path) -> None:
    """A tags value that is not list[str] must cause a ValueError at load time."""
    tasks_dir = tmp_path / "tasks"
    _write_task(
        tasks_dir,
        "verification_heavy",
        "bad_tags",
        overrides={"tags": "not-a-list"},
    )

    with pytest.raises(ValueError, match="tags must be list"):
        load_tasks(tasks_dir)


# ─── Boundary: structural_verifier field round-trip ───────────────────────────

def test_structural_verifier_round_trips_through_loader(tmp_path: Path) -> None:
    """Loader must preserve the structural_verifier path string into Task."""
    tasks_dir = tmp_path / "tasks"
    _write_task(
        tasks_dir,
        "verification_heavy",
        "with_verifier",
        overrides={"structural_verifier": "workspace/verify.py"},
    )

    tasks = load_tasks(tasks_dir)

    assert len(tasks) == 1
    assert tasks[0].structural_verifier == "workspace/verify.py", (
        f"unexpected structural_verifier: {tasks[0].structural_verifier!r}"
    )


def test_structural_verifier_absent_defaults_to_none(tmp_path: Path) -> None:
    """When task.yaml omits structural_verifier, Task.structural_verifier is None."""
    tasks_dir = tmp_path / "tasks"
    _write_task(tasks_dir, "verification_heavy", "no_verifier")

    tasks = load_tasks(tasks_dir)

    assert len(tasks) == 1
    assert tasks[0].structural_verifier is None, (
        f"expected None, got {tasks[0].structural_verifier!r}"
    )


def test_structural_verifier_wrong_type_rejected(tmp_path: Path) -> None:
    """A structural_verifier that is not a string must cause a ValueError."""
    tasks_dir = tmp_path / "tasks"
    _write_task(
        tasks_dir,
        "verification_heavy",
        "bad_verifier",
        overrides={"structural_verifier": 42},
    )

    with pytest.raises(ValueError, match="structural_verifier must be a string"):
        load_tasks(tasks_dir)


# ─── Boundary: verification_heavy category + combined optional fields ─────────

def test_verification_heavy_category_accepted_by_loader(tmp_path: Path) -> None:
    """Loader must accept category=verification_heavy; failing this would silently
    drop all verification_heavy tasks from the benchmark run."""
    tasks_dir = tmp_path / "tasks"
    _write_task(tasks_dir, "verification_heavy", "reachability")

    tasks = load_tasks(tasks_dir)

    assert len(tasks) == 1
    assert tasks[0].category == "verification_heavy"
    assert tasks[0].instance_id == "verification_heavy__reachability"


def test_verification_heavy_task_with_all_optional_fields(tmp_path: Path) -> None:
    """A task.yaml matching the actual unreachable_functions / upgrade_impact
    layout (tags + structural_verifier + non-zero budget) must load without error
    and expose all fields correctly.

    This exercises the exact combination that the PR's real task.yaml files use,
    so a future refactor that drops either optional field from the Task dataclass
    or the loader will be caught here.
    """
    tasks_dir = tmp_path / "tasks"
    _write_task(
        tasks_dir,
        "verification_heavy",
        "full_manifest",
        overrides={
            "structural_verifier": "workspace/verify.py",
            "tags": [
                "verification_heavy",
                "static_analysis",
                "realism_checklist_v1",
            ],
        },
    )

    tasks = load_tasks(tasks_dir)

    assert len(tasks) == 1
    task = tasks[0]
    assert task.structural_verifier == "workspace/verify.py"
    assert "realism_checklist_v1" in task.tags
    assert task.execution_budget.max_code_runs == 10
    assert task.execution_budget.max_wall_seconds == 120
    assert not task.execution_budget.is_unlimited


def test_real_verification_heavy_tasks_load_from_problems_dir() -> None:
    """The two real task.yaml files added by issue #185 must be discoverable and
    parse-able by the loader from the canonical problems/ directory.

    This catches regressions where a task.yaml field name or category enum value
    diverges from what the loader enforces.

    Note: load_tasks expects the root that contains <category>/<slug>/task.yaml
    — i.e., problems/artifact/, not problems/artifact/verification_heavy/.
    We load from problems/artifact/ and filter to the two target instance_ids.
    """
    repo_root = Path(__file__).resolve().parent.parent
    tasks_dir = repo_root / "problems" / "artifact"

    if not (tasks_dir / "verification_heavy").is_dir():
        pytest.skip("problems/artifact/verification_heavy/ not present in this checkout")

    tasks = load_tasks(
        tasks_dir,
        filter_ids={
            "verification_heavy__unreachable_functions",
            "verification_heavy__upgrade_impact",
        },
    )

    instance_ids = {t.instance_id for t in tasks}
    assert "verification_heavy__unreachable_functions" in instance_ids, (
        f"unreachable_functions task not found; got: {sorted(instance_ids)}"
    )
    assert "verification_heavy__upgrade_impact" in instance_ids, (
        f"upgrade_impact task not found; got: {sorted(instance_ids)}"
    )

    unreachable = next(t for t in tasks if "unreachable" in t.instance_id)
    assert unreachable.category == "verification_heavy"
    assert unreachable.output_artifact == "output/unreachable.jsonl"
    assert unreachable.structural_verifier is not None
    assert "realism_checklist_v1" in unreachable.tags

    upgrade = next(t for t in tasks if "upgrade" in t.instance_id)
    assert upgrade.category == "verification_heavy"
    assert upgrade.output_artifact == "output/conflicts.jsonl"
    assert upgrade.structural_verifier is not None
    assert "realism_checklist_v1" in upgrade.tags
