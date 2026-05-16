"""Agent-runner abstraction for Claude Code and Codex CLI.

Each runner encapsulates binary discovery, config/auth isolation, MCP config
generation, subprocess invocation, and metadata extraction for one agent surface.

Callers interact through the AgentRunner interface:

    runner = make_runner("claude_code")   # or "codex_cli"
    binary  = runner.find_binary()
    version = runner.get_version(binary)
    flags   = runner.build_tools_flags(arm, mcp_config_path)
    runner.invoke(
        prompt=prompt, cwd=scratch_dir, system_prompt=sys_prompt,
        tools_flags=flags, result_file=out_path, binary=binary,
        mcp_config_path=mcp_config_path,
    )
    cost, turns = runner.extract_metadata(Path(out_path))

Config/auth isolation is handled *internally* by each runner's invoke() method —
callers do not manage temp dirs directly.
"""

from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

# Imported by run.py and artifact_cli.py so rejection error wording is consistent.
CODEX_NOT_IMPLEMENTED_MSG = "not yet implemented — see Slice 5"

# Built-in Claude tools blocked for onlycode / code_only arms.
# Canonical single source of truth — imported by run.py and artifact_run.py.
BLOCKED_BUILTINS = (
    "Agent,AskUserQuestion,Bash,CronCreate,CronDelete,CronList,"
    "Edit,EnterPlanMode,EnterWorktree,ExitPlanMode,ExitWorktree,"
    "Glob,Grep,ListMcpResourcesTool,LSP,Monitor,NotebookEdit,"
    "PowerShell,PushNotification,Read,ReadMcpResourceTool,"
    "RemoteTrigger,SendMessage,Skill,"
    "TaskCreate,TaskGet,TaskList,TaskOutput,TaskStop,TaskUpdate,"
    "TeamCreate,TeamDelete,TodoWrite,ToolSearch,WebFetch,WebSearch,Write"
)


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class AgentRunner(ABC):
    """Common interface for invoking an agent binary with reproducible isolation."""

    surface: ClassVar[str]  # "claude_code" | "codex_cli"

    @abstractmethod
    def find_binary(self) -> str:
        """Return path to the agent binary, or raise FileNotFoundError."""

    @abstractmethod
    def verify_auth(self) -> None:
        """Raise FileNotFoundError if required auth artifacts are missing.

        Called by preflight code. Must have no side effects (no temp dirs,
        no file copies). Returning ``None`` means auth is plausibly valid;
        it does not guarantee a live session.
        """

    @abstractmethod
    def get_version(self, binary: str) -> str:
        """Return a version string for the binary, or 'unknown'."""

    @abstractmethod
    def build_tools_flags(self, arm: str, mcp_config_path: str | None) -> list[str]:
        """Return CLI flags controlling tool access for the given arm."""

    @abstractmethod
    def invoke(
        self,
        *,
        prompt: str,
        cwd: str,
        system_prompt: str,
        tools_flags: list[str],
        result_file: str,
        binary: str,
        mcp_config_path: str | None = None,
    ) -> None:
        """Run the agent, appending output to result_file. Non-zero exit does not raise.

        ``mcp_config_path`` is used by CodexRunner to locate the exec-server
        bundle. ClaudeRunner ignores it (the path is already embedded in
        ``tools_flags`` via ``--mcp-config``).
        """

    @abstractmethod
    def extract_metadata(self, jsonl_path: Path) -> tuple[float | None, int | None]:
        """Parse (cost_usd, num_turns) from the agent output file."""


# ---------------------------------------------------------------------------
# ClaudeRunner
# ---------------------------------------------------------------------------

class ClaudeRunner(AgentRunner):
    """Runs Claude Code (the ``claude`` CLI)."""

    surface = "claude_code"

    def find_binary(self) -> str:
        env_val = os.environ.get("CLAUDE")
        if env_val and os.path.isfile(env_val) and os.access(env_val, os.X_OK):
            return env_val

        path = shutil.which("claude")
        if path:
            return path

        for ext_dir in sorted(
            glob.glob(
                "/home/vscode/.vscode-server/extensions/"
                "anthropic.claude-code-*-linux-x64"
            ),
            reverse=True,
        ):
            candidate = os.path.join(
                ext_dir, "resources", "native-binary", "claude"
            )
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate

        raise FileNotFoundError(
            "claude binary not found. Set CLAUDE= or install Claude Code."
        )

    def verify_auth(self) -> None:
        # Claude credentials are copied into a temp config dir inside invoke();
        # surface-level pre-check is intentionally a no-op.
        return

    def get_version(self, binary: str) -> str:
        try:
            proc = subprocess.run(
                [binary, "--version"], capture_output=True, text=True, timeout=10
            )
            return proc.stdout.strip() or proc.stderr.strip() or "unknown"
        except Exception:
            return "unknown"

    def build_tools_flags(self, arm: str, mcp_config_path: str | None) -> list[str]:
        if arm in ("tool_rich", "baseline"):
            return []
        if arm in ("code_only", "onlycode"):
            flags: list[str] = []
            if mcp_config_path:
                flags += ["--mcp-config", mcp_config_path, "--strict-mcp-config"]
            flags += [
                "--tools", "mcp__codebox__execute_code,mcp__codebox__list_tools",
                "--disallowedTools", BLOCKED_BUILTINS,
            ]
            return flags
        if arm == "bash_only":
            blocked = ",".join(
                t for t in BLOCKED_BUILTINS.split(",") if t.strip() != "Bash"
            )
            return ["--tools", "Bash", "--disallowedTools", blocked]
        raise ValueError(f"Unknown arm for ClaudeRunner: {arm!r}")

    def invoke(
        self,
        *,
        prompt: str,
        cwd: str,
        system_prompt: str,
        tools_flags: list[str],
        result_file: str,
        binary: str,
        mcp_config_path: str | None = None,  # unused; already in tools_flags
    ) -> None:
        cfg_dir = tempfile.mkdtemp(prefix="claude-eval-")
        try:
            for fname in (".credentials.json", ".claude.json"):
                src = os.path.expanduser(f"~/.claude/{fname}")
                if os.path.isfile(src):
                    shutil.copy2(src, cfg_dir)

            cmd = [
                binary,
                "-p", prompt,
                "--model", "claude-sonnet-4-6",
                "--system-prompt", system_prompt,
                *tools_flags,
                "--dangerously-skip-permissions",
                "--no-session-persistence",
                "--output-format", "stream-json",
                "--verbose",
            ]
            env = os.environ.copy()
            env["CLAUDE_CONFIG_DIR"] = cfg_dir
            env["FORCE_PROMPT_CACHING_5M"] = "1"
            with open(result_file, "a") as out:
                subprocess.run(
                    cmd, cwd=cwd, stdout=out, stderr=subprocess.STDOUT, env=env
                )
        finally:
            shutil.rmtree(cfg_dir, ignore_errors=True)

    def extract_metadata(self, jsonl_path: Path) -> tuple[float | None, int | None]:
        try:
            content = jsonl_path.read_text()
        except OSError:
            return (None, None)
        cost: float | None = None
        turns: int | None = None
        cost_match = re.findall(r'"total_cost_usd":\s*([\d.]+)', content)
        if cost_match:
            try:
                cost = float(cost_match[-1])
            except ValueError:
                pass
        turns_match = re.findall(r'"num_turns":\s*(\d+)', content)
        if turns_match:
            try:
                turns = int(turns_match[-1])
            except ValueError:
                pass
        return (cost, turns)


# ---------------------------------------------------------------------------
# CodexRunner
# ---------------------------------------------------------------------------

class CodexRunner(AgentRunner):
    """Runs OpenAI Codex CLI (the ``codex`` binary)."""

    surface = "codex_cli"

    def find_binary(self) -> str:
        path = shutil.which("codex")
        if path:
            return path
        raise FileNotFoundError(
            "codex binary not found. Install with: npm install -g @openai/codex"
        )

    def verify_auth(self) -> None:
        src = os.path.expanduser("~/.codex/auth.json")
        if not os.path.isfile(src):
            raise FileNotFoundError(
                "~/.codex/auth.json not found — Codex CLI requires a valid auth token."
            )

    def get_version(self, binary: str) -> str:
        try:
            proc = subprocess.run(
                [binary, "--version"], capture_output=True, text=True, timeout=10
            )
            return proc.stdout.strip() or proc.stderr.strip() or "unknown"
        except Exception:
            return "unknown"

    def build_tools_flags(self, arm: str, mcp_config_path: str | None) -> list[str]:
        # Tool restriction is enforced via [features] in config.toml, not CLI flags.
        if arm not in ("tool_rich", "baseline", "code_only", "onlycode", "bash_only"):
            raise ValueError(f"Unknown arm for CodexRunner: {arm!r}")
        return []

    def _make_isolated_config(
        self,
        mcp_config_path: str | None = None,
        cwd: str = ".",
    ) -> str:
        """Create an isolated CODEX_HOME directory for a single run.

        Private helper of ``invoke()``. Copies ``~/.codex/auth.json`` into
        a fresh temp dir and writes ``config.toml``. Re-runs the auth check
        as defense-in-depth; preflight callers should use ``verify_auth()``
        instead, which has no side effects.

        Returns the path to the isolated config directory; ``invoke()`` is
        responsible for ``shutil.rmtree``.
        """
        self.verify_auth()
        src = os.path.expanduser("~/.codex/auth.json")

        cfg_dir = tempfile.mkdtemp(prefix="codex-eval-")
        shutil.copy2(src, cfg_dir)

        bundle_path = self._resolve_bundle(mcp_config_path)
        persistent = os.environ.get("ONLYCODES_PERSISTENT_KERNEL", "0")
        _write_codex_config(cfg_dir, bundle_path, cwd, persistent)

        return cfg_dir

    def invoke(
        self,
        *,
        prompt: str,
        cwd: str,
        system_prompt: str,
        tools_flags: list[str],  # always [] for Codex; kept for interface compat
        result_file: str,
        binary: str,
        mcp_config_path: str | None = None,
    ) -> None:
        """Run codex exec with an isolated CODEX_HOME containing auth + MCP config."""
        cfg_dir = self._make_isolated_config(mcp_config_path=mcp_config_path, cwd=cwd)
        try:
            cmd = [
                binary, "exec",
                "--ephemeral",
                "--dangerously-bypass-approvals-and-sandbox",
                "--json",
                prompt,
            ]
            env = os.environ.copy()
            env["CODEX_HOME"] = cfg_dir
            with open(result_file, "a") as out:
                subprocess.run(
                    cmd,
                    cwd=cwd,
                    stdout=out,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    env=env,
                )
        finally:
            shutil.rmtree(cfg_dir, ignore_errors=True)

    def extract_metadata(self, jsonl_path: Path) -> tuple[float | None, int | None]:
        try:
            content = jsonl_path.read_text()
        except OSError:
            return (None, None)
        turns = sum(
            1
            for line in content.splitlines()
            if _safe_json_type(line) == "turn.started"
        )
        # Codex does not expose a cost field for ChatGPT Pro sessions.
        return (None, turns if turns > 0 else None)

    def preflight(self, mcp_config_path: str | None = None) -> None:
        """Verify all Codex runtime dependencies before starting a run.

        Raises ``RuntimeError`` (not ``FileNotFoundError``) with an actionable
        message for each of the following failure modes (checked in order):

        1. ``node`` is not on PATH.
        2. The ``codex`` binary is not found.
        3. The exec-server bundle is not found.

        Returns ``None`` on success. Has no side effects (no temp dirs, no
        file writes).
        """
        if not shutil.which("node"):
            raise RuntimeError(
                "node not found on PATH. Install Node.js to run the exec-server."
            )
        try:
            self.find_binary()
        except FileNotFoundError as exc:
            raise RuntimeError(str(exc)) from exc
        try:
            self._resolve_bundle(mcp_config_path)
        except FileNotFoundError as exc:
            raise RuntimeError(str(exc)) from exc

    def _resolve_bundle(self, mcp_config_path: str | None) -> str:
        """Return the exec-server JS bundle path.

        Tries to read it from the JSON MCP config (Claude format), then falls
        back to the default build output location.
        """
        if mcp_config_path and os.path.isfile(mcp_config_path):
            try:
                with open(mcp_config_path) as f:
                    cfg = json.load(f)
                args = cfg.get("mcpServers", {}).get("codebox", {}).get("args", [])
                if args and os.path.isfile(args[0]):
                    return args[0]
            except (json.JSONDecodeError, KeyError, IndexError):
                pass
        # Default: bundle next to this package.
        candidate = Path(__file__).parent.parent / "exec_server" / "dist" / "exec-server.bundle.mjs"
        if candidate.is_file():
            return str(candidate)
        raise FileNotFoundError(
            f"exec-server bundle not found. Run `npm run build` in exec_server/. "
            f"Tried: {candidate}"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _toml_str(s: str) -> str:
    """Escape a string for use in a TOML basic string (double-quoted value).

    Escapes backslashes first, then double-quote characters, so the result
    can be safely embedded between ``"..."`` in a TOML document.
    """
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _write_codex_config(
    cfg_dir: str,
    bundle_path: str,
    cwd: str,
    persistent_kernel: str,
) -> None:
    """Write config.toml into cfg_dir for a Codex run.

    Avoids an external TOML library by rendering the known-shape config
    as a string directly.
    """
    toml = (
        'web_search = "disabled"\n'
        "\n"
        "[features]\n"
        "shell_tool = false\n"
        "apply_patch_freeform = false\n"
        "\n"
        "[mcp_servers.codebox]\n"
        'command = "node"\n'
        f'args = ["{_toml_str(bundle_path)}"]\n'
        "\n"
        "[mcp_servers.codebox.env]\n"
        f'ONLYCODES_PERSISTENT_KERNEL = "{_toml_str(persistent_kernel)}"\n'
        "\n"
        "[mcp_servers.codebox.options]\n"
        f'enabled_tools = ["execute_code", "execute_code_and_wait"]\n'
        f"startup_timeout_sec = 30.0\n"
        f'cwd = "{_toml_str(cwd)}"\n'
    )
    with open(os.path.join(cfg_dir, "config.toml"), "w") as f:
        f.write(toml)


def _safe_json_type(line: str) -> str | None:
    """Parse a JSONL line and return its 'type' field, or None on error."""
    try:
        return json.loads(line).get("type")
    except (json.JSONDecodeError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def make_runner(surface: str) -> AgentRunner:
    """Return an AgentRunner for the given surface name."""
    if surface == "claude_code":
        return ClaudeRunner()
    if surface == "codex_cli":
        return CodexRunner()
    raise ValueError(
        f"Unknown agent surface: {surface!r}. "
        f"Valid values: 'claude_code', 'codex_cli'."
    )
