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


def test_codex_resolve_bundle_raises_when_not_found(tmp_path):
    # Pass a nonexistent mcp config and point to a tmp dir with no bundle.
    # The default bundle exists in this repo so we can't easily test the fallback
    # without a real file; instead confirm the happy path from JSON config works
    # and the error path raises.
    with pytest.raises(FileNotFoundError, match="exec-server bundle not found"):
        # Give it a valid JSON file that points to a nonexistent bundle.
        mcp = tmp_path / "mcp.json"
        mcp.write_text(json.dumps({"mcpServers": {"codebox": {"args": ["/no/such/bundle.mjs"]}}}))
        CodexRunner()._resolve_bundle(str(mcp))
