"""Hidden grader for stateful_reasoning__upgrade_impact.

Contract: ``grade(scratch_dir: Path) -> GradeResult``. See docs/SCHEMA_ARTIFACT.md §3.

Correctness criterion:

    The agent's output/conflicts.jsonl MUST list exactly those packages whose
    dependency constraint on the upgraded package is NOT satisfied by the new
    version. Set equality on package names (constraint detail not graded).

    Grader implements a pure-Python semver constraint checker covering:
      ^X.Y.Z  → >=X.Y.Z <(X+1).0.0  (or <0.(Y+1).0 if X==0)
      ~X.Y.Z  → >=X.Y.Z <X.(Y+1).0
      >=X.Y.Z / >X.Y.Z / <=X.Y.Z / <X.Y.Z
      X.Y.Z   → exact match

Determinism: pure function of workspace/packages.json. No randomness.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


INPUT_REL = "packages.json"
OUTPUT_REL = "output/conflicts.jsonl"


def _parse_semver(v: str) -> tuple[int, int, int]:
    parts = v.strip().split(".")
    return (int(parts[0]), int(parts[1]), int(parts[2]))


def _satisfies(constraint: str, version: str) -> bool:
    """Return True if version satisfies the npm-style semver constraint."""
    ver = _parse_semver(version)
    c = constraint.strip()

    if c.startswith("^"):
        base = _parse_semver(c[1:])
        if base[0] > 0:
            upper = (base[0] + 1, 0, 0)
        elif base[1] > 0:
            upper = (0, base[1] + 1, 0)
        else:
            upper = (0, 0, base[2] + 1)
        return base <= ver < upper
    if c.startswith("~"):
        base = _parse_semver(c[1:])
        upper = (base[0], base[1] + 1, 0)
        return base <= ver < upper
    if c.startswith(">="):
        return ver >= _parse_semver(c[2:])
    if c.startswith(">"):
        return ver > _parse_semver(c[1:])
    if c.startswith("<="):
        return ver <= _parse_semver(c[2:])
    if c.startswith("<"):
        return ver < _parse_semver(c[1:])
    # Exact
    return ver == _parse_semver(c)


def _compute_conflicts(packages_data: dict) -> set[str]:
    upgrade_pkg = packages_data["upgrade"]["package"]
    new_version = packages_data["upgrade"]["to"]
    conflicts: set[str] = set()
    for pkg_name, pkg_info in packages_data["packages"].items():
        deps = pkg_info.get("dependencies", {})
        if upgrade_pkg in deps:
            constraint = deps[upgrade_pkg]
            if not _satisfies(constraint, new_version):
                conflicts.add(pkg_name)
    return conflicts


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()

    input_path = scratch_dir / INPUT_REL
    if not input_path.is_file():
        return GradeResult(False, 0.0, f"input {INPUT_REL} not found in scratch dir")

    packages_data = json.loads(input_path.read_text())

    output_path = scratch_dir / OUTPUT_REL
    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    raw = output_path.read_text()
    if not raw.strip():
        return GradeResult(False, 0.0, "output artifact is empty")

    agent_pkgs: set[str] = set()
    for lineno, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            return GradeResult(False, 0.0, f"line {lineno}: JSON parse error: {exc.msg}")
        if not isinstance(obj, dict):
            return GradeResult(False, 0.0, f"line {lineno}: expected JSON object")
        if "package" not in obj:
            return GradeResult(False, 0.0, f"line {lineno}: missing 'package' key")
        pkg = obj["package"]
        if not isinstance(pkg, str):
            return GradeResult(False, 0.0, f"line {lineno}: 'package' must be a string")
        if pkg in agent_pkgs:
            return GradeResult(False, 0.0, f"duplicate package: {pkg!r}")
        agent_pkgs.add(pkg)

    reference = _compute_conflicts(packages_data)

    missing = reference - agent_pkgs
    extra = agent_pkgs - reference

    if missing or extra:
        parts = []
        if missing:
            parts.append(f"missing {len(missing)} package(s): {sorted(missing)}")
        if extra:
            parts.append(f"{len(extra)} incorrect package(s): {sorted(extra)}")
        return GradeResult(
            False,
            round(len(agent_pkgs & reference) / max(len(reference), 1), 4),
            "; ".join(parts),
        )

    return GradeResult(True, 1.0, f"all {len(reference)} conflicts identified correctly")
