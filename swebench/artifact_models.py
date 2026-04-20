"""Data models for artifact-graded benchmark tasks and results.

Kept deliberately separate from ``swebench/models.py`` so artifact mode does
not entangle with SWE-bench mode. See docs/SCHEMA_ARTIFACT.md for the frozen
on-disk schema this module mirrors.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ExecutionBudget:
    """Execution budget fields from task.yaml. 0 means unlimited (see SCHEMA §2.3)."""

    max_code_runs: int
    max_wall_seconds: int

    @property
    def enforcement(self) -> str:
        """Always 'OFF' for seed-v1 — no hard caps enforced yet."""
        return "OFF"

    @property
    def is_unlimited(self) -> bool:
        return self.max_code_runs == 0 and self.max_wall_seconds == 0


@dataclass(frozen=True)
class Task:
    """A single artifact-graded task.

    This is NOT an extension of ``swebench.models.Problem``. Artifact mode and
    SWE-bench mode use disjoint in-memory types.
    """

    instance_id: str
    category: str
    difficulty: str
    problem_statement: str      # relative path to prompt.md
    workspace_dir: str          # relative path, typically "workspace/"
    output_artifact: str        # relative to scratch dir
    hidden_grader: str          # relative path, typically "grader/hidden.py"
    reference_output: str       # relative path under grader/
    execution_budget: ExecutionBudget
    structural_verifier: str | None = None  # optional
    tags: list[str] = field(default_factory=list)
    task_dir: Path | None = None  # populated by loader; absolute path


@dataclass(frozen=True)
class GradeResult:
    """Result of invoking ``grader/hidden.py:grade(scratch_dir)``.

    Canonical import path for grader modules: ``from swebench.artifact_models
    import GradeResult``. The harness also accepts any object with matching
    ``passed: bool``, ``score: float``, ``detail: str`` attributes (structural
    typing — see SCHEMA §3.1).
    """

    passed: bool
    score: float
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "score": self.score, "detail": self.detail}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GradeResult":
        return cls(
            passed=bool(data["passed"]),
            score=float(data["score"]),
            detail=str(data["detail"]),
        )


@dataclass
class ArtifactArmResult:
    """Result of running one artifact-mode arm on one task.

    Parallels ``swebench.models.ArmResult`` but with artifact-specific fields.
    ``verdict`` follows the same "PASS" | "FAIL" | "ERROR" convention.
    """

    instance_id: str
    arm: str            # "code_only" | "tool_rich"
    run_idx: int
    verdict: str        # "PASS" | "FAIL" | "ERROR"
    grade_result: GradeResult | None
    budget: dict[str, Any]
    wall_secs: int
    cost_usd: float | None
    num_turns: int | None
    claude_version: str | None
    agent_jsonl_path: str
    # Issue #108: per-run leak audit. True if the agent transcript contained a
    # grader sentinel or a reference-output fingerprint for this task. Defaults
    # to False so pre-audit runs/data remain loadable.
    leak_detected: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["grade_result"] = self.grade_result.to_dict() if self.grade_result else None
        return d
