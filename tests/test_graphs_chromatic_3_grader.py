"""Regression tests for the enumeration__graphs_chromatic_3 hidden grader.

Locks in the post-#169 contract:
  * grade(reference) → passed=True, score=1.0
  * grade-time wall on the reference output stays under 1 second
  * the grader never imports networkx (fail-fast if the hard dep slips back in)
  * the frozen reference set contains exactly 64 graphs
"""

from __future__ import annotations

import importlib
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TASK_DIR = REPO_ROOT / "problems" / "artifact" / "enumeration" / "graphs_chromatic_3"
GRADER_FILE = TASK_DIR / "grader" / "hidden.py"
REF_FILE = TASK_DIR / "grader" / "reference_output.jsonl"


def _load_grade():
    """Import the grader's grade() function via path manipulation."""
    grader_dir = str(GRADER_FILE.parent)
    if grader_dir not in sys.path:
        sys.path.insert(0, grader_dir)
    if "hidden" in sys.modules:
        return importlib.reload(sys.modules["hidden"]).grade
    from hidden import grade
    return grade


def _write_output(scratch: Path, text: str) -> None:
    output_dir = scratch / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "graphs.jsonl").write_text(text)


def test_grader_does_not_import_networkx() -> None:
    """The grader must not depend on networkx at grade time (issue #169)."""
    grader_text = GRADER_FILE.read_text()
    assert "import networkx" not in grader_text
    assert "from networkx" not in grader_text


def test_reference_has_64_lines() -> None:
    """The frozen reference set must contain exactly 64 graphs (OEIS-style count)."""
    n = sum(1 for line in REF_FILE.read_text().splitlines() if line.strip())
    assert n == 64


def test_grade_reference_passes(tmp_path: Path) -> None:
    """grade(reference_output.jsonl) → passed=True, score=1.0."""
    _write_output(tmp_path, REF_FILE.read_text())
    grade = _load_grade()
    result = grade(tmp_path)
    assert result.passed is True
    assert result.score == 1.0


def test_grade_time_under_one_second(tmp_path: Path) -> None:
    """SCHEMA §3.2.6: grade-time wall under 1 second on the reference output."""
    _write_output(tmp_path, REF_FILE.read_text())
    grade = _load_grade()
    t0 = time.time()
    result = grade(tmp_path)
    dt = time.time() - t0
    assert result.passed is True
    assert dt < 1.0, f"grade took {dt:.2f}s (issue #169 budget is < 1s)"


def test_grade_handles_relabelled_reference(tmp_path: Path) -> None:
    """Submitting the reference set under a vertex relabelling still passes."""
    import json

    perm = (5, 4, 3, 2, 1, 0)
    out_lines = []
    for line in REF_FILE.read_text().splitlines():
        if not line.strip():
            continue
        edges = json.loads(line)
        new = []
        for u, v in edges:
            pu, pv = perm[u], perm[v]
            if pu > pv:
                pu, pv = pv, pu
            new.append([pu, pv])
        new.sort()
        out_lines.append(json.dumps(new))
    _write_output(tmp_path, "\n".join(out_lines) + "\n")

    grade = _load_grade()
    result = grade(tmp_path)
    assert result.passed is True
    assert result.score == 1.0


def test_grade_rejects_chi2_graph(tmp_path: Path) -> None:
    """A bipartite (chi=2) graph must be flagged with the chi diagnostic."""
    import json

    tree = [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5]]
    _write_output(tmp_path, json.dumps(tree) + "\n")
    grade = _load_grade()
    result = grade(tmp_path)
    assert result.passed is False
    assert "chromatic number is 2" in result.detail


def test_grade_rejects_disconnected_graph(tmp_path: Path) -> None:
    """A graph leaving vertices 3,4,5 isolated must trip the connectivity check."""
    import json

    triangle = [[0, 1], [1, 2], [0, 2]]
    _write_output(tmp_path, json.dumps(triangle) + "\n")
    grade = _load_grade()
    result = grade(tmp_path)
    assert result.passed is False
    assert "not connected" in result.detail


def test_grade_rejects_isomorphism_duplicate(tmp_path: Path) -> None:
    """Submitting two isomorphic copies of the same graph must be rejected."""
    import json

    first_line = next(line for line in REF_FILE.read_text().splitlines() if line.strip())
    edges = json.loads(first_line)
    perm = (5, 4, 3, 2, 1, 0)
    relabelled = sorted(
        sorted([perm[u], perm[v]]) for u, v in edges
    )
    _write_output(tmp_path, first_line + "\n" + json.dumps(relabelled) + "\n")
    grade = _load_grade()
    result = grade(tmp_path)
    assert result.passed is False
    assert "duplicate" in result.detail
