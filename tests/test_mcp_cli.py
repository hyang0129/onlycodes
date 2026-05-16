"""Tests for swebench.mcp_cli — `mcp-config generate` subcommand."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from swebench.mcp_cli import mcp_group


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_env(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    """Set up a fake repo root with a real bundle file.

    Returns (pkg_root, bundle_path).
    """
    pkg_root = tmp_path / "repo"
    bundle_dir = pkg_root / "exec_server" / "dist"
    bundle_dir.mkdir(parents=True)
    bundle = bundle_dir / "exec-server.bundle.mjs"
    bundle.write_text("// fake bundle\n")

    # Point swebench.repo_root() at our fake repo root.
    monkeypatch.setattr("swebench.mcp_cli.swebench.repo_root", lambda: pkg_root)

    # Make node resolvable.
    monkeypatch.setattr("swebench.mcp_cli.shutil.which", lambda name: "/usr/bin/node" if name == "node" else None)

    return pkg_root, bundle


# ---------------------------------------------------------------------------
# test_generate_fresh_write
# ---------------------------------------------------------------------------

def test_generate_fresh_write(tmp_path, monkeypatch):
    """generate exits 0, writes valid JSON with a 'codebox' server entry."""
    pkg_root, bundle = _make_env(tmp_path, monkeypatch)
    out_path = tmp_path / "out" / "mcp-config.json"
    out_path.parent.mkdir(parents=True)

    runner = CliRunner()
    result = runner.invoke(mcp_group, ["generate", "--out", str(out_path)])

    assert result.exit_code == 0, f"Unexpected exit: {result.exit_code!r}\noutput: {result.output}"
    assert out_path.exists(), "Output file was not created"

    config = json.loads(out_path.read_text())
    assert "mcpServers" in config
    assert "codebox" in config["mcpServers"]
    codebox = config["mcpServers"]["codebox"]
    assert codebox["command"] == "/usr/bin/node"
    assert str(bundle) in codebox["args"]


# ---------------------------------------------------------------------------
# test_generate_merge_preserves_other_servers
# ---------------------------------------------------------------------------

def test_generate_merge_preserves_other_servers(tmp_path, monkeypatch):
    """generate merges into an existing config, keeping non-codebox servers."""
    pkg_root, bundle = _make_env(tmp_path, monkeypatch)
    out_path = tmp_path / "mcp-config.json"

    # Pre-populate with an unrelated server.
    existing = {
        "mcpServers": {
            "othertool": {"type": "stdio", "command": "x", "args": []}
        }
    }
    out_path.write_text(json.dumps(existing, indent=2) + "\n")

    runner = CliRunner()
    result = runner.invoke(mcp_group, ["generate", "--out", str(out_path)])

    assert result.exit_code == 0, f"Unexpected exit: {result.exit_code!r}\noutput: {result.output}"

    config = json.loads(out_path.read_text())
    assert "othertool" in config["mcpServers"], "othertool server was lost"
    assert "codebox" in config["mcpServers"], "codebox server missing"
    assert config["mcpServers"]["othertool"]["command"] == "x"


# ---------------------------------------------------------------------------
# test_generate_missing_bundle_exits_nonzero
# ---------------------------------------------------------------------------

def test_generate_missing_bundle_exits_nonzero(tmp_path, monkeypatch):
    """generate exits non-zero and mentions 'npm run build' when bundle is absent."""
    # Set up a repo root WITHOUT the bundle.
    pkg_root = tmp_path / "repo"
    pkg_root.mkdir(parents=True)
    monkeypatch.setattr("swebench.mcp_cli.swebench.repo_root", lambda: pkg_root)
    monkeypatch.setattr(
        "swebench.mcp_cli.shutil.which",
        lambda name: "/usr/bin/node" if name == "node" else None,
    )

    out_path = tmp_path / "mcp-config.json"

    # Default CliRunner mixes stderr into output, so the error message appears there.
    runner = CliRunner()
    result = runner.invoke(mcp_group, ["generate", "--out", str(out_path)])

    assert result.exit_code != 0, "Expected non-zero exit when bundle is absent"
    assert "npm run build" in (result.output or ""), (
        f"Expected 'npm run build' mention. Output: {result.output!r}"
    )


# ---------------------------------------------------------------------------
# test_generate_invalid_existing_json_exits_nonzero
# ---------------------------------------------------------------------------

def test_generate_invalid_existing_json_exits_nonzero(tmp_path, monkeypatch):
    """generate exits non-zero when --out exists but contains invalid JSON."""
    pkg_root, bundle = _make_env(tmp_path, monkeypatch)
    out_path = tmp_path / "mcp-config.json"
    out_path.write_text("{not valid")

    runner = CliRunner()
    result = runner.invoke(mcp_group, ["generate", "--out", str(out_path)])

    assert result.exit_code != 0, (
        f"Expected non-zero exit for invalid JSON, got {result.exit_code}. "
        f"Output: {result.output!r}"
    )
