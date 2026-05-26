"""Unit tests for swebench.runner — AgentRunner, ClaudeRunner, CodexRunner."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import tomllib

from swebench.runner import (
    BLOCKED_BUILTINS,
    ClaudeRunner,
    CodexRunner,
    _toml_str,
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
    """Default (baseline) arm: native shell enabled, no codebox MCP block."""
    _write_codex_config(str(tmp_path), "/path/bundle.mjs", "/scratch", "0")
    toml_path = tmp_path / "config.toml"
    assert toml_path.is_file()
    content = toml_path.read_text()
    # tool_rich/baseline grants native shell + freeform apply_patch.
    assert "shell_tool = true" in content
    assert "apply_patch_freeform = true" in content
    assert 'web_search = "disabled"' in content
    # No codebox MCP server block in baseline.
    assert "[mcp_servers.codebox]" not in content
    assert "/path/bundle.mjs" not in content
    assert "ONLYCODES_PERSISTENT_KERNEL" not in content


def test_write_codex_config_persistent_kernel_flag(tmp_path):
    """ONLYCODES_PERSISTENT_KERNEL is only emitted for arms that register codebox."""
    _write_codex_config(str(tmp_path), "/bundle.mjs", "/scratch", "1", arm="code_only")
    content = (tmp_path / "config.toml").read_text()
    assert 'ONLYCODES_PERSISTENT_KERNEL = "1"' in content


# ---------------------------------------------------------------------------
# CodexRunner — model pinning (Issue #253)
# ---------------------------------------------------------------------------

def test_write_codex_config_writes_default_model_line(tmp_path):
    """Acceptance: ``_write_codex_config`` always writes a ``model = "..."`` line."""
    _write_codex_config(str(tmp_path), "/bundle.mjs", "/scratch", "0")
    content = (tmp_path / "config.toml").read_text()
    assert 'model = "gpt-5.5"' in content


def test_write_codex_config_writes_custom_model_line(tmp_path):
    """Acceptance: ``--codex-model <name>`` overrides the default."""
    _write_codex_config(
        str(tmp_path), "/bundle.mjs", "/scratch", "0", model="gpt-5.4-mini"
    )
    content = (tmp_path / "config.toml").read_text()
    assert 'model = "gpt-5.4-mini"' in content
    # Must be at top level, not inside any [section]
    first_section = content.split("[", 1)[0]
    assert 'model = "gpt-5.4-mini"' in first_section


def test_codex_runner_constructor_passes_model(tmp_path):
    """The model arg threads through to ``_write_codex_config``."""
    runner = CodexRunner(model="gpt-5.4")
    assert runner.model == "gpt-5.4"


def test_codex_runner_default_model_is_gpt_5_5():
    """Default constructor arg is gpt-5.5."""
    assert CodexRunner().model == "gpt-5.5"


def test_make_runner_codex_threads_codex_model():
    """make_runner forwards codex_model to CodexRunner."""
    r = make_runner("codex_cli", codex_model="gpt-5.4")
    assert isinstance(r, CodexRunner)
    assert r.model == "gpt-5.4"


def test_make_runner_codex_default_model():
    """make_runner uses gpt-5.5 as the default codex_model."""
    r = make_runner("codex_cli")
    assert isinstance(r, CodexRunner)
    assert r.model == "gpt-5.5"


# ---------------------------------------------------------------------------
# CodexRunner — cost estimation from token usage (Issue #253)
# ---------------------------------------------------------------------------

def _make_codex_jsonl(
    tmp_path: Path,
    *,
    model: str | None,
    usages: list[dict] | None,
) -> Path:
    """Build a minimal Codex JSONL with optional meta+model and usage entries."""
    f = tmp_path / "agent.jsonl"
    lines: list[str] = []
    if model is not None:
        lines.append(json.dumps({"type": "meta", "model": model}))
    else:
        lines.append(json.dumps({"type": "meta"}))  # meta but no model field
    if usages is None:
        # Default: just one turn with no usage block
        lines += [
            json.dumps({"type": "turn.started"}),
            json.dumps({"type": "turn.completed"}),
        ]
    else:
        for usage in usages:
            lines += [
                json.dumps({"type": "turn.started"}),
                json.dumps({"type": "turn.completed", "usage": usage}),
            ]
    f.write_text("\n".join(lines) + "\n")
    return f


def test_codex_extract_metadata_known_model_estimates_cost(tmp_path):
    """Acceptance: known model + turn.completed usage → estimated cost."""
    f = _make_codex_jsonl(
        tmp_path,
        model="gpt-5.5",
        usages=[{
            "input_tokens": 421838,
            "cached_input_tokens": 353280,
            "output_tokens": 4673,
            "reasoning_output_tokens": 1881,  # already inside output_tokens
        }],
    )
    cost, turns = CodexRunner().extract_metadata(f)
    assert turns == 1
    # gpt-5.5: input=$5/M, cached=$0.50/M, output=$30/M
    # non_cached = 421838 - 353280 = 68558
    # cost = (68558 * 5 + 353280 * 0.50 + 4673 * 30) / 1_000_000
    #      = (342790 + 176640 + 140190) / 1_000_000 = 659620 / 1_000_000 = 0.65962
    expected = (68558 * 5.0 + 353280 * 0.50 + 4673 * 30.0) / 1_000_000.0
    assert cost == pytest.approx(expected, rel=1e-9)


def test_codex_extract_metadata_sums_multiple_turns(tmp_path):
    """Multiple turn.completed events are summed."""
    f = _make_codex_jsonl(
        tmp_path,
        model="gpt-5.4-mini",
        usages=[
            {"input_tokens": 1000, "cached_input_tokens": 0, "output_tokens": 100},
            {"input_tokens": 2000, "cached_input_tokens": 500, "output_tokens": 200},
        ],
    )
    cost, turns = CodexRunner().extract_metadata(f)
    assert turns == 2
    # Totals: input=3000, cached=500, output=300
    # gpt-5.4-mini: input=$0.75, cached=$0.075, output=$4.50
    # non_cached = 3000 - 500 = 2500
    # cost = (2500 * 0.75 + 500 * 0.075 + 300 * 4.50) / 1_000_000
    expected = (2500 * 0.75 + 500 * 0.075 + 300 * 4.50) / 1_000_000.0
    assert cost == pytest.approx(expected, rel=1e-9)


def test_codex_extract_metadata_unknown_model_returns_none(tmp_path):
    """Acceptance: unknown model → cost=None (turns still extracted)."""
    f = _make_codex_jsonl(
        tmp_path,
        model="claude-sonnet-99",  # not in price table
        usages=[{"input_tokens": 100, "cached_input_tokens": 0, "output_tokens": 10}],
    )
    cost, turns = CodexRunner().extract_metadata(f)
    assert cost is None
    assert turns == 1


def test_codex_extract_metadata_missing_meta_returns_none(tmp_path):
    """No meta line at all → cost=None."""
    f = tmp_path / "agent.jsonl"
    f.write_text(
        json.dumps({"type": "turn.started"}) + "\n"
        + json.dumps({"type": "turn.completed", "usage": {
            "input_tokens": 100, "output_tokens": 5
        }}) + "\n"
    )
    cost, turns = CodexRunner().extract_metadata(f)
    assert cost is None
    assert turns == 1


def test_codex_extract_metadata_meta_without_model_returns_none(tmp_path):
    """Meta line present but no model field → cost=None."""
    f = _make_codex_jsonl(
        tmp_path,
        model=None,  # meta with no model field
        usages=[{"input_tokens": 100, "cached_input_tokens": 0, "output_tokens": 5}],
    )
    cost, turns = CodexRunner().extract_metadata(f)
    assert cost is None
    assert turns == 1


def test_codex_extract_metadata_no_usage_returns_none(tmp_path):
    """Known model but no turn.completed has a ``usage`` block → cost=None."""
    f = _make_codex_jsonl(
        tmp_path,
        model="gpt-5.5",
        usages=None,  # turn.completed with no usage key
    )
    cost, turns = CodexRunner().extract_metadata(f)
    assert cost is None
    assert turns == 1


def test_codex_extract_metadata_handles_missing_cached_input(tmp_path):
    """``cached_input_tokens`` absent → treated as 0 (still produces a cost)."""
    f = _make_codex_jsonl(
        tmp_path,
        model="gpt-5.4",
        usages=[{"input_tokens": 1000, "output_tokens": 100}],
    )
    cost, turns = CodexRunner().extract_metadata(f)
    assert turns == 1
    # gpt-5.4: input=$2.50, cached=$0.25, output=$15
    # cost = (1000 * 2.5 + 0 * 0.25 + 100 * 15) / 1_000_000
    expected = (1000 * 2.5 + 100 * 15) / 1_000_000.0
    assert cost == pytest.approx(expected, rel=1e-9)


def test_codex_extract_metadata_malformed_jsonl_lines_ignored(tmp_path):
    """Non-JSON / malformed lines are skipped, not raised."""
    f = tmp_path / "agent.jsonl"
    f.write_text(
        json.dumps({"type": "meta", "model": "gpt-5.5"}) + "\n"
        + "WARNING: some stderr line leaked in\n"
        + json.dumps({"type": "turn.started"}) + "\n"
        + json.dumps({"type": "turn.completed", "usage": {
            "input_tokens": 100, "output_tokens": 5
        }}) + "\n"
    )
    cost, turns = CodexRunner().extract_metadata(f)
    assert turns == 1
    assert cost == pytest.approx(
        (100 * 5.0 + 5 * 30.0) / 1_000_000.0, rel=1e-9
    )


# ---------------------------------------------------------------------------
# codex_prices.toml — schema sanity
# ---------------------------------------------------------------------------

def test_codex_prices_toml_contains_three_models():
    """Acceptance: price table covers gpt-5.5, gpt-5.4, gpt-5.4-mini."""
    from swebench.runner import _load_codex_prices
    prices = _load_codex_prices()
    for slug in ("gpt-5.5", "gpt-5.4", "gpt-5.4-mini"):
        assert slug in prices, f"missing {slug} in price table"
        assert prices[slug]["input"] > 0
        assert prices[slug]["cached_input"] >= 0
        assert prices[slug]["output"] > 0


def test_codex_prices_toml_has_dated_header():
    """Acceptance: TOML header records the date and source URL."""
    from pathlib import Path as _P
    import swebench.runner as _r
    path = _P(_r.__file__).parent / "codex_prices.toml"
    content = path.read_text()
    # Must mention a 2026 date and openai.com source so a reviewer can audit it.
    assert "2026" in content
    assert "openai" in content.lower()


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
# verify_auth — surface-agnostic preflight check
# ---------------------------------------------------------------------------

def test_claude_verify_auth_is_noop():
    """ClaudeRunner.verify_auth() returns None without raising, regardless of env."""
    from swebench.runner import ClaudeRunner
    assert ClaudeRunner().verify_auth() is None


def test_codex_verify_auth_raises_when_auth_missing(monkeypatch):
    """CodexRunner.verify_auth() must raise FileNotFoundError when ~/.codex/auth.json is absent."""
    monkeypatch.setattr("swebench.runner.os.path.isfile", lambda _p: False)
    with pytest.raises(FileNotFoundError, match=r"~/\.codex/auth\.json"):
        CodexRunner().verify_auth()


def test_codex_verify_auth_ok_when_auth_present(tmp_path, monkeypatch):
    """CodexRunner.verify_auth() returns None and creates no temp dirs when auth exists."""
    fake_home = tmp_path / "home"
    codex_dir = fake_home / ".codex"
    codex_dir.mkdir(parents=True)
    (codex_dir / "auth.json").write_text('{"token": "test-token"}')

    real_expanduser = os.path.expanduser

    def fake_expanduser(path: str) -> str:
        if path.startswith("~/"):
            return str(fake_home / path[2:])
        return real_expanduser(path)

    monkeypatch.setattr("swebench.runner.os.path.expanduser", fake_expanduser)

    # Sentinel: ensure no temp dir is created during verify_auth.
    def fail_mkdtemp(*_a, **_kw):
        raise AssertionError("verify_auth must not create a temp dir")

    monkeypatch.setattr("swebench.runner.tempfile.mkdtemp", fail_mkdtemp)

    assert CodexRunner().verify_auth() is None


# ---------------------------------------------------------------------------
# CodexRunner — _make_isolated_config (internal helper) still works end-to-end
# ---------------------------------------------------------------------------

def test_codex_make_isolated_config_success(tmp_path, monkeypatch):
    """_make_isolated_config() returns a dir containing auth.json when source exists."""
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

    # _resolve_bundle will look for a bundle; supply a fake bundle via mcp_config.
    bundle = tmp_path / "bundle.mjs"
    bundle.write_text("// fake")
    mcp_json = tmp_path / "mcp.json"
    mcp_json.write_text(json.dumps({
        "mcpServers": {"codebox": {"args": [str(bundle)]}}
    }))

    cfg_dir = CodexRunner()._make_isolated_config(
        mcp_config_path=str(mcp_json),
        cwd=str(tmp_path),
    )
    try:
        assert Path(cfg_dir).is_dir()
        assert (Path(cfg_dir) / "auth.json").is_file()
    finally:
        _shutil.rmtree(cfg_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Codex cache-prefix stabilization (skills symlink + stable process cwd)
# ---------------------------------------------------------------------------

def test_codex_make_isolated_config_creates_skills_symlink(tmp_path, monkeypatch):
    """Per-task CODEX_HOME must have ``skills`` symlinked to the shared dir
    so SKILL.md paths in the developer message stay byte-stable across tasks
    (otherwise OpenAI's prompt cache misses every task)."""
    import shutil as _shutil
    fake_home = tmp_path / "home"
    codex_dir = fake_home / ".codex"
    codex_dir.mkdir(parents=True)
    (codex_dir / "auth.json").write_text('{"token": "t"}')

    real_expanduser = os.path.expanduser
    def fake_expanduser(p):
        if p.startswith("~/"):
            return str(fake_home / p[2:])
        return real_expanduser(p)
    monkeypatch.setattr("swebench.runner.os.path.expanduser", fake_expanduser)

    cfg_dir = CodexRunner()._make_isolated_config(
        mcp_config_path=None, cwd=str(tmp_path), arm="baseline"
    )
    try:
        from swebench.runner import CODEX_SHARED_SKILLS_DIR
        skills_link = Path(cfg_dir) / "skills"
        assert skills_link.is_symlink(), "expected skills/ to be a symlink"
        assert os.readlink(str(skills_link)) == CODEX_SHARED_SKILLS_DIR
    finally:
        _shutil.rmtree(cfg_dir, ignore_errors=True)


def test_arm_uses_stable_process_cwd():
    """Only the code-only family runs with the stable process cwd."""
    from swebench.runner import _arm_uses_stable_process_cwd
    assert _arm_uses_stable_process_cwd("code_only") is True
    assert _arm_uses_stable_process_cwd("onlycode") is True
    assert _arm_uses_stable_process_cwd("tool_rich") is False
    assert _arm_uses_stable_process_cwd("baseline") is False
    assert _arm_uses_stable_process_cwd("bash_only") is False


def test_ensure_codex_cache_dirs_idempotent():
    """Calling the dir-ensure helper multiple times is safe."""
    from swebench.runner import _ensure_codex_cache_dirs, CODEX_SHARED_SKILLS_DIR, CODEX_STABLE_CWD
    _ensure_codex_cache_dirs()
    _ensure_codex_cache_dirs()
    assert os.path.isdir(CODEX_SHARED_SKILLS_DIR)
    assert os.path.isdir(CODEX_STABLE_CWD)


def test_run_command_codex_baseline_skips_bundle_check(tmp_path, monkeypatch):
    """Preflight for codex_cli + baseline must not require the exec-server bundle (F-1)."""
    from click.testing import CliRunner
    from swebench.cli import cli
    from swebench.runner import CodexRunner

    monkeypatch.setattr(
        "swebench.runner.CodexRunner.find_binary",
        lambda self: "/usr/bin/codex",
    )
    # verify_auth must be a no-op (real test of: preflight does not touch the bundle).
    monkeypatch.setattr(
        "swebench.runner.CodexRunner.verify_auth",
        lambda self: None,
    )
    # If preflight wrongly tries to resolve the bundle, this blows up loudly.
    def _bundle_should_not_be_touched(self, _mcp):
        raise AssertionError(
            "preflight must not call _resolve_bundle for baseline arm"
        )
    monkeypatch.setattr(
        "swebench.runner.CodexRunner._resolve_bundle",
        _bundle_should_not_be_touched,
    )

    # Empty problems dir so run_command exits with "No problem files found"
    # *after* preflight succeeds — verifies preflight passes without bundle.
    problems_dir = tmp_path / "problems" / "swe"
    problems_dir.mkdir(parents=True)
    monkeypatch.setattr("swebench.run.repo_root", lambda: tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "run",
            "--agent-surface", "codex_cli",
            "--arms", "baseline",
            "--output-dir", str(tmp_path / "out"),
        ],
        catch_exceptions=False,
    )
    # Preflight succeeded; failure now comes from empty problems dir, not from bundle.
    assert result.exit_code == 1
    assert "No problem files found" in (result.output or ""), (
        f"expected post-preflight failure, got: {result.output!r}"
    )


# ---------------------------------------------------------------------------
# _write_codex_config — arm-conditional onlycode restrictions
# ---------------------------------------------------------------------------

def test_write_codex_config_onlycode_restrictions(tmp_path):
    """onlycode arm: codebox-only — native shell off, browser/computer/apps off, codebox registered."""
    _write_codex_config(str(tmp_path), "/bundle.mjs", "/scratch", "0", arm="onlycode")
    content = (tmp_path / "config.toml").read_text()
    assert "browser_use = false" in content
    assert "computer_use = false" in content
    assert "shell_tool = false" in content
    assert "apply_patch_freeform = false" in content
    # apps=false suppresses request_plugin_install for cache-stable tools array (#292).
    assert "apps = false" in content
    assert 'web_search = "disabled"' in content
    assert "[mcp_servers.codebox]" in content


def test_write_codex_config_code_only_restrictions(tmp_path):
    """code_only arm (artifact mode alias) must emit the same restrictions as onlycode."""
    _write_codex_config(str(tmp_path), "/bundle.mjs", "/scratch", "0", arm="code_only")
    content = (tmp_path / "config.toml").read_text()
    assert "browser_use = false" in content
    assert "computer_use = false" in content
    assert "shell_tool = false" in content
    assert "apps = false" in content
    assert "[mcp_servers.codebox]" in content


def test_write_codex_config_baseline_native_tools(tmp_path):
    """baseline arm: native shell + freeform apply_patch, no codebox MCP."""
    _write_codex_config(str(tmp_path), "/bundle.mjs", "/scratch", "0", arm="baseline")
    content = (tmp_path / "config.toml").read_text()
    assert "shell_tool = true" in content
    assert "apply_patch_freeform = true" in content
    # No browser/computer restrictions — matches Claude tool_rich (full toolset).
    assert "browser_use" not in content
    assert "computer_use" not in content
    # No codebox MCP server registered.
    assert "[mcp_servers.codebox]" not in content


def test_write_codex_config_tool_rich_native_tools(tmp_path):
    """tool_rich arm: identical config to baseline (native tools, no codebox)."""
    _write_codex_config(str(tmp_path), "/bundle.mjs", "/scratch", "0", arm="tool_rich")
    content = (tmp_path / "config.toml").read_text()
    assert "shell_tool = true" in content
    assert "apply_patch_freeform = true" in content
    assert "browser_use" not in content
    assert "computer_use" not in content
    assert "[mcp_servers.codebox]" not in content


def test_write_codex_config_bash_only_restrictions(tmp_path):
    """bash_only arm: native shell only — no codebox, no freeform apply_patch."""
    _write_codex_config(str(tmp_path), "/bundle.mjs", "/scratch", "0", arm="bash_only")
    content = (tmp_path / "config.toml").read_text()
    assert "shell_tool = true" in content
    assert "apply_patch_freeform = false" in content
    assert "browser_use = false" in content
    assert "computer_use = false" in content
    # apps fix is code_only-specific; bash_only retains native plugin tools.
    assert "apps =" not in content
    assert "[mcp_servers.codebox]" not in content


def test_write_codex_config_onlycode_valid_toml(tmp_path):
    """onlycode config must produce valid TOML parseable by tomllib."""
    _write_codex_config(str(tmp_path), "/bundle.mjs", "/scratch", "0", arm="onlycode")
    content = (tmp_path / "config.toml").read_text()
    parsed = tomllib.loads(content)
    assert parsed["features"]["browser_use"] is False
    assert parsed["features"]["computer_use"] is False
    assert parsed["features"]["shell_tool"] is False
    assert parsed["features"]["apply_patch_freeform"] is False
    assert parsed["features"]["apps"] is False
    assert "codebox" in parsed["mcp_servers"]


def test_write_codex_config_bash_only_valid_toml(tmp_path):
    """bash_only config parses cleanly and has the expected feature shape."""
    _write_codex_config(str(tmp_path), "/bundle.mjs", "/scratch", "0", arm="bash_only")
    parsed = tomllib.loads((tmp_path / "config.toml").read_text())
    assert parsed["features"]["shell_tool"] is True
    assert parsed["features"]["apply_patch_freeform"] is False
    assert parsed["features"]["browser_use"] is False
    assert parsed["features"]["computer_use"] is False
    assert "mcp_servers" not in parsed


def test_write_codex_config_tool_rich_valid_toml(tmp_path):
    """tool_rich config parses cleanly with native tools enabled."""
    _write_codex_config(str(tmp_path), "/bundle.mjs", "/scratch", "0", arm="tool_rich")
    parsed = tomllib.loads((tmp_path / "config.toml").read_text())
    assert parsed["features"]["shell_tool"] is True
    assert parsed["features"]["apply_patch_freeform"] is True
    assert "browser_use" not in parsed["features"]
    assert "computer_use" not in parsed["features"]
    assert "mcp_servers" not in parsed


# ---------------------------------------------------------------------------
# CodexRunner.build_tools_flags — stores _arm for invoke()
# ---------------------------------------------------------------------------

def test_codex_build_tools_flags_stores_arm():
    """build_tools_flags must set self._arm so invoke() can read it."""
    runner = CodexRunner()
    runner.build_tools_flags("onlycode", None)
    assert runner._arm == "onlycode"


def test_codex_build_tools_flags_baseline_stores_arm():
    runner = CodexRunner()
    runner.build_tools_flags("baseline", None)
    assert runner._arm == "baseline"


# ---------------------------------------------------------------------------
# CodexRunner — arm-specific prompt directives (soft apply_patch suppression)
# ---------------------------------------------------------------------------

def test_apply_arm_directive_tool_rich_passthrough():
    """tool_rich and baseline must NOT prepend any directive."""
    from swebench.runner import _apply_arm_directive
    base = "solve this problem"
    assert _apply_arm_directive(base, "tool_rich") == base
    assert _apply_arm_directive(base, "baseline") == base


def test_apply_arm_directive_code_only_prepends_codebox_only_instruction():
    """code_only / onlycode must prepend a directive restricting tools to codebox."""
    from swebench.runner import _apply_arm_directive
    out = _apply_arm_directive("body", "code_only")
    assert out.endswith("body")
    assert out != "body"
    assert "execute_code" in out
    assert "apply_patch" in out
    # onlycode alias gets the same directive.
    assert _apply_arm_directive("body", "onlycode") == out


def test_apply_arm_directive_bash_only_prepends_shell_only_instruction():
    """bash_only must prepend a directive restricting tools to shell."""
    from swebench.runner import _apply_arm_directive
    out = _apply_arm_directive("body", "bash_only")
    assert out.endswith("body")
    assert out != "body"
    assert "shell" in out.lower()
    assert "apply_patch" in out


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


# ---------------------------------------------------------------------------
# _toml_str — escape helper
# ---------------------------------------------------------------------------

def test_toml_str_escapes_backslash():
    assert _toml_str("C:\\foo") == "C:\\\\foo"


def test_toml_str_escapes_quote():
    assert _toml_str('say "hi"') == 'say \\"hi\\"'


def test_toml_str_passthrough_clean():
    assert _toml_str("/clean/path") == "/clean/path"


def test_write_codex_config_roundtrip_paths(tmp_path):
    """Paths with backslash and quote must round-trip through config.toml.

    Uses arm=code_only because that's the only arm that registers the codebox
    MCP server (and therefore the only arm where these path fields appear).
    """
    bundle_path = 'C:\\Users\\test "user"\\bundle.mjs'
    cwd = 'C:\\work dir\\"quoted"'
    _write_codex_config(str(tmp_path), bundle_path, cwd, "0", arm="code_only")
    toml_text = (tmp_path / "config.toml").read_text()
    parsed = tomllib.loads(toml_text)
    assert parsed["mcp_servers"]["codebox"]["args"][0] == bundle_path
    assert parsed["mcp_servers"]["codebox"]["options"]["cwd"] == cwd


# ---------------------------------------------------------------------------
# CodexRunner.preflight() — all four cases
# ---------------------------------------------------------------------------

def test_codex_preflight_happy(monkeypatch):
    """preflight() returns None when node, binary, and bundle are all found."""
    monkeypatch.setattr("swebench.runner.shutil.which", lambda name: "/usr/bin/node" if name == "node" else None)
    monkeypatch.setattr("swebench.runner.CodexRunner.find_binary", lambda self: "/usr/bin/codex")
    monkeypatch.setattr("swebench.runner.CodexRunner._resolve_bundle", lambda self, _: "/fake/bundle.mjs")
    result = CodexRunner().preflight()
    assert result is None


def test_codex_preflight_no_node(monkeypatch):
    """preflight() raises RuntimeError with 'node' in message when node is absent."""
    monkeypatch.setattr("swebench.runner.shutil.which", lambda _name: None)
    with pytest.raises(RuntimeError, match="node"):
        CodexRunner().preflight()


def test_codex_preflight_no_binary(monkeypatch):
    """preflight() raises RuntimeError when codex binary is not found."""
    monkeypatch.setattr("swebench.runner.shutil.which", lambda name: "/usr/bin/node" if name == "node" else None)
    monkeypatch.setattr(
        "swebench.runner.CodexRunner.find_binary",
        lambda self: (_ for _ in ()).throw(FileNotFoundError("codex binary not found")),
    )
    with pytest.raises(RuntimeError):
        CodexRunner().preflight()


def test_codex_preflight_no_bundle(monkeypatch):
    """preflight() raises RuntimeError with 'bundle' in message when bundle is absent."""
    monkeypatch.setattr("swebench.runner.shutil.which", lambda name: "/usr/bin/node" if name == "node" else None)
    monkeypatch.setattr("swebench.runner.CodexRunner.find_binary", lambda self: "/usr/bin/codex")
    monkeypatch.setattr(
        "swebench.runner.CodexRunner._resolve_bundle",
        lambda self, _: (_ for _ in ()).throw(FileNotFoundError("exec-server bundle not found")),
    )
    with pytest.raises(RuntimeError, match="bundle"):
        CodexRunner().preflight()
