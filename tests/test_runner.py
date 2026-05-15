"""Unit tests for swebench.runner — AgentRunner, ClaudeRunner, CodexRunner."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from swebench.runner import (
    BLOCKED_BUILTINS,
    ClaudeRunner,
    CodexRunner,
    _write_codex_config,
    make_runner,
)


# ---------------------------------------------------------------------------
# make_runner factory
# ---------------------------------------------------------------------------

def test_make_runner_claude():
    r = make_runner("claude_code")
    assert isinstance(r, ClaudeRunner)
    assert r.surface == "claude_code"


def test_make_runner_codex():
    r = make_runner("codex_cli")
    assert isinstance(r, CodexRunner)
    assert r.surface == "codex_cli"


def test_make_runner_unknown():
    with pytest.raises(ValueError, match="Unknown agent surface"):
        make_runner("llama_cli")


# ---------------------------------------------------------------------------
# ClaudeRunner — config isolation (tested indirectly via invoke internals)
# ---------------------------------------------------------------------------

def test_claude_runner_invoke_creates_and_cleans_temp_config(tmp_path, monkeypatch):
    """Config dir must be created and cleaned up even when the binary fails."""
    import subprocess
    created_dirs: list[str] = []
    real_mkdtemp = __import__("tempfile").mkdtemp

    def tracking_mkdtemp(**kwargs):
        d = real_mkdtemp(**kwargs)
        if "claude-eval-" in d:
            created_dirs.append(d)
        return d

    monkeypatch.setattr("swebench.runner.tempfile.mkdtemp", tracking_mkdtemp)

    result_file = str(tmp_path / "out.jsonl")
    ClaudeRunner().invoke(
        prompt="hello",
        cwd=str(tmp_path),
        system_prompt="",
        tools_flags=[],
        result_file=result_file,
        binary="/bin/true",  # exists, exits 0, writes nothing
    )
    # The temp dir must have been cleaned up.
    for d in created_dirs:
        assert not Path(d).exists(), f"Temp dir not cleaned up: {d}"


# ---------------------------------------------------------------------------
# harness.generate_mcp_config (Claude MCP JSON config generation)
# ---------------------------------------------------------------------------

def test_harness_generate_mcp_config_sets_cwd(tmp_path):
    from swebench.harness import generate_mcp_config
    base = tmp_path / "mcp-config.json"
    base.write_text(json.dumps({
        "mcpServers": {
            "codebox": {
                "command": "node",
                "args": ["/path/to/bundle.mjs"],
                "cwd": "/old/path",
            }
        }
    }))
    out = generate_mcp_config(str(base), "/new/scratch")
    try:
        cfg = json.loads(Path(out).read_text())
        assert cfg["mcpServers"]["codebox"]["cwd"] == "/new/scratch"
    finally:
        if out != str(base):
            os.unlink(out)


def test_harness_generate_mcp_config_missing_file_returns_input():
    from swebench.harness import generate_mcp_config
    out = generate_mcp_config("/nonexistent/path.json", "/scratch")
    assert out == "/nonexistent/path.json"


# ---------------------------------------------------------------------------
# ClaudeRunner — build_tools_flags
# ---------------------------------------------------------------------------

def test_claude_tools_flags_baseline():
    assert ClaudeRunner().build_tools_flags("baseline", None) == []


def test_claude_tools_flags_tool_rich():
    assert ClaudeRunner().build_tools_flags("tool_rich", None) == []


def test_claude_tools_flags_onlycode_with_mcp():
    flags = ClaudeRunner().build_tools_flags("onlycode", "/tmp/mcp.json")
    assert "--mcp-config" in flags
    assert "--strict-mcp-config" in flags
    assert "--tools" in flags
    assert "--disallowedTools" in flags
    idx = flags.index("--disallowedTools")
    assert "Bash" in flags[idx + 1]


def test_claude_tools_flags_code_only_without_mcp():
    flags = ClaudeRunner().build_tools_flags("code_only", None)
    assert "--mcp-config" not in flags
    assert "--disallowedTools" in flags


def test_claude_tools_flags_bash_only():
    flags = ClaudeRunner().build_tools_flags("bash_only", None)
    assert flags[flags.index("--tools") + 1] == "Bash"
    disallowed = flags[flags.index("--disallowedTools") + 1]
    assert "Bash" not in disallowed
    assert "Read" in disallowed


def test_claude_tools_flags_unknown_arm():
    with pytest.raises(ValueError):
        ClaudeRunner().build_tools_flags("unknown", None)


# ---------------------------------------------------------------------------
# ClaudeRunner — extract_metadata
# ---------------------------------------------------------------------------

def test_claude_extract_metadata_parses_cost_and_turns(tmp_path):
    f = tmp_path / "agent.jsonl"
    f.write_text(
        json.dumps({"type": "meta"}) + "\n"
        + json.dumps({"type": "result", "total_cost_usd": 0.0456, "num_turns": 7}) + "\n"
    )
    cost, turns = ClaudeRunner().extract_metadata(f)
    assert cost == pytest.approx(0.0456)
    assert turns == 7


def test_claude_extract_metadata_missing_file():
    cost, turns = ClaudeRunner().extract_metadata(Path("/nonexistent/agent.jsonl"))
    assert cost is None
    assert turns is None


def test_claude_extract_metadata_no_cost_no_turns(tmp_path):
    f = tmp_path / "agent.jsonl"
    f.write_text(json.dumps({"type": "meta"}) + "\n")
    cost, turns = ClaudeRunner().extract_metadata(f)
    assert cost is None
    assert turns is None


# ---------------------------------------------------------------------------
# CodexRunner — config generation (TOML writing)
# ---------------------------------------------------------------------------

def test_write_codex_config_creates_valid_toml(tmp_path):
    _write_codex_config(str(tmp_path), "/path/bundle.mjs", "/scratch", "0")
    toml_path = tmp_path / "config.toml"
    assert toml_path.is_file()
    content = toml_path.read_text()
    assert "shell_tool = false" in content
    assert "apply_patch_freeform = false" in content
    assert 'web_search_mode = "disabled"' in content
    assert "/path/bundle.mjs" in content
    assert "/scratch" in content
    assert 'ONLYCODES_PERSISTENT_KERNEL = "0"' in content


def test_write_codex_config_persistent_kernel_flag(tmp_path):
    _write_codex_config(str(tmp_path), "/bundle.mjs", "/scratch", "1")
    content = (tmp_path / "config.toml").read_text()
    assert 'ONLYCODES_PERSISTENT_KERNEL = "1"' in content


# ---------------------------------------------------------------------------
# CodexRunner — build_tools_flags always empty
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("arm", ["tool_rich", "baseline", "code_only", "onlycode", "bash_only"])
def test_codex_tools_flags_always_empty(arm):
    assert CodexRunner().build_tools_flags(arm, "/tmp/mcp.json") == []


def test_codex_tools_flags_unknown_arm():
    with pytest.raises(ValueError):
        CodexRunner().build_tools_flags("nonsense", None)


# ---------------------------------------------------------------------------
# CodexRunner — extract_metadata counts turn.started events
# ---------------------------------------------------------------------------

def test_codex_extract_metadata_counts_turns(tmp_path):
    f = tmp_path / "agent.jsonl"
    lines = [
        json.dumps({"type": "thread.started"}),
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "hi"}}),
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 5}}),
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "done"}}),
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 50, "output_tokens": 3}}),
        "WARNING: some non-json line",
    ]
    f.write_text("\n".join(lines) + "\n")
    cost, turns = CodexRunner().extract_metadata(f)
    assert cost is None        # Codex never exposes cost
    assert turns == 2


def test_codex_extract_metadata_no_turns(tmp_path):
    f = tmp_path / "agent.jsonl"
    f.write_text(json.dumps({"type": "thread.started"}) + "\n")
    cost, turns = CodexRunner().extract_metadata(f)
    assert cost is None
    assert turns is None


def test_codex_extract_metadata_missing_file():
    cost, turns = CodexRunner().extract_metadata(Path("/nonexistent/agent.jsonl"))
    assert cost is None
    assert turns is None


# ---------------------------------------------------------------------------
# CodexRunner — _resolve_bundle
# ---------------------------------------------------------------------------

def test_codex_resolve_bundle_from_json_config(tmp_path):
    bundle = tmp_path / "bundle.mjs"
    bundle.write_text("// fake bundle")
    mcp_json = tmp_path / "mcp-config.json"
    mcp_json.write_text(json.dumps({
        "mcpServers": {"codebox": {"args": [str(bundle)]}}
    }))
    resolved = CodexRunner()._resolve_bundle(str(mcp_json))
    assert resolved == str(bundle)


def test_codex_resolve_bundle_raises_when_not_found(tmp_path, monkeypatch):
    # The default bundle exists in the repo, so patch Path.is_file to make the
    # fallback candidate also appear missing.
    monkeypatch.setattr("pathlib.Path.is_file", lambda self: False)
    mcp = tmp_path / "mcp.json"
    mcp.write_text(json.dumps({"mcpServers": {"codebox": {"args": ["/no/such/bundle.mjs"]}}}))
    with pytest.raises(FileNotFoundError, match="exec-server bundle not found"):
        CodexRunner()._resolve_bundle(str(mcp))


# ---------------------------------------------------------------------------
# CodexRunner — find_binary raises when codex not on PATH
# ---------------------------------------------------------------------------

def test_codex_find_binary_missing(monkeypatch):
    """CodexRunner.find_binary() must raise FileNotFoundError with install hint."""
    monkeypatch.setattr("swebench.runner.shutil.which", lambda _name: None)
    with pytest.raises(FileNotFoundError, match="npm install -g @openai/codex"):
        CodexRunner().find_binary()


# ---------------------------------------------------------------------------
# CodexRunner — make_isolated_config raises when auth.json is absent
# ---------------------------------------------------------------------------

def test_codex_make_isolated_config_missing_auth(monkeypatch):
    """make_isolated_config() must raise FileNotFoundError when ~/.codex/auth.json is absent."""
    monkeypatch.setattr("swebench.runner.os.path.isfile", lambda _p: False)
    with pytest.raises(FileNotFoundError, match=r"~/\.codex/auth\.json"):
        CodexRunner().make_isolated_config()


def test_codex_make_isolated_config_success(tmp_path, monkeypatch):
    """make_isolated_config() returns a dir containing auth.json when the source exists."""
    import shutil as _shutil

    fake_home = tmp_path / "home"
    codex_dir = fake_home / ".codex"
    codex_dir.mkdir(parents=True)
    auth_src = codex_dir / "auth.json"
    auth_src.write_text('{"token": "test-token"}')

    # Patch os.path.expanduser so "~/.codex/auth.json" resolves to our fake home.
    real_expanduser = os.path.expanduser

    def fake_expanduser(path: str) -> str:
        if path.startswith("~/"):
            return str(fake_home / path[2:])
        return real_expanduser(path)

    monkeypatch.setattr("swebench.runner.os.path.expanduser", fake_expanduser)

    # _resolve_bundle will look for a bundle; redirect Path.is_file so the
    # fallback candidate appears missing, then supply a fake bundle via mcp_config.
    bundle = tmp_path / "bundle.mjs"
    bundle.write_text("// fake")
    mcp_json = tmp_path / "mcp.json"
    mcp_json.write_text(json.dumps({
        "mcpServers": {"codebox": {"args": [str(bundle)]}}
    }))

    cfg_dir = CodexRunner().make_isolated_config(
        mcp_config_path=str(mcp_json),
        cwd=str(tmp_path),
    )
    try:
        assert Path(cfg_dir).is_dir()
        assert (Path(cfg_dir) / "auth.json").is_file()
    finally:
        _shutil.rmtree(cfg_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# run_command — rejects codex_cli + onlycode
# ---------------------------------------------------------------------------

def test_run_command_rejects_codex_onlycode(tmp_path, monkeypatch):
    """swebench run --agent-surface codex_cli --arms onlycode must exit 1."""
    from click.testing import CliRunner
    from swebench.cli import cli

    # Prevent real binary discovery / auth check from running before the guard.
    # The rejection guard in run_command fires after find_binary() + make_isolated_config(),
    # so we stub both to no-ops. If the guard fires first this monkeypatch is unused —
    # either way the test is correct.
    monkeypatch.setattr(
        "swebench.runner.CodexRunner.find_binary",
        lambda self: "/usr/bin/codex",
    )
    monkeypatch.setattr(
        "swebench.runner.CodexRunner.make_isolated_config",
        lambda self, **kw: tmp_path / "cfg",
    )
    # Prevent the problems-dir check from failing on a clean env.
    problems_dir = tmp_path / "problems" / "swe"
    problems_dir.mkdir(parents=True)
    (problems_dir / "dummy.yaml").write_text(
        "instance_id: dummy\nrepo: r\nbase_commit: abc\n"
        "problem_statement: p\ntest_cmd: pytest\n"
    )
    monkeypatch.setattr("swebench.run.repo_root", lambda: tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["run", "--agent-surface", "codex_cli", "--arms", "onlycode",
         "--output-dir", str(tmp_path / "out")],
        catch_exceptions=False,
    )
    assert result.exit_code == 1, f"Expected exit 1, got {result.exit_code}. output={result.output}"
    assert "not yet implemented" in (result.output or ""), (
        f"Expected 'not yet implemented' in output. Got: {result.output!r}"
    )


# ---------------------------------------------------------------------------
# artifact run_command — rejects codex_cli + code_only
# ---------------------------------------------------------------------------

def test_artifact_run_command_rejects_codex_code_only(tmp_path, monkeypatch):
    """artifact run --agent-surface codex_cli --arms code_only must exit 1."""
    from click.testing import CliRunner
    from swebench.cli import cli

    # Stub binary discovery so preflight doesn't fail on missing codex binary.
    monkeypatch.setattr(
        "swebench.runner.CodexRunner.find_binary",
        lambda self: "/usr/bin/codex",
    )
    # Provide a minimal task so load_tasks doesn't fail.
    tasks_dir = tmp_path / "problems" / "artifact" / "enumeration" / "dummy_task"
    tasks_dir.mkdir(parents=True)
    (tasks_dir / "task.yaml").write_text(
        "instance_id: enumeration__dummy_task\n"
        "category: enumeration\n"
        "difficulty: easy\n"
        "problem_statement: |\n  Write code.\n"
        "workspace_dir: workspace\n"
        "output_artifact: answer.txt\n"
        "hidden_grader: grader/hidden.py\n"
        "reference_output: grader/reference_output.txt\n"
        "execution_budget:\n"
        "  max_code_runs: 0\n"
        "  max_wall_seconds: 0\n"
    )
    (tasks_dir / "workspace").mkdir()
    grader_dir = tasks_dir / "grader"
    grader_dir.mkdir()
    (grader_dir / "hidden.py").write_text("def grade(d): pass\n")
    (grader_dir / "reference_output.txt").write_text("42\n")
    monkeypatch.setattr("swebench.artifact_cli.repo_root", lambda: tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "artifact", "run",
            "--agent-surface", "codex_cli",
            "--arms", "code_only",
            "--tasks-dir", str(tmp_path / "problems" / "artifact"),
            "--output-dir", str(tmp_path / "out"),
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 1, (
        f"Expected exit 1, got {result.exit_code}. output={result.output}"
    )
    assert "not yet implemented" in (result.output or ""), (
        f"Expected 'not yet implemented' in output. Got: {result.output!r}"
    )


# ---------------------------------------------------------------------------
# analyze pathology — rejects Codex JSONL
# ---------------------------------------------------------------------------

def test_codex_jsonl_analyze_guard(tmp_path):
    """pathology command must reject a results dir containing Codex JSONL."""
    from click.testing import CliRunner
    from swebench.cli import cli

    # Write a minimal JSONL whose meta line identifies the surface as codex_cli.
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    jsonl = results_dir / "dummy__baseline_run1.jsonl"
    jsonl.write_text(
        json.dumps({"type": "meta", "agent_surface": "codex_cli", "instance_id": "dummy"}) + "\n"
        + json.dumps({"type": "turn.started"}) + "\n"
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "analyze", "pathology",
            "--results-dir", str(results_dir),
            "--dry-run",
            "--stage", "mechanical",
        ],
        catch_exceptions=True,
    )
    # The guard should either raise NotImplementedError (caught as exit 1)
    # or exit non-zero with the expected message.
    output = result.output or ""
    if result.exception is not None:
        assert isinstance(result.exception, (NotImplementedError, SystemExit)), (
            f"Unexpected exception type: {type(result.exception)}: {result.exception}"
        )
        if isinstance(result.exception, NotImplementedError):
            assert "Codex JSONL not yet supported" in str(result.exception), (
                f"Wrong NotImplementedError message: {result.exception}"
            )
        else:
            # SystemExit — message may be in output or exit code signals failure
            assert "Codex JSONL not yet supported" in output or result.exit_code != 0, (
                f"Expected 'Codex JSONL not yet supported' or non-zero exit. "
                f"Got: exit={result.exit_code}, output={output!r}"
            )
    else:
        # No exception — must have exited non-zero with the right message
        assert result.exit_code != 0 and "Codex JSONL not yet supported" in output, (
            f"Expected non-zero exit + 'Codex JSONL not yet supported'. "
            f"Got: exit={result.exit_code}, output={output!r}"
        )
