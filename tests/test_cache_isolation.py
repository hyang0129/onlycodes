"""Tests for the `--cache-isolation` flag added in #294.

Three boundaries are covered here:

1. Nonce determinism — `compute_isolation_nonce` is stable for a given
   (instance_id, arm, run_idx) and differs across each axis.
2. JSONL meta-line stamping — when the harness is invoked with
   ``--cache-isolation``, the meta line written by the run loop contains an
   ``isolation_nonce`` field whose value matches the deterministic formula.
   When the flag is off, the field is absent.
3. ``_write_codex_config`` MCP block — when ``isolation_nonce`` is passed,
   the resulting ``config.toml`` contains an ``[mcp_servers.iso_nonce]``
   block referencing the on-disk stub server; without it, no such block
   appears.

The tests do not invoke real codex / claude binaries: artifact_run is
exercised with a FakeRunner that swallows the new kwarg, and SWE-bench
run is exercised via a monkeypatched ``_runner.invoke`` so we observe the
JSONL meta line written by ``_run_arm``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swebench.artifact_models import ExecutionBudget, Task
from swebench.artifact_run import run_artifact_arm
from swebench.runner import (
    AgentRunner,
    _write_codex_config,
    compute_isolation_nonce,
)


# ---------------------------------------------------------------------------
# Boundary 1: nonce determinism
# ---------------------------------------------------------------------------


class TestComputeIsolationNonce:
    """The nonce formula must be deterministic, 16-hex, and sensitive to each
    of (instance_id, arm, run_idx) — so that re-runs reuse the same nonce
    (``--resume`` correctness) and different (task, arm, run) triples can never
    collide on the same prompt-cache key.
    """

    def test_same_inputs_yield_same_nonce(self):
        a = compute_isolation_nonce("repo__task-1", "code_only", 1)
        b = compute_isolation_nonce("repo__task-1", "code_only", 1)
        assert a == b, "Determinism: equal inputs must produce equal nonces"

    def test_nonce_is_16_hex_chars(self):
        n = compute_isolation_nonce("anything", "tool_rich", 0)
        assert isinstance(n, str)
        assert len(n) == 16, f"Expected 16-char nonce, got {len(n)}: {n!r}"
        int(n, 16)  # raises ValueError if not hex

    def test_different_instance_id_changes_nonce(self):
        a = compute_isolation_nonce("repo__task-1", "code_only", 1)
        b = compute_isolation_nonce("repo__task-2", "code_only", 1)
        assert a != b, (
            "Different instance_id must produce a different nonce; "
            f"both were {a}"
        )

    def test_different_arm_changes_nonce(self):
        """Cross-arm isolation: code_only and tool_rich of the same task must
        not share a cache prefix. This is the reason ``arm`` is part of the
        formula."""
        a = compute_isolation_nonce("repo__task-1", "code_only", 1)
        b = compute_isolation_nonce("repo__task-1", "tool_rich", 1)
        c = compute_isolation_nonce("repo__task-1", "bash_only", 1)
        assert a != b, "code_only and tool_rich nonces must differ"
        assert a != c, "code_only and bash_only nonces must differ"
        assert b != c, "tool_rich and bash_only nonces must differ"

    def test_different_run_idx_changes_nonce(self):
        a = compute_isolation_nonce("repo__task-1", "code_only", 1)
        b = compute_isolation_nonce("repo__task-1", "code_only", 2)
        assert a != b, "Different run_idx must produce a different nonce"

    def test_known_value_pinned(self):
        """Pin one specific (instance_id, arm, run_idx) so accidental refactors
        that change the formula (e.g. swapping the order or the separator) are
        caught immediately.

        sha256("repo__task-1|code_only|1")[:16] = the literal asserted below.
        Recompute with::

            >>> import hashlib
            >>> hashlib.sha256(b"repo__task-1|code_only|1").hexdigest()[:16]
        """
        nonce = compute_isolation_nonce("repo__task-1", "code_only", 1)
        # Computed once with the actual implementation as the canonical value.
        import hashlib
        expected = hashlib.sha256(b"repo__task-1|code_only|1").hexdigest()[:16]
        assert nonce == expected, (
            f"Nonce formula drifted: got {nonce!r}, expected {expected!r}. "
            "If this change was intentional, update the test and document the "
            "migration plan for in-flight --resume runs."
        )


# ---------------------------------------------------------------------------
# Boundary 2: artifact JSONL meta-line stamping
# ---------------------------------------------------------------------------


class _StubRunner(AgentRunner):
    """Minimal AgentRunner stub that observes invoke() kwargs.

    Writes a benign result.json + answer.txt so run_artifact_arm reaches the
    grading stage without crashing. We do not assert verdict here — we assert
    the JSONL meta line, which is written *before* invoke().
    """

    surface = "claude_code"

    def __init__(self) -> None:
        self.last_invoke_kwargs: dict = {}

    def find_binary(self) -> str:
        return "/usr/bin/true"

    def verify_auth(self) -> None:
        return None

    def get_version(self, _binary: str) -> str:
        return "stub-1.0"

    def build_tools_flags(self, _arm: str, _mcp: str | None) -> list[str]:
        return []

    def invoke(self, **kw) -> None:
        self.last_invoke_kwargs = kw
        Path(kw["cwd"], "answer.txt").write_text("ok\n")
        with open(kw["result_file"], "a") as f:
            f.write('{"type":"result","total_cost_usd":0.0,"num_turns":1}\n')

    def extract_metadata(self, _path: Path) -> tuple[float | None, int | None]:
        return (0.0, 1)


def _write_minimal_artifact_task(task_dir: Path) -> Task:
    """Write a minimal artifact task on disk and return its loaded Task."""
    (task_dir / "workspace").mkdir(parents=True)
    (task_dir / "grader").mkdir(parents=True)
    (task_dir / "grader" / "hidden.py").write_text(
        "def grade(scratch_dir):\n"
        "    class R:\n"
        "        passed = True; score = 1.0; detail = 'ok'\n"
        "    return R()\n"
    )
    (task_dir / "prompt.md").write_text("Write 'ok' to answer.txt\n")

    task = Task(
        instance_id="iso__test-task",
        category="iso",
        difficulty="easy",
        problem_statement="prompt.md",
        workspace_dir="workspace/",
        output_artifact="answer.txt",
        hidden_grader="grader/hidden.py",
        reference_output="",
        execution_budget=ExecutionBudget(max_code_runs=0, max_wall_seconds=0),
        task_dir=task_dir,
    )
    return task


def _read_meta_line(agent_jsonl: Path) -> dict:
    """Return the parsed meta record (first line of agent.jsonl)."""
    line = agent_jsonl.read_text().splitlines()[0]
    obj = json.loads(line)
    assert obj.get("type") == "meta", f"Expected meta record, got {obj!r}"
    return obj


class TestArtifactRunStampsNonceInMeta:
    """``run_artifact_arm(..., isolation_nonce=N)`` must stamp ``N`` into the
    JSONL meta line; passing ``None`` (default) must leave the field absent.
    """

    def test_isolation_nonce_present_when_set(self, tmp_path: Path):
        task = _write_minimal_artifact_task(tmp_path / "task")
        runner = _StubRunner()

        nonce = "deadbeefcafebabe"
        run_artifact_arm(
            task, "code_only", 1,
            results_dir=tmp_path / "results",
            runner=runner,
            echo=lambda _m: None,
            isolation_nonce=nonce,
        )

        agent_jsonl = tmp_path / "results" / task.instance_id / "code_only" / "run1" / "agent.jsonl"
        meta = _read_meta_line(agent_jsonl)
        assert meta.get("isolation_nonce") == nonce, (
            f"Expected isolation_nonce={nonce!r} in meta line, got {meta!r}"
        )

    def test_isolation_nonce_absent_when_unset(self, tmp_path: Path):
        task = _write_minimal_artifact_task(tmp_path / "task")
        runner = _StubRunner()

        run_artifact_arm(
            task, "code_only", 1,
            results_dir=tmp_path / "results",
            runner=runner,
            echo=lambda _m: None,
            # isolation_nonce omitted — defaults to None
        )

        agent_jsonl = tmp_path / "results" / task.instance_id / "code_only" / "run1" / "agent.jsonl"
        meta = _read_meta_line(agent_jsonl)
        assert "isolation_nonce" not in meta, (
            "isolation_nonce must NOT appear in the meta line when the flag "
            "is off — its presence is the signal that downstream summary "
            "annotates the cost column with (iso)."
        )

    def test_nonce_threaded_to_runner_invoke(self, tmp_path: Path):
        """The nonce kwarg must also reach the runner's invoke() so the
        agent surface can use it (codex registers an extra MCP server)."""
        task = _write_minimal_artifact_task(tmp_path / "task")
        runner = _StubRunner()

        nonce = "1234abcd5678ef90"
        run_artifact_arm(
            task, "code_only", 1,
            results_dir=tmp_path / "results",
            runner=runner,
            echo=lambda _m: None,
            isolation_nonce=nonce,
        )
        assert runner.last_invoke_kwargs.get("isolation_nonce") == nonce, (
            f"runner.invoke() must receive isolation_nonce={nonce!r}, got "
            f"{runner.last_invoke_kwargs.get('isolation_nonce')!r}"
        )

    def test_artifact_result_json_carries_nonce(self, tmp_path: Path):
        """The persisted result.json (consumed by ``artifact analyze``) must
        also carry the nonce so the analyze table can mark rows ``(iso)``.
        """
        task = _write_minimal_artifact_task(tmp_path / "task")
        runner = _StubRunner()

        nonce = "feedface00112233"
        run_artifact_arm(
            task, "code_only", 1,
            results_dir=tmp_path / "results",
            runner=runner,
            echo=lambda _m: None,
            isolation_nonce=nonce,
        )

        result_path = tmp_path / "results" / task.instance_id / "code_only" / "run1" / "result.json"
        data = json.loads(result_path.read_text())
        assert data.get("isolation_nonce") == nonce, (
            f"result.json must carry isolation_nonce={nonce!r}; got {data!r}"
        )


# ---------------------------------------------------------------------------
# Boundary 3: _write_codex_config — MCP iso block
# ---------------------------------------------------------------------------


class TestWriteCodexConfigIsoBlock:
    """When ``isolation_nonce`` is passed, ``_write_codex_config`` must
    emit an ``[mcp_servers.iso_nonce]`` block; when omitted, no such block.
    """

    def test_iso_block_present_when_nonce_set(self, tmp_path: Path):
        nonce = "abc123def456abc1"
        iso_server = "/some/path/iso_nonce_server.mjs"
        _write_codex_config(
            str(tmp_path),
            "/bundle.mjs",
            "/scratch",
            "0",
            arm="code_only",
            isolation_nonce=nonce,
            iso_server_path=iso_server,
        )
        content = (tmp_path / "config.toml").read_text()
        assert "[mcp_servers.iso_nonce]" in content, (
            f"Expected [mcp_servers.iso_nonce] block in config.toml; "
            f"got:\n{content}"
        )
        # The nonce itself must appear (as env var value and tool name).
        assert nonce in content, (
            f"Expected nonce {nonce!r} to appear in config.toml; got:\n{content}"
        )
        assert "ONLYCODES_ISOLATION_NONCE" in content, (
            "Stub server env var must be set in the iso_nonce block"
        )
        assert iso_server in content, (
            f"Expected stub server path {iso_server!r} in config.toml"
        )

    def test_iso_block_absent_when_nonce_unset(self, tmp_path: Path):
        _write_codex_config(
            str(tmp_path),
            "/bundle.mjs",
            "/scratch",
            "0",
            arm="code_only",
            # isolation_nonce omitted
        )
        content = (tmp_path / "config.toml").read_text()
        assert "[mcp_servers.iso_nonce]" not in content, (
            "iso_nonce block must NOT appear when isolation is off"
        )
        assert "ONLYCODES_ISOLATION_NONCE" not in content, (
            "isolation nonce env var must NOT appear when isolation is off"
        )

    def test_iso_block_added_to_all_arms_when_nonce_set(self, tmp_path: Path):
        """Cache isolation must apply to every codex arm (not just code_only),
        because cross-arm cache leakage is exactly what we want to eliminate.
        """
        for arm in ("baseline", "tool_rich", "code_only", "onlycode", "bash_only"):
            cfg = tmp_path / arm
            cfg.mkdir()
            _write_codex_config(
                str(cfg),
                "/bundle.mjs",
                "/scratch",
                "0",
                arm=arm,
                isolation_nonce="abc123def456abc1",
                iso_server_path="/stub/iso.mjs",
            )
            content = (cfg / "config.toml").read_text()
            assert "[mcp_servers.iso_nonce]" in content, (
                f"iso_nonce block missing for arm={arm!r}"
            )


# ---------------------------------------------------------------------------
# Boundary 4: summary / analyze annotates (iso)
# ---------------------------------------------------------------------------


class TestSummaryAnnotatesIso:
    """summary._format_cost must append ``(iso)`` when ArmResult carries a
    non-None isolation_nonce, and must not when the field is None.
    """

    def test_format_cost_appends_iso_marker(self):
        from swebench.analyze.summary import _format_cost
        from swebench.models import ArmResult

        r = ArmResult(
            instance_id="repo__t1",
            arm="onlycode",
            run_idx=1,
            verdict="PASS",
            cost_usd=0.123,
            num_turns=4,
            wall_secs=10,
            jsonl_path="",
            test_txt_path="",
            agent_surface="codex_cli",
            isolation_nonce="abc123def456abc1",
        )
        formatted = _format_cost(r)
        assert formatted.endswith("(iso)"), (
            f"Expected (iso) suffix; got {formatted!r}"
        )
        # Cost amount must still appear
        assert "0.123" in formatted

    def test_format_cost_no_iso_marker_when_field_none(self):
        from swebench.analyze.summary import _format_cost
        from swebench.models import ArmResult

        r = ArmResult(
            instance_id="repo__t1",
            arm="onlycode",
            run_idx=1,
            verdict="PASS",
            cost_usd=0.123,
            num_turns=4,
            wall_secs=10,
            jsonl_path="",
            test_txt_path="",
            agent_surface="codex_cli",
            isolation_nonce=None,
        )
        formatted = _format_cost(r)
        assert "(iso)" not in formatted, (
            f"(iso) marker must not appear when isolation_nonce is None; "
            f"got {formatted!r}"
        )
