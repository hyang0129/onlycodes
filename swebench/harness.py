"""Shared subprocess wrappers for git, claude binary, venv setup, and test running."""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def find_claude_binary() -> str:
    """Locate the claude binary — PATH first, then VS Code extension glob.

    Returns the path to the claude binary, or raises FileNotFoundError.
    """
    # Check CLAUDE env var first
    claude_env = os.environ.get("CLAUDE")
    if claude_env and os.path.isfile(claude_env) and os.access(claude_env, os.X_OK):
        return claude_env

    # Check PATH
    claude_path = shutil.which("claude")
    if claude_path:
        return claude_path

    # Try VS Code extension path
    for ext_dir in sorted(
        glob.glob("/home/vscode/.vscode-server/extensions/anthropic.claude-code-*-linux-x64"),
        reverse=True,
    ):
        candidate = os.path.join(ext_dir, "resources", "native-binary", "claude")
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate

    raise FileNotFoundError(
        "claude binary not found. Set CLAUDE= or install Claude Code."
    )


def git_reset(repo_dir: str, commit: str) -> None:
    """Hard-reset a repo to a given commit and clean untracked files."""
    subprocess.run(
        ["git", "-C", repo_dir, "checkout", commit, "--force", "--quiet"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", repo_dir, "clean", "-fd", "--quiet"],
        check=True,
        capture_output=True,
    )


def clone_repo(repo_slug: str, dest: str) -> None:
    """Clone a GitHub repo if not already cloned."""
    if os.path.isdir(os.path.join(dest, ".git")):
        return
    subprocess.run(
        ["gh", "repo", "clone", repo_slug, dest, "--", "--quiet"],
        check=True,
        capture_output=True,
    )


def setup_venv(venv_dir: str, repo_dir: str) -> None:
    """Create a venv and pip install the project in editable mode (if not already done)."""
    if os.path.isdir(venv_dir):
        return
    subprocess.run(
        ["python3.11", "-m", "venv", venv_dir],
        check=True,
        capture_output=True,
    )
    pip = os.path.join(venv_dir, "bin", "pip")
    subprocess.run(
        [pip, "install", "--quiet", "-e", repo_dir],
        capture_output=True,
    )


def apply_test_patch(repo_dir: str, patch_path: str) -> bool:
    """Apply a test patch to the repo. Returns True if successful."""
    if not os.path.isfile(patch_path):
        return False
    result = subprocess.run(
        ["git", "-C", repo_dir, "apply", patch_path],
        capture_output=True,
    )
    return result.returncode == 0


def make_isolated_claude_config() -> str:
    """Create an isolated Claude config directory with only credentials.

    Returns the path to the temp directory. Caller must clean up.
    """
    cfg_dir = tempfile.mkdtemp(prefix="claude-eval-")
    for fname in (".credentials.json", ".claude.json"):
        src = os.path.expanduser(f"~/.claude/{fname}")
        if os.path.isfile(src):
            shutil.copy2(src, cfg_dir)
    return cfg_dir


def generate_mcp_config(base_config_path: str, cwd: str) -> str:
    """Generate a per-run MCP config with cwd set to the target repo.

    Returns the path to the temp config file. Caller must clean up.
    """
    if not os.path.isfile(base_config_path):
        return base_config_path

    with open(base_config_path) as f:
        config = json.load(f)

    # Set cwd on the codebox server only (matches run_swebench.sh behavior)
    codebox = config.get("mcpServers", {}).get("codebox")
    if codebox is not None:
        codebox["cwd"] = cwd

    tmp = tempfile.NamedTemporaryFile(
        prefix="mcp-config-",
        suffix=".json",
        mode="w",
        delete=False,
    )
    json.dump(config, tmp)
    tmp.close()
    return tmp.name


def run_claude(
    *,
    prompt: str,
    repo_dir: str,
    system_prompt: str,
    tools_flags: list[str],
    result_file: str,
    claude_binary: str,
) -> None:
    """Run the claude binary with isolated config. Non-zero exit does not raise."""
    cfg_dir = make_isolated_claude_config()
    try:
        cmd = [
            claude_binary,
            "-p", prompt,
            "--model", "claude-sonnet-4-6",
            "--cwd", repo_dir,
            "--system-prompt", system_prompt,
            *tools_flags,
            "--dangerously-skip-permissions",
            "--no-session-persistence",
            "--output-format", "stream-json",
            "--verbose",
        ]

        env = os.environ.copy()
        env["CLAUDE_CONFIG_DIR"] = cfg_dir

        with open(result_file, "w") as out:
            subprocess.run(cmd, stdout=out, stderr=subprocess.STDOUT, env=env)
    finally:
        shutil.rmtree(cfg_dir, ignore_errors=True)


def run_tests(
    *,
    repo_dir: str,
    test_cmd: str,
    venv_dir: str,
    result_file: str,
) -> str:
    """Run the test suite and write results. Returns 'PASS' or 'FAIL'."""
    # Replace leading 'python' with venv python
    venv_python = os.path.join(venv_dir, "bin", "python")
    if test_cmd.startswith("python "):
        effective_cmd = venv_python + test_cmd[len("python"):]
    else:
        effective_cmd = test_cmd

    with open(result_file, "w") as out:
        proc = subprocess.run(
            effective_cmd,
            shell=True,
            cwd=repo_dir,
            stdout=out,
            stderr=subprocess.STDOUT,
        )

    verdict = "PASS" if proc.returncode == 0 else "FAIL"

    with open(result_file, "a") as out:
        out.write(f"\n{verdict}\n")

    return verdict
