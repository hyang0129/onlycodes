"""Component test: invoke_grader → json_pointer_rfc6901 grader hidden.py boundary.

Boundary: swebench.artifact_grade.invoke_grader() runs
problems/artifact/verification_heavy/json_pointer_rfc6901/grader/hidden.py:grade()
in a subprocess. This PR (#188) cleaned up a duplicate ``""`` key in
``_base_doc()`` (the second ``"": "empty-key"  # duplicate intentional``
entry was removed, leaving only the first occurrence).

These tests verify the contract between the harness (invoke_grader) and the
concrete json_pointer_rfc6901 grader:
  - A correct RFC-6901 implementation must pass.
  - The empty-key pointer ``"/"`` (which resolves the ``""`` key) is tested
    by the grader and must still work after the deduplication.
  - A broken implementation (wrong escape handling) must fail.
  - A missing artifact must yield passed=False without raising.

Both real modules cooperate across the subprocess boundary: no grader doubles,
no harness doubles. The scratch dir (filesystem) is the only seam.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from swebench.artifact_grade import GraderInvocationError, invoke_grader
from swebench.artifact_models import ExecutionBudget, GradeResult, Task

# Absolute path to the real json_pointer_rfc6901 task directory.
_JP_TASK_DIR = (
    Path(__file__).resolve().parent.parent
    / "problems/artifact/verification_heavy/json_pointer_rfc6901"
)

# A correct RFC-6901 implementation mirroring the reference_output.py.
_CORRECT_SOLUTION = textwrap.dedent("""\
    def _unescape(token: str) -> str:
        return token.replace("~1", "/").replace("~0", "~")

    def _split(pointer: str) -> list:
        if pointer == "":
            return []
        if not pointer.startswith("/"):
            raise ValueError(f"invalid JSON pointer: {pointer!r}")
        return [_unescape(tok) for tok in pointer[1:].split("/")]

    def _as_array_index(token: str, length: int, *, allow_dash: bool) -> int:
        if token == "-":
            if not allow_dash:
                raise KeyError(f"'-' index not valid here")
            return length
        if token == "":
            raise KeyError("empty array index")
        if token != "0" and (not token.isdigit() or token[0] == "0"):
            raise KeyError(f"invalid array index {token!r}")
        if not token.isdigit():
            raise KeyError(f"invalid array index {token!r}")
        idx = int(token)
        return idx

    def resolve(doc, pointer: str):
        tokens = _split(pointer)
        if not tokens:
            return doc
        node = doc
        for i, token in enumerate(tokens):
            if isinstance(node, dict):
                if token not in node:
                    raise KeyError(f"key {token!r} not found")
                node = node[token]
            elif isinstance(node, list):
                idx = _as_array_index(token, len(node), allow_dash=False)
                if idx >= len(node):
                    raise KeyError(f"array index {idx} out of range")
                node = node[idx]
            else:
                raise KeyError(f"cannot traverse into {type(node).__name__}")
        return node

    def set_at(doc, pointer: str, value) -> None:
        if pointer == "":
            raise ValueError("cannot replace root document via set_at")
        tokens = _split(pointer)
        node = doc
        for token in tokens[:-1]:
            if isinstance(node, dict):
                if token not in node:
                    raise KeyError(f"key {token!r} not found (no auto-create)")
                node = node[token]
            elif isinstance(node, list):
                idx = _as_array_index(token, len(node), allow_dash=False)
                if idx >= len(node):
                    raise KeyError(f"array index {idx} out of range")
                node = node[idx]
            else:
                raise KeyError(f"cannot traverse into {type(node).__name__}")
        last = tokens[-1]
        if isinstance(node, dict):
            node[last] = value
        elif isinstance(node, list):
            idx = _as_array_index(last, len(node), allow_dash=True)
            if idx == len(node):
                node.append(value)
            elif idx < len(node):
                node[idx] = value
            else:
                raise KeyError(f"array index {idx} out of range (len={len(node)})")
        else:
            raise KeyError(f"cannot set on {type(node).__name__}")
""")

# A broken solution: incorrect escape order (decodes ~0 before ~1, violating RFC §4).
_BROKEN_ESCAPE_ORDER = textwrap.dedent("""\
    def _unescape(token: str) -> str:
        # BUG: wrong order — RFC 6901 requires ~1 first, then ~0.
        return token.replace("~0", "~").replace("~1", "/")

    def _split(pointer: str) -> list:
        if pointer == "":
            return []
        if not pointer.startswith("/"):
            raise ValueError(f"invalid JSON pointer: {pointer!r}")
        return [_unescape(tok) for tok in pointer[1:].split("/")]

    def resolve(doc, pointer: str):
        tokens = _split(pointer)
        if not tokens:
            return doc
        node = doc
        for token in tokens:
            if isinstance(node, dict):
                if token not in node:
                    raise KeyError(token)
                node = node[token]
            elif isinstance(node, list):
                node = node[int(token)]
            else:
                raise KeyError(token)
        return node

    def set_at(doc, pointer: str, value) -> None:
        if pointer == "":
            raise ValueError("cannot replace root")
        tokens = _split(pointer)
        node = doc
        for t in tokens[:-1]:
            if isinstance(node, dict):
                node = node[t]
            elif isinstance(node, list):
                node = node[int(t)]
        last = tokens[-1]
        if isinstance(node, dict):
            node[last] = value
        elif isinstance(node, list):
            if last == "-":
                node.append(value)
            else:
                node[int(last)] = value
""")


def _make_jp_task() -> Task:
    """Build a Task pointing at the real json_pointer_rfc6901 grader directory."""
    return Task(
        instance_id="verification_heavy__json_pointer_rfc6901",
        category="verification_heavy",
        difficulty="hard",
        problem_statement="prompt.md",
        workspace_dir="workspace/",
        output_artifact="output/solution.py",
        hidden_grader="grader/hidden.py",
        reference_output="grader/reference_output.py",
        execution_budget=ExecutionBudget(0, 0),
        task_dir=_JP_TASK_DIR.resolve(),
    )


def _write_solution(scratch_dir: Path, code: str) -> None:
    """Write the agent solution into the expected artifact path."""
    output_dir = scratch_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "solution.py").write_text(code)


@pytest.mark.component
class TestInvokeGraderJsonPointerContract:
    """Verify the invoke_grader → json_pointer_rfc6901 grader subprocess contract.

    Specifically guards the post-#188 state where _base_doc() no longer has
    a duplicate '' key — the grader must still handle the empty-key pointer
    ('/' → key '' → 'empty-key') correctly.
    """

    def test_correct_solution_passes(self, tmp_path: Path) -> None:
        """A correct RFC-6901 resolve+set_at implementation must yield passed=True, score=1.0."""
        task = _make_jp_task()
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        _write_solution(scratch, _CORRECT_SOLUTION)

        result = invoke_grader(task, scratch)

        assert isinstance(result, GradeResult)
        assert result.passed is True, (
            f"Expected correct impl to pass; detail: {result.detail}"
        )
        assert result.score == 1.0, f"Expected score=1.0; got {result.score}"

    def test_correct_solution_detail_mentions_all_cases(self, tmp_path: Path) -> None:
        """The grader detail must report 'all <N> cases passed' with N > 0.

        Pins the detail format contract so a future refactor that silently drops
        test cases is caught here.
        """
        task = _make_jp_task()
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        _write_solution(scratch, _CORRECT_SOLUTION)

        result = invoke_grader(task, scratch)

        assert result.passed is True
        assert "all" in result.detail and "cases passed" in result.detail, (
            f"Unexpected detail format; got: {result.detail!r}"
        )
        # Extract and verify the count is positive.
        import re
        m = re.search(r"all (\d+) cases passed", result.detail)
        assert m is not None, f"Could not parse case count from: {result.detail!r}"
        assert int(m.group(1)) > 0

    def test_broken_escape_order_fails(self, tmp_path: Path) -> None:
        """A solution with wrong ~0/~1 escape order must fail.

        The grader tests '/a~1b' (pointer for key 'a/b') and '/m~0n' (for
        'm~n') — both require correct RFC §4 escape ordering. This test pins
        that the grader's escape-ordering test cases catch the common bug.
        """
        task = _make_jp_task()
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        _write_solution(scratch, _BROKEN_ESCAPE_ORDER)

        result = invoke_grader(task, scratch)

        assert isinstance(result, GradeResult)
        assert result.passed is False, (
            f"Expected wrong-escape-order impl to fail; got passed=True, detail={result.detail!r}"
        )
        assert result.score < 1.0, f"Expected score < 1.0; got {result.score}"

    def test_missing_artifact_yields_failed_grade_not_exception(self, tmp_path: Path) -> None:
        """When no solution.py exists the grader must return passed=False, not raise.

        The harness contract: grader returns a GradeResult even on missing
        artifact. Only infrastructure failures raise GraderInvocationError.
        """
        task = _make_jp_task()
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        # Deliberately write nothing.

        result = invoke_grader(task, scratch)

        assert isinstance(result, GradeResult)
        assert result.passed is False
        assert result.score == 0.0

    def test_empty_key_pointer_resolved_after_dedup_cleanup(self, tmp_path: Path) -> None:
        """The '/' pointer (resolving the '' key) must still pass after the #188 dedup cleanup.

        Before #188, _base_doc() defined '' twice ('': 'empty-key' appeared as the
        first and fourth key). #188 removed the duplicate second occurrence.
        The grader's _RESOLVE_TESTS includes ('/','empty-key') — this test
        confirms the grader still exercises that case correctly and the correct
        solution passes it.
        """
        task = _make_jp_task()
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        _write_solution(scratch, _CORRECT_SOLUTION)

        result = invoke_grader(task, scratch)

        # The correct solution handles '/' → '' key → 'empty-key'.
        # If the grader's _base_doc() lost the '' key entirely (regression),
        # it would fail with KeyError on '/'' in _RESOLVE_TESTS, producing
        # a passed=False result from the grader.
        assert result.passed is True, (
            f"Empty-key pointer test case failed after #188 dedup cleanup; "
            f"detail: {result.detail}"
        )
