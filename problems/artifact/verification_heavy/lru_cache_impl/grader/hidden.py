"""Hidden grader for verification_heavy__lru_cache_impl.

Contract: ``grade(scratch_dir: Path) -> GradeResult``. See docs/SCHEMA_ARTIFACT.md §3.

Correctness criterion:

    The agent's output/lru_cache.py must define ``LRUCache(capacity)`` with
    ``get(key) -> int`` (returns -1 on miss) and ``put(key, value) -> None``.
    30 deterministic property tests covering: basic operations, capacity
    enforcement, access-order recency (get updates LRU), put-recency,
    capacity-1 edge case, and seeded random operation sequences.

Determinism: all test cases are fixed constants or seeded from instance_id.
"""

from __future__ import annotations

import importlib.util
import random
import traceback
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


OUTPUT_REL = "output/lru_cache.py"


def _import_module(solution_path: Path):
    spec = importlib.util.spec_from_file_location("agent_lru", solution_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_tests(LRUCache) -> list[str]:  # noqa: N803
    failures: list[str] = []

    def check(name: str, got, expected):
        if got != expected:
            failures.append(f"  [{name}] expected {expected!r}, got {got!r}")

    # ── Group 1: basic put/get ────────────────────────────────────────────
    c = LRUCache(3)
    c.put(1, 10)
    check("g1-get-present", c.get(1), 10)
    check("g1-get-absent", c.get(99), -1)
    c.put(1, 20)  # overwrite
    check("g1-overwrite", c.get(1), 20)

    # ── Group 2: capacity enforcement ────────────────────────────────────
    c = LRUCache(2)
    c.put(1, 1)
    c.put(2, 2)
    c.put(3, 3)  # evicts 1 (LRU)
    check("g2-evicted", c.get(1), -1)
    check("g2-kept-2", c.get(2), 2)
    check("g2-kept-3", c.get(3), 3)

    # ── Group 3: get updates recency ─────────────────────────────────────
    c = LRUCache(2)
    c.put(1, 1)
    c.put(2, 2)
    c.get(1)      # access 1 → 2 is now LRU
    c.put(3, 3)   # should evict 2, not 1
    check("g3-get-recency-evict-2", c.get(2), -1)
    check("g3-get-recency-keep-1", c.get(1), 1)
    check("g3-get-recency-keep-3", c.get(3), 3)

    # ── Group 4: put updates recency ─────────────────────────────────────
    c = LRUCache(2)
    c.put(1, 1)
    c.put(2, 2)
    c.put(1, 111)  # re-put 1 → 2 is now LRU
    c.put(3, 3)    # should evict 2
    check("g4-put-recency-evict-2", c.get(2), -1)
    check("g4-put-recency-keep-1", c.get(1), 111)
    check("g4-put-recency-keep-3", c.get(3), 3)

    # ── Group 5: capacity = 1 ────────────────────────────────────────────
    c = LRUCache(1)
    c.put(1, 1)
    check("g5-cap1-get", c.get(1), 1)
    c.put(2, 2)
    check("g5-cap1-evict-1", c.get(1), -1)
    check("g5-cap1-keep-2", c.get(2), 2)
    c.put(2, 22)  # overwrite same key
    check("g5-cap1-overwrite", c.get(2), 22)

    # ── Group 6: sequential eviction order ───────────────────────────────
    c = LRUCache(3)
    for k in (1, 2, 3):
        c.put(k, k * 10)
    c.put(4, 40)  # evicts 1
    check("g6-seq-evict-1", c.get(1), -1)
    c.put(5, 50)  # evicts 2
    check("g6-seq-evict-2", c.get(2), -1)
    check("g6-seq-keep-3", c.get(3), 30)
    check("g6-seq-keep-4", c.get(4), 40)
    check("g6-seq-keep-5", c.get(5), 50)

    # ── Group 7: seeded random sequence (10 ops) ─────────────────────────
    rng = random.Random("verification_heavy__lru_cache_impl:seq1")
    cap = 4
    c = LRUCache(cap)
    ref: dict[int, int] = {}
    lru_order: list[int] = []  # most-recent at end

    def ref_put(k, v):
        if k in ref:
            lru_order.remove(k)
        elif len(ref) >= cap:
            evicted = lru_order.pop(0)
            del ref[evicted]
        ref[k] = v
        lru_order.append(k)

    def ref_get(k):
        if k not in ref:
            return -1
        lru_order.remove(k)
        lru_order.append(k)
        return ref[k]

    ops = []
    for _ in range(20):
        key = rng.randint(1, 6)
        if rng.random() < 0.5:
            val = rng.randint(1, 100)
            c.put(key, val)
            ref_put(key, val)
            ops.append(f"put({key},{val})")
        else:
            got = c.get(key)
            expected = ref_get(key)
            if got != expected:
                failures.append(
                    f"  [g7-random] after {ops}: get({key})={got!r}, expected {expected!r}"
                )
                break
            ops.append(f"get({key})->{got}")

    # ── Group 8: seeded random sequence (another 10 ops, different seed) ─
    rng2 = random.Random("verification_heavy__lru_cache_impl:seq2")
    cap2 = 3
    c2 = LRUCache(cap2)
    ref2: dict[int, int] = {}
    lru2: list[int] = []

    def ref_put2(k, v):
        if k in ref2:
            lru2.remove(k)
        elif len(ref2) >= cap2:
            evicted = lru2.pop(0)
            del ref2[evicted]
        ref2[k] = v
        lru2.append(k)

    def ref_get2(k):
        if k not in ref2:
            return -1
        lru2.remove(k)
        lru2.append(k)
        return ref2[k]

    ops2 = []
    for _ in range(20):
        key = rng2.randint(1, 5)
        if rng2.random() < 0.45:
            val = rng2.randint(10, 90)
            c2.put(key, val)
            ref_put2(key, val)
            ops2.append(f"put({key},{val})")
        else:
            got = c2.get(key)
            expected = ref_get2(key)
            if got != expected:
                failures.append(
                    f"  [g8-random] after {ops2}: get({key})={got!r}, expected {expected!r}"
                )
                break
            ops2.append(f"get({key})->{got}")

    return failures


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()
    solution_path = scratch_dir / OUTPUT_REL

    if not solution_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced (output/lru_cache.py missing)")

    try:
        mod = _import_module(solution_path)
    except Exception as exc:
        tb = traceback.format_exc()
        return GradeResult(False, 0.0, f"failed to import lru_cache.py: {exc}\n{tb[:400]}")

    if not hasattr(mod, "LRUCache"):
        return GradeResult(False, 0.0, "lru_cache.py does not define 'LRUCache'")

    LRUCache = mod.LRUCache  # noqa: N806
    try:
        failures = _run_tests(LRUCache)
    except Exception as exc:
        tb = traceback.format_exc()
        return GradeResult(False, 0.0, f"grader error running tests: {exc}\n{tb[:400]}")

    # Count total assertion calls as a proxy for total tests
    # (groups 1-8 contain ~30 assertions; random groups may short-circuit)
    total_tests = 30
    n_fail = len(failures)
    n_pass = max(0, total_tests - n_fail)

    if failures:
        detail = f"{n_pass}/{total_tests} checks passed. Failures:\n" + "\n".join(failures[:10])
        if len(failures) > 10:
            detail += f"\n  ... ({len(failures) - 10} more)"
        return GradeResult(False, round(n_pass / total_tests, 4), detail)

    return GradeResult(True, 1.0, f"all {total_tests} property tests passed")
