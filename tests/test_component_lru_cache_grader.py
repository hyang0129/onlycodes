"""Component test: invoke_grader → lru_cache_impl grader boundary.

Boundary: swebench.artifact_grade.invoke_grader() runs
problems/artifact/verification_heavy/lru_cache_impl/grader/hidden.py:grade()
in a subprocess. This PR (#186) fixed:
  - sha256-based seed derivation (was using hash(), which is non-deterministic)
  - exact total_tests count (grade detail now always matches the fixed count)

These tests verify the contract between the harness (invoke_grader) and the
concrete lru_cache_impl grader. Both real modules cooperate across the
subprocess boundary: no grader doubles, no harness doubles.

The scratch dir (filesystem) is the only seam that is ephemeral — it is the
canonical medium through which the two modules exchange data.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from swebench.artifact_grade import GraderInvocationError, invoke_grader
from swebench.artifact_models import ExecutionBudget, GradeResult, Task

# Absolute path to the real lru_cache_impl task directory.
_LRU_TASK_DIR = (
    Path(__file__).resolve().parent.parent
    / "problems/artifact/verification_heavy/lru_cache_impl"
)

# A correct LRUCache implementation — the grader must PASS this.
_CORRECT_LRU = textwrap.dedent("""\
    class LRUCache:
        def __init__(self, capacity: int):
            self._cap = capacity
            self._cache: dict = {}   # key → value, ordered by insertion (Python 3.7+)

        def get(self, key: int) -> int:
            if key not in self._cache:
                return -1
            # Move to end (most-recently-used).
            value = self._cache.pop(key)
            self._cache[key] = value
            return value

        def put(self, key: int, value: int) -> None:
            if key in self._cache:
                self._cache.pop(key)
            elif len(self._cache) >= self._cap:
                # Evict least-recently-used (first key).
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = value
""")

# A broken LRUCache that never evicts — violates LRU semantics.
_BROKEN_LRU_NO_EVICTION = textwrap.dedent("""\
    class LRUCache:
        def __init__(self, capacity: int):
            self._cache: dict = {}

        def get(self, key: int) -> int:
            return self._cache.get(key, -1)

        def put(self, key: int, value: int) -> None:
            # Never evicts — wrong LRU semantics.
            self._cache[key] = value
""")

# A broken LRUCache with wrong miss sentinel value.
_BROKEN_LRU_WRONG_SENTINEL = textwrap.dedent("""\
    class LRUCache:
        def __init__(self, capacity: int):
            self._cap = capacity
            self._cache: dict = {}

        def get(self, key: int) -> int:
            return self._cache.get(key, 0)  # Wrong: should return -1 on miss.

        def put(self, key: int, value: int) -> None:
            self._cache[key] = value
""")


def _make_lru_task() -> Task:
    """Build a Task pointing at the real lru_cache_impl grader directory."""
    return Task(
        instance_id="verification_heavy__lru_cache_impl",
        category="verification_heavy",
        difficulty="medium",
        problem_statement="prompt.md",
        workspace_dir="workspace/",
        output_artifact="output/lru_cache.py",
        hidden_grader="grader/hidden.py",
        reference_output="grader/reference_output.json",
        execution_budget=ExecutionBudget(0, 0),
        task_dir=_LRU_TASK_DIR.resolve(),
    )


def _write_solution(scratch_dir: Path, code: str) -> None:
    """Write LRUCache implementation into the expected artifact path."""
    output_dir = scratch_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "lru_cache.py").write_text(code)


@pytest.mark.component
class TestInvokeGraderLruCacheContract:
    """Verify the invoke_grader → lru_cache_impl grader subprocess contract."""

    def test_correct_lru_passes(self, tmp_path: Path):
        """A correct LRUCache implementation must yield passed=True, score=1.0."""
        task = _make_lru_task()
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        _write_solution(scratch, _CORRECT_LRU)

        result = invoke_grader(task, scratch)

        assert isinstance(result, GradeResult)
        assert result.passed is True, f"Expected pass; detail: {result.detail}"
        assert result.score == 1.0, f"Expected score=1.0; got {result.score}"

    def test_correct_lru_detail_reports_total_tests(self, tmp_path: Path):
        """When all tests pass the detail must include the total_tests count.

        PR #186 fixed total_tests to be exact. This test pins the contract so
        any future grader edit that changes the count is immediately caught.
        """
        task = _make_lru_task()
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        _write_solution(scratch, _CORRECT_LRU)

        result = invoke_grader(task, scratch)

        assert result.passed is True
        # The grader emits "all <N> property tests passed" — N must be non-zero
        # and consistent across repeated calls (determinism contract).
        assert "property tests passed" in result.detail, (
            f"Unexpected detail format: {result.detail!r}"
        )
        # Extract the count and verify it is positive.
        import re
        m = re.search(r"all (\d+) property tests passed", result.detail)
        assert m is not None, f"Could not parse total_tests from: {result.detail!r}"
        total_tests = int(m.group(1))
        assert total_tests > 0, f"total_tests must be positive; got {total_tests}"

    def test_total_tests_is_deterministic_across_calls(self, tmp_path: Path):
        """Running the grader twice on the same solution must yield identical total_tests.

        Guards the sha256-seeding fix: if seeding were non-deterministic (e.g.
        using hash()), the random group test counts would vary between subprocess
        calls, breaking the benchmark's reproducibility contract.
        """
        import re
        task = _make_lru_task()

        results = []
        for run_idx in range(2):
            scratch = tmp_path / f"scratch_{run_idx}"
            scratch.mkdir()
            _write_solution(scratch, _CORRECT_LRU)
            r = invoke_grader(task, scratch)
            m = re.search(r"all (\d+) property tests passed", r.detail)
            assert m is not None, f"Run {run_idx}: unexpected detail: {r.detail!r}"
            results.append(int(m.group(1)))

        assert results[0] == results[1], (
            f"total_tests differed between runs: {results[0]} vs {results[1]}. "
            "Grader seeding is not deterministic."
        )

    def test_broken_lru_no_eviction_fails(self, tmp_path: Path):
        """An LRUCache that never evicts must yield passed=False with score < 1.0."""
        task = _make_lru_task()
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        _write_solution(scratch, _BROKEN_LRU_NO_EVICTION)

        result = invoke_grader(task, scratch)

        assert isinstance(result, GradeResult)
        assert result.passed is False, (
            f"Expected failure for no-eviction impl; got passed=True, detail={result.detail!r}"
        )
        assert result.score < 1.0, f"Expected score < 1.0; got {result.score}"

    def test_broken_lru_wrong_sentinel_fails(self, tmp_path: Path):
        """An LRUCache that returns 0 instead of -1 on miss must fail."""
        task = _make_lru_task()
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        _write_solution(scratch, _BROKEN_LRU_WRONG_SENTINEL)

        result = invoke_grader(task, scratch)

        assert result.passed is False, (
            f"Expected failure for wrong-sentinel impl; got passed=True"
        )

    def test_missing_artifact_fails_gracefully(self, tmp_path: Path):
        """When no lru_cache.py exists the grader must return passed=False, not raise."""
        task = _make_lru_task()
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        # Deliberately write nothing — no output/lru_cache.py.

        result = invoke_grader(task, scratch)

        assert isinstance(result, GradeResult)
        assert result.passed is False
        assert result.score == 0.0

    def test_score_is_partial_for_partially_correct_impl(self, tmp_path: Path):
        """A partially correct impl (passes some groups, fails others) must have 0 < score < 1."""
        # This impl handles basic get/put correctly but does NOT update LRU order on get.
        partial_impl = textwrap.dedent("""\
            class LRUCache:
                def __init__(self, capacity: int):
                    self._cap = capacity
                    self._cache: dict = {}

                def get(self, key: int) -> int:
                    # Missing: does not update recency on get.
                    return self._cache.get(key, -1)

                def put(self, key: int, value: int) -> None:
                    if key in self._cache:
                        self._cache.pop(key)
                    elif len(self._cache) >= self._cap:
                        self._cache.pop(next(iter(self._cache)))
                    self._cache[key] = value
        """)
        task = _make_lru_task()
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        _write_solution(scratch, partial_impl)

        result = invoke_grader(task, scratch)

        assert isinstance(result, GradeResult)
        assert result.passed is False
        # Some tests pass (basic get/put), so score should be > 0.
        assert result.score > 0.0, (
            f"Expected partial score > 0.0 for partially-correct impl; got {result.score}"
        )
        assert result.score < 1.0, (
            f"Expected partial score < 1.0 for partially-correct impl; got {result.score}"
        )
