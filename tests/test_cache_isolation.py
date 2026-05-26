"""Tests for the ``--cache-isolation`` flag (#294, #296).

Four boundaries are covered here:

1. Nonce generation — ``generate_isolation_nonce`` returns 16-hex and mints
   a fresh value per call (datetime-salted with (instance, arm, run) salt)
   so reruns, different sweeps, tasks, arms, and run indices all get
   distinct nonces and cannot share prompt-cache keys (#294, #296).
2. JSONL meta-line stamping — when the harness is invoked with
   ``--cache-isolation``, the meta line contains an ``isolation_nonce`` field;
   when the flag is off, the field is absent.
3. ``_write_codex_config`` MCP block — when ``isolation_nonce`` is passed,
   the resulting ``config.toml`` contains an ``[mcp_servers.iso_nonce]``
   block referencing the on-disk stub server.
4. ``ClaudeRunner`` iso plumbing — merged mcp-config preserves base entries,
   ``--disallowedTools`` is extended, the env var is set, and arms with no
   base ``--mcp-config`` get one added (#296).

The tests do not invoke real codex / claude binaries.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from swebench.artifact_models import ExecutionBudget, Task
from swebench.artifact_run import run_artifact_arm
from swebench.runner import (
    AgentRunner,
    ClaudeRunner,
    _splice_iso_into_claude_flags,
    _write_claude_iso_mcp_config,
    _write_codex_config,
    generate_isolation_nonce,
)


# ---------------------------------------------------------------------------
# Boundary 1: nonce generation
# ---------------------------------------------------------------------------


class TestGenerateIsolationNonce:
    """The nonce must be 16-hex and **fresh per call**. The original #294
    formula was deterministic sha256(instance|arm|run); #296 replaced it with
    a datetime-salted hash so reruns and re-sweeps within the provider TTL
    window cannot inherit cache state from a prior invocation. The identifier
    salt is retained so concurrent calls for *different* triples remain
    collision-safe even on the same wall-clock instant.
    """

    def test_nonce_is_16_hex_chars(self):
        n = generate_isolation_nonce("anything", "tool_rich", 0)
        assert isinstance(n, str)
        assert len(n) == 16, f"Expected 16-char nonce, got {len(n)}: {n!r}"
        int(n, 16)  # raises ValueError if not hex

    def test_same_inputs_yield_different_nonces(self):
        """The #296 contract: re-invoking the same triple back-to-back must
        produce different nonces so a rerun cannot inherit the prior run's
        warm cache entry.
        """
        a = generate_isolation_nonce("repo__task-1", "code_only", 1)
        b = generate_isolation_nonce("repo__task-1", "code_only", 1)
        assert a != b, (
            "Reruns of the same triple must mint distinct nonces; both were "
            f"{a}. If the formula reverted to deterministic, cross-rerun "
            "and cross-sweep cache leakage is back."
        )

    def test_many_calls_unique(self):
        """Belt-and-braces against a degenerate clock or hash: 100 calls of
        the same triple — all 100 nonces must be distinct.
        """
        nonces = {
            generate_isolation_nonce("repo__task-1", "code_only", 1)
            for _ in range(100)
        }
        assert len(nonces) == 100, (
            f"Expected 100 distinct nonces; got {len(nonces)}. "
            "Indicates a broken timestamp source or hash truncation."
        )

    def test_different_triples_yield_different_nonces(self):
        """Even when called within the same microsecond, different triples
        must produce different nonces (the identifier salt guarantees this).
        Hardest case: same wall-clock instant — simulate by patching the
        timestamp generator.
        """
        from swebench import runner as runner_mod

        class _FrozenClock:
            @staticmethod
            def now(_tz):
                from datetime import datetime, timezone
                return datetime(2026, 5, 26, 12, 0, 0, 0, tzinfo=timezone.utc)

        with patch.object(runner_mod, "datetime", _FrozenClock):
            a = generate_isolation_nonce("repo__task-1", "code_only", 1)
            b = generate_isolation_nonce("repo__task-2", "code_only", 1)
            c = generate_isolation_nonce("repo__task-1", "tool_rich", 1)
            d = generate_isolation_nonce("repo__task-1", "code_only", 2)
        assert len({a, b, c, d}) == 4, (
            "Under a frozen clock, each (instance, arm, run) triple must "
            f"still produce a unique nonce; got {{a:{a}, b:{b}, c:{c}, d:{d}}}"
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


# ---------------------------------------------------------------------------
# Boundary 5: ClaudeRunner iso plumbing (#296)
# ---------------------------------------------------------------------------


class TestClaudeIsoMcpConfig:
    """``_write_claude_iso_mcp_config`` must always emit the iso_nonce stub
    server entry and preserve any pre-existing servers when a base config is
    supplied.
    """

    def test_writes_iso_server_with_only_iso_when_no_base(self, tmp_path: Path):
        path = _write_claude_iso_mcp_config(
            base_config_path=None,
            iso_server_path="/some/path/iso_nonce_server.mjs",
            nonce="abc123def456abc1",
            out_dir=str(tmp_path),
        )
        cfg = json.loads(Path(path).read_text())
        assert set(cfg["mcpServers"].keys()) == {"iso_nonce"}, (
            f"Expected only iso_nonce server when no base; got {cfg!r}"
        )
        iso = cfg["mcpServers"]["iso_nonce"]
        assert iso["command"] == "node"
        assert iso["args"] == ["/some/path/iso_nonce_server.mjs"]
        assert iso["env"]["ONLYCODES_ISOLATION_NONCE"] == "abc123def456abc1"

    def test_preserves_base_servers_when_merging(self, tmp_path: Path):
        base = tmp_path / "mcp-config.json"
        base.write_text(json.dumps({
            "mcpServers": {
                "codebox": {"command": "node", "args": ["/path/exec.mjs"]}
            }
        }))
        path = _write_claude_iso_mcp_config(
            base_config_path=str(base),
            iso_server_path="/stub/iso.mjs",
            nonce="feedface00112233",
            out_dir=str(tmp_path),
        )
        cfg = json.loads(Path(path).read_text())
        assert set(cfg["mcpServers"].keys()) == {"codebox", "iso_nonce"}, (
            f"Merged config must keep base servers; got {cfg!r}"
        )
        assert cfg["mcpServers"]["codebox"]["args"] == ["/path/exec.mjs"]


class TestSpliceIsoIntoClaudeFlags:
    """``_splice_iso_into_claude_flags`` must add an iso ``--mcp-config`` for
    arms that lack one, extend an existing one for code_only/onlycode, and
    extend or append ``--disallowedTools`` accordingly.
    """

    def test_tool_rich_arm_gets_mcp_config_added(self):
        flags: list[str] = []
        out = _splice_iso_into_claude_flags(
            flags, "/tmp/merged.json", "mcp__iso_nonce__iso_nonce_abc"
        )
        assert "--mcp-config" in out
        assert out[out.index("--mcp-config") + 1] == "/tmp/merged.json"
        assert "--strict-mcp-config" in out
        assert out[out.index("--disallowedTools") + 1] == (
            "mcp__iso_nonce__iso_nonce_abc"
        )

    def test_code_only_arm_replaces_existing_mcp_config_value(self):
        flags = [
            "--mcp-config", "/orig/mcp.json", "--strict-mcp-config",
            "--tools", "mcp__codebox__execute_code",
            "--disallowedTools", "Bash,Edit,Read",
        ]
        out = _splice_iso_into_claude_flags(
            flags, "/tmp/merged.json", "mcp__iso_nonce__iso_nonce_xyz"
        )
        assert out[out.index("--mcp-config") + 1] == "/tmp/merged.json"
        # disallowedTools value extended, not replaced
        idx = out.index("--disallowedTools")
        assert out[idx + 1] == "Bash,Edit,Read,mcp__iso_nonce__iso_nonce_xyz"
        # --strict-mcp-config must still be present (not duplicated)
        assert out.count("--strict-mcp-config") == 1

    def test_bash_only_arm_extends_disallowed_and_adds_mcp_config(self):
        flags = ["--tools", "Bash", "--disallowedTools", "Edit,Read,Write"]
        out = _splice_iso_into_claude_flags(
            flags, "/tmp/merged.json", "mcp__iso_nonce__iso_nonce_qq"
        )
        assert "--mcp-config" in out
        assert out[out.index("--mcp-config") + 1] == "/tmp/merged.json"
        assert out[out.index("--disallowedTools") + 1] == (
            "Edit,Read,Write,mcp__iso_nonce__iso_nonce_qq"
        )

    def test_input_not_mutated(self):
        flags = ["--tools", "Bash"]
        original = list(flags)
        _splice_iso_into_claude_flags(flags, "/tmp/x.json", "tool_x")
        assert flags == original, "Helper must not mutate caller's flags list"


class TestClaudeInvokeIsoIntegration:
    """End-to-end: ``ClaudeRunner.invoke(isolation_nonce=...)`` must place the
    iso flags into the subprocess argv and the nonce into the subprocess env.
    Patches ``subprocess.Popen`` to capture without launching ``claude``.
    """

    def _capture_invoke(self, *, isolation_nonce: str | None, arm: str,
                        mcp_config_path: str | None, tmp_path: Path) -> dict:
        captured: dict = {}

        class _FakePopen:
            def __init__(self, cmd, **kw):
                captured["cmd"] = list(cmd)
                captured["env"] = kw.get("env", {}).copy()
                # Snapshot --mcp-config contents before the invoke cleanup
                # removes the temp cfg_dir holding the merged config.
                if "--mcp-config" in cmd:
                    idx = cmd.index("--mcp-config")
                    cfg_path = cmd[idx + 1]
                    if Path(cfg_path).is_file():
                        captured["mcp_config_contents"] = Path(cfg_path).read_text()
                self.returncode = 0

            def wait(self, timeout=None):
                return 0

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        runner = ClaudeRunner()
        flags = runner.build_tools_flags(arm, mcp_config_path)
        result_file = tmp_path / "out.jsonl"

        with patch("swebench.runner.subprocess.Popen", _FakePopen):
            runner.invoke(
                prompt="hello",
                cwd=str(tmp_path),
                system_prompt="You are a helpful assistant.",
                tools_flags=flags,
                result_file=str(result_file),
                binary="/usr/bin/true",
                mcp_config_path=mcp_config_path,
                wall_timeout_seconds=10,
                isolation_nonce=isolation_nonce,
            )
        return captured

    def test_iso_off_leaves_argv_untouched(self, tmp_path: Path):
        cap = self._capture_invoke(
            isolation_nonce=None, arm="baseline",
            mcp_config_path=None, tmp_path=tmp_path,
        )
        assert "--mcp-config" not in cap["cmd"]
        assert "ONLYCODES_ISOLATION_NONCE" not in cap["env"]

    def test_iso_on_baseline_arm_adds_mcp_config_and_disallow(self, tmp_path: Path):
        cap = self._capture_invoke(
            isolation_nonce="abc123def456abc1",
            arm="baseline", mcp_config_path=None, tmp_path=tmp_path,
        )
        assert "--mcp-config" in cap["cmd"], (
            "tool_rich/baseline arms must get an --mcp-config added when iso is on"
        )
        assert "--strict-mcp-config" in cap["cmd"]
        idx = cap["cmd"].index("--disallowedTools")
        assert "mcp__iso_nonce__iso_nonce_abc123def456abc1" in cap["cmd"][idx + 1]
        assert cap["env"].get("ONLYCODES_ISOLATION_NONCE") == "abc123def456abc1"

    def test_iso_on_code_only_arm_preserves_codebox_config(self, tmp_path: Path):
        base = tmp_path / "mcp-config.json"
        base.write_text(json.dumps({
            "mcpServers": {
                "codebox": {"command": "node", "args": ["/exec.mjs"]}
            }
        }))
        cap = self._capture_invoke(
            isolation_nonce="feedface00112233",
            arm="code_only", mcp_config_path=str(base), tmp_path=tmp_path,
        )
        merged = json.loads(cap["mcp_config_contents"])
        assert set(merged["mcpServers"].keys()) == {"codebox", "iso_nonce"}, (
            "code_only iso config must keep the codebox server alongside the stub"
        )
        # disallowedTools should retain BLOCKED_BUILTINS *and* add the iso tool.
        d_idx = cap["cmd"].index("--disallowedTools")
        disallowed = cap["cmd"][d_idx + 1]
        assert "Bash" in disallowed and "Edit" in disallowed, (
            "BLOCKED_BUILTINS must remain in --disallowedTools when iso extends it"
        )
        assert "mcp__iso_nonce__iso_nonce_feedface00112233" in disallowed
