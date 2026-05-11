"""Integration tests for ``verification_heavy__lru_cache_impl`` grader.

Scenario: slice-lru-grader
Tier: wiring

Verifies that the lru_cache_impl grader (updated in issue #186) correctly:
  1. Scores a correct LRUCache implementation at 1.0.
  2. Reports the exact number of tests run (not the old hardcoded 30).
  3. Uses sha256-based seeding (not the old string-seeded random).
  4. Scores a broken implementation below 1.0 (falsifiability check).
  5. Handles missing output artifact gracefully (score=0.0, passed=False).
  6. Handles import errors gracefully (score=0.0, passed=False).

The grader is invoked directly (subprocess isolation is not required for
wiring-tier tests — we're verifying the grader's interface contract, not
the full harness).

Key changes tested:
  - ``total_tests = len(results)`` (was hardcoded ``total_tests = 30``).
  - RNG seeds via ``int(sha256(instance_id + salt)[:8], 16)`` (was string-seeded).
  - Partial scoring: ``score = n_pass / total_tests`` (was ``max(0, 30 - failures) / 30``).
"""

from __future__ import annotations

import importlib.util
import sys
import textwrap
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Load the grader module directly (avoids modifying sys.path globally)
# ---------------------------------------------------------------------------

_GRADER_PATH = (
    Path(__file__).resolve().parent.parent
    / "problems"
    / "artifact"
    / "verification_heavy"
    / "lru_cache_impl"
    / "grader"
    / "hidden.py"
)


def _load_grader():
    name = "_lru_grader_itest"
    spec = importlib.util.spec_from_file_location(name, _GRADER_PATH)
    assert spec is not None and spec.loader is not None, (
        f"Cannot load grader from {_GRADER_PATH}"
    )
    mod = importlib.util.module_from_spec(spec)
    # Must register in sys.modules BEFORE exec_module so that @dataclass can
    # look up the module via cls.__module__ during class decoration.
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return mod


@pytest.fixture(scope="module")
def grader():
    return _load_grader()


# ---------------------------------------------------------------------------
# Reference implementation: a correct LRUCache
# ---------------------------------------------------------------------------

_CORRECT_IMPL = textwrap.dedent("""
    from collections import OrderedDict

    class LRUCache:
        def __init__(self, capacity: int) -> None:
            self._cap = capacity
            self._cache: OrderedDict[int, int] = OrderedDict()

        def get(self, key: int) -> int:
            if key not in self._cache:
                return -1
            self._cache.move_to_end(key)
            return self._cache[key]

        def put(self, key: int, value: int) -> None:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = value
            if len(self._cache) > self._cap:
                self._cache.popitem(last=False)
""")

# A broken implementation: get never updates recency (fails group 3 tests)
_BROKEN_IMPL_NO_RECENCY = textwrap.dedent("""
    class LRUCache:
        def __init__(self, capacity: int) -> None:
            self._cap = capacity
            self._cache: dict[int, int] = {}
            self._order: list[int] = []

        def get(self, key: int) -> int:
            # BUG: does not update recency on get
            return self._cache.get(key, -1)

        def put(self, key: int, value: int) -> None:
            if key in self._cache:
                self._order.remove(key)
            elif len(self._cache) >= self._cap:
                evicted = self._order.pop(0)
                del self._cache[evicted]
            self._cache[key] = value
            self._order.append(key)
""")


def _write_solution(scratch_dir: Path, code: str) -> None:
    out_dir = scratch_dir / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "lru_cache.py").write_text(code)


# ---------------------------------------------------------------------------
# Wiring tests
# ---------------------------------------------------------------------------


def test_grader_correct_implementation_passes(grader, tmp_path):
    """A correct LRUCache must score 1.0 and passed=True."""
    _write_solution(tmp_path, _CORRECT_IMPL)
    result = grader.grade(tmp_path)
    assert result.passed is True, f"Correct impl failed: {result.detail}"
    assert result.score == 1.0, f"Score was {result.score}, expected 1.0"


def test_grader_total_tests_is_exact_not_hardcoded(grader, tmp_path):
    """total_tests must equal the number of _Result objects, not the old constant 30.

    The previous implementation hardcoded ``total_tests = 30``. After issue #186
    it is ``len(results)``. The actual count (from groups 1–8) should be > 30
    because each op in the random sequences now produces a _Result.
    """
    _write_solution(tmp_path, _CORRECT_IMPL)
    result = grader.grade(tmp_path)
    # A perfect run says "all N property tests passed"
    assert "all" in result.detail and "property tests passed" in result.detail, (
        f"Unexpected detail format: {result.detail!r}"
    )
    # Extract the reported count
    import re
    m = re.search(r"all (\d+) property tests passed", result.detail)
    assert m is not None, f"Could not parse test count from: {result.detail!r}"
    reported_total = int(m.group(1))
    # The old hardcoded value was 30. The new approach counts actual checks.
    # Groups 1-6 have 14 fixed checks; groups 7-8 each run 20 ops with
    # (roughly 50%/55% chance of a get) — actual count varies but is well
    # above 14. The important contract: it must NOT be exactly 30 (the
    # old constant) and must be > 10 (sanity floor).
    assert reported_total > 10, (
        f"total_tests ({reported_total}) is suspiciously low — grader may not "
        "be running all groups"
    )
    # The old hardcoded 30 was wrong — if it's 30, the fix wasn't applied.
    # (This will only fail if by coincidence len(results) == 30, which is
    # astronomically unlikely given the random sequences produce variable counts.)
    # Instead, verify the number matches actual run_tests output.
    # Use the module-scoped fixture already loaded (passed in as `grader`).
    grader_mod = grader
    from collections import OrderedDict

    class _CorrectLRU:
        def __init__(self, cap):
            self._cap = cap
            self._cache = OrderedDict()

        def get(self, key):
            if key not in self._cache:
                return -1
            self._cache.move_to_end(key)
            return self._cache[key]

        def put(self, key, value):
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = value
            if len(self._cache) > self._cap:
                self._cache.popitem(last=False)

    actual_results = grader_mod._run_tests(_CorrectLRU)
    assert reported_total == len(actual_results), (
        f"Reported total {reported_total} != actual result count {len(actual_results)}"
    )


def test_grader_sha256_seed_used(grader):
    """The _seed_for function must use sha256, not a plain string seed.

    Verify that ``_seed_for(instance_id, salt)`` exists and returns an int
    (not a string), confirming the sha256 implementation is in place.
    """
    assert hasattr(grader, "_seed_for"), (
        "grader is missing _seed_for — sha256 seeding was not implemented"
    )
    seed = grader._seed_for("verification_heavy__lru_cache_impl", ":seq1")
    assert isinstance(seed, int), f"_seed_for must return int, got {type(seed)}"
    # The seed must be stable (deterministic)
    seed2 = grader._seed_for("verification_heavy__lru_cache_impl", ":seq1")
    assert seed == seed2, "_seed_for must be deterministic"
    # Different salts must produce different seeds
    seed_seq2 = grader._seed_for("verification_heavy__lru_cache_impl", ":seq2")
    assert seed != seed_seq2, "Different salts must produce different seeds"


def test_grader_broken_implementation_fails(grader, tmp_path):
    """A broken LRUCache (no get-recency) must score below 1.0 and passed=False.

    This is the falsifiability check: the grader must detect incorrect behavior.
    """
    _write_solution(tmp_path, _BROKEN_IMPL_NO_RECENCY)
    result = grader.grade(tmp_path)
    assert result.passed is False, (
        "Broken impl (no get-recency) incorrectly passed the grader"
    )
    assert result.score < 1.0, (
        f"Broken impl scored {result.score}, expected < 1.0"
    )
    assert result.score >= 0.0, "Score must be in [0.0, 1.0]"


def test_grader_partial_score_is_fraction(grader, tmp_path):
    """A partially correct implementation must score strictly between 0 and 1.

    Verifies the scoring formula is ``n_pass / total_tests`` (not floor-division
    or the old ``max(0, 30 - n_fail) / 30``).
    """
    _write_solution(tmp_path, _BROKEN_IMPL_NO_RECENCY)
    result = grader.grade(tmp_path)
    # The broken impl passes groups 1, 2, 4, 5, 6 (no-recency get) but fails group 3
    # and parts of the random sequences. Score must be strictly fractional.
    assert 0.0 < result.score < 1.0, (
        f"Expected partial score in (0.0, 1.0), got {result.score}"
    )


def test_grader_missing_output_file(grader, tmp_path):
    """Missing output/lru_cache.py must return passed=False, score=0.0."""
    # No solution written — output dir doesn't exist
    result = grader.grade(tmp_path)
    assert result.passed is False
    assert result.score == 0.0
    assert "missing" in result.detail.lower() or "not produced" in result.detail.lower(), (
        f"Expected 'missing' in detail, got: {result.detail!r}"
    )


def test_grader_import_error_handled(grader, tmp_path):
    """A solution with a syntax error must return passed=False, score=0.0."""
    _write_solution(tmp_path, "this is not valid python !!!!")
    result = grader.grade(tmp_path)
    assert result.passed is False
    assert result.score == 0.0
    assert "import" in result.detail.lower() or "failed" in result.detail.lower(), (
        f"Expected import error detail, got: {result.detail!r}"
    )


def test_grader_no_lrucache_class(grader, tmp_path):
    """A solution without an LRUCache class must return passed=False, score=0.0."""
    _write_solution(tmp_path, "# no class defined\nprint('hello')\n")
    result = grader.grade(tmp_path)
    assert result.passed is False
    assert result.score == 0.0
    assert "LRUCache" in result.detail or "does not define" in result.detail, (
        f"Expected missing-class detail, got: {result.detail!r}"
    )


def test_grader_instance_id_constant(grader):
    """INSTANCE_ID constant must match the task's declared instance_id."""
    assert grader.INSTANCE_ID == "verification_heavy__lru_cache_impl", (
        f"INSTANCE_ID mismatch: {grader.INSTANCE_ID!r}"
    )


def test_grader_result_detail_on_pass(grader, tmp_path):
    """On a passing run, detail must report all N tests passed (not empty)."""
    _write_solution(tmp_path, _CORRECT_IMPL)
    result = grader.grade(tmp_path)
    assert result.detail, "detail must not be empty on pass"
    assert "passed" in result.detail.lower(), (
        f"Expected 'passed' in detail: {result.detail!r}"
    )


def test_grader_failure_detail_names_failing_check(grader, tmp_path):
    """On failure, detail must include at least one check name (e.g. 'g3-...')."""
    _write_solution(tmp_path, _BROKEN_IMPL_NO_RECENCY)
    result = grader.grade(tmp_path)
    # The detail should contain at least one check name like [g3-get-recency-evict-2]
    assert "[g" in result.detail, (
        f"Expected named check in failure detail, got: {result.detail!r}"
    )
