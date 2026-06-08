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
import hashlib
import json
import logging
import os
import re
import signal
import shutil
import subprocess
import tempfile
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import ClassVar


def generate_isolation_nonce(instance_id: str, arm: str, run_idx: int) -> str:
    """Return a fresh 16-hex nonce for a (task, arm, run_idx) invocation.

    Used by ``--cache-isolation`` (#294, #296). Each call mixes a microsecond
    UTC timestamp with the (instance, arm, run_idx) salt and hashes to 16 hex,
    so:

    - **Reruns** of the same triple produce different nonces — the new run
      cannot inherit a prior run's prompt-cache entry still warm within the
      provider's TTL window.
    - **Different sweeps** of the same triple (e.g. ``seed_1`` vs ``seed_2``
      output dirs) likewise mint independent nonces.
    - **Concurrent invocations** of *different* triples are safe even if they
      land on the same microsecond, because the identifier salt distinguishes
      them. Concurrent calls for the *same* triple are not expected (the
      scheduler dispatches each triple to one worker).
    - **Cross-arm** isolation: arm is part of the salt, preserving the original
      #294 guarantee that arms within a task do not share a cache key.

    ``--resume`` correctness is preserved because completed runs are skipped
    by ``is_run_complete()`` *before* this function is called — the prior
    nonce is irrelevant for a fresh resumed invocation.

    ⚠ KNOWN-LIMITATION (2026-05-26): empirical cache isolation is NOT reliably
    achieved by this nonce. See the docstring on the ``--cache-isolation``
    flag (in ``run.py`` and ``artifact_cli.py``) and the ``invoke`` methods
    of ``ClaudeRunner`` and ``CodexRunner`` for the failure-mode details.
    Treat the nonce as a *necessary but insufficient* component of isolation:
    the tools[] payload differs per task as designed, but neither vendor
    documents a flag that scopes or skips the prompt cache, and observed
    cached_input_tokens on iso-runs match contaminated runs in smoke tests.
    """
    salt = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%f")
    raw = f"{salt}|{instance_id}|{arm}|{run_idx}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

# Built-in Claude tools blocked for onlycode / code_only arms.
# Canonical single source of truth — imported by run.py and artifact_run.py.
#
# This is the full known built-in surface of the ``claude`` binary. It also
# seeds the *baseline* disallow list (everything here minus CODING_ALLOWLIST),
# so any agentic-orchestration tool added to the binary must be mirrored here
# to keep both arms reproducible across binary versions. ``Task`` (the subagent
# spawner — distinct from the legacy ``Agent`` alias), ``Workflow`` and
# ``ScheduleWakeup`` were observed in the binary's default surface (2026-06-06,
# issue #334) but missing from this list; the onlycode allowlist masked the gap,
# the unrestricted baseline did not.
BLOCKED_BUILTINS = (
    "Agent,AskUserQuestion,Bash,CronCreate,CronDelete,CronList,"
    "Edit,EnterPlanMode,EnterWorktree,ExitPlanMode,ExitWorktree,"
    "Glob,Grep,ListMcpResourcesTool,LSP,Monitor,NotebookEdit,"
    "PowerShell,PushNotification,Read,ReadMcpResourceTool,"
    "RemoteTrigger,ScheduleWakeup,SendMessage,Skill,"
    "Task,TaskCreate,TaskGet,TaskList,TaskOutput,TaskStop,TaskUpdate,"
    "TeamCreate,TeamDelete,TodoWrite,ToolSearch,WebFetch,WebSearch,"
    "Workflow,Write"
)

# Canonical "native file-system coding" tool surface for the baseline /
# tool_rich arms. The baseline is pinned to exactly this allowlist (and
# everything else in BLOCKED_BUILTINS is disallowed) so it is an apples-to-apples
# "native tools vs code-only" contrast: no subagents (Task), no automation
# (Cron*, Workflow, ScheduleWakeup, Monitor, RemoteTrigger), no web access —
# but with Glob/Grep restored (the binary default omits them). See issue #334.
CODING_ALLOWLIST = "Bash,Edit,Glob,Grep,Read,Write"


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
        wall_timeout_seconds: int = 3600,
        isolation_nonce: str | None = None,
    ) -> None:
        """Run the agent, appending output to result_file. Non-zero exit does not raise.

        ``mcp_config_path`` is used by CodexRunner to locate the exec-server
        bundle. ClaudeRunner ignores it (the path is already embedded in
        ``tools_flags`` via ``--mcp-config``).

        ``wall_timeout_seconds`` caps the total wall time of the agent subprocess.
        Pass 0 for unlimited.

        ``isolation_nonce`` enables per-task prompt-cache isolation when set
        (see issue #294). For CodexRunner, the nonce is injected into the
        ``tools[]`` array via an extra stub MCP server, breaking OpenAI's
        cross-task prompt cache. For ClaudeRunner, this is currently a no-op
        — Claude's cache architecture differs and a symmetric mechanism is
        a future follow-up (TODO).
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
            # Pin to the canonical coding allowlist instead of inheriting the
            # binary's full default surface (which includes subagents and
            # automation tools, and omits Glob/Grep). #334. ``--tools`` acts as
            # a true allowlist for this binary; the explicit ``--disallowedTools``
            # is defense-in-depth against allowlist-semantics drift.
            allow = set(CODING_ALLOWLIST.split(","))
            blocked = ",".join(
                t for t in BLOCKED_BUILTINS.split(",") if t.strip() not in allow
            )
            return ["--tools", CODING_ALLOWLIST, "--disallowedTools", blocked]
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
        wall_timeout_seconds: int = 3600,
        isolation_nonce: str | None = None,
    ) -> None:
        cfg_dir = tempfile.mkdtemp(prefix="claude-eval-")
        try:
            for fname in (".credentials.json", ".claude.json"):
                src = os.path.expanduser(f"~/.claude/{fname}")
                if os.path.isfile(src):
                    shutil.copy2(src, cfg_dir)

            env = os.environ.copy()
            env["CLAUDE_CONFIG_DIR"] = cfg_dir
            env["FORCE_PROMPT_CACHING_5M"] = "1"

            # Per-invocation prompt-cache isolation (#296). Register the
            # iso_nonce stub MCP server so the tool name embedded in
            # Anthropic's tools[] array differs per invocation, missing the
            # prefix cache. The stub tool is added to --disallowedTools so
            # the agent cannot accidentally call it.
            #
            # ⚠ DOES NOT WORK (2026-05-26 smoke test, 3 back-to-back tasks):
            # Claude Code reports the stub MCP as status:pending in the
            # session-init record, so the nonced tool never lands in the
            # outbound tools[] before the first API call. Iso-pass JSONLs
            # show identical first-turn cache_read_input_tokens to a
            # contaminated baseline pass (~9871 tokens on tasks 2 and 3;
            # primer at 0). The failure is invisible to unit tests because
            # the argv shape is correct — it is a property of Claude Code's
            # MCP startup race we do not control. Kept enabled so the
            # nonce is recorded in the JSONL meta and so the harness flag
            # composes with other isolation mechanisms; do not interpret
            # presence of the nonce as evidence of cold cache.
            if isolation_nonce:
                iso_server_path = _resolve_iso_nonce_server()
                base_cfg: str | None = None
                if "--mcp-config" in tools_flags:
                    idx = tools_flags.index("--mcp-config")
                    base_cfg = tools_flags[idx + 1]
                merged_cfg = _write_claude_iso_mcp_config(
                    base_cfg, iso_server_path, isolation_nonce, cfg_dir
                )
                iso_tool = f"mcp__iso_nonce__iso_nonce_{isolation_nonce}"
                tools_flags = _splice_iso_into_claude_flags(
                    tools_flags, merged_cfg, iso_tool
                )
                env["ONLYCODES_ISOLATION_NONCE"] = isolation_nonce

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
            effective_timeout = wall_timeout_seconds if wall_timeout_seconds != 0 else None
            with open(result_file, "a") as out:
                with subprocess.Popen(
                    cmd, cwd=cwd, stdout=out, stderr=subprocess.STDOUT, env=env,
                    start_new_session=True,
                ) as proc:
                    try:
                        proc.wait(timeout=effective_timeout)
                    except subprocess.TimeoutExpired:
                        try:
                            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        proc.wait()
                        out.flush()
                        out.write(json.dumps({"type": "system", "subtype": "wall_timeout", "wall_seconds": wall_timeout_seconds}) + "\n")
                        logging.warning("wall_timeout: agent killed after %ds", wall_timeout_seconds)
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

DEFAULT_CODEX_MODEL = "gpt-5.5"


class CodexRunner(AgentRunner):
    """Runs OpenAI Codex CLI (the ``codex`` binary).

    ``model`` pins the underlying ChatGPT model for reproducibility. The value
    is written into ``config.toml`` *and* passed as ``codex exec -m <model>``
    (belt-and-braces — the CLI flag wins on conflict, but having both means a
    config-write bug cannot silently drop the pin). The same value is recorded
    in the JSONL ``meta`` line by ``run.py``, then read back by
    ``extract_metadata`` to look up prices in ``codex_prices.toml``.
    """

    surface = "codex_cli"

    def __init__(self, model: str = DEFAULT_CODEX_MODEL) -> None:
        self.model = model

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
        # Store the arm so invoke() can pass it to _make_isolated_config without
        # changing the AgentRunner ABC interface.
        self._arm = arm
        return []

    def _make_isolated_config(
        self,
        mcp_config_path: str | None = None,
        cwd: str = ".",
        arm: str = "baseline",
        isolation_nonce: str | None = None,
    ) -> str:
        """Create an isolated CODEX_HOME directory for a single run.

        Private helper of ``invoke()``. Copies ``~/.codex/auth.json`` into
        a fresh temp dir and writes ``config.toml``. Re-runs the auth check
        as defense-in-depth; preflight callers should use ``verify_auth()``
        instead, which has no side effects.

        ``arm`` controls whether extra tool-restriction knobs are written into
        config.toml (for ``onlycode``/``code_only`` arms).

        ``isolation_nonce`` — when set, an additional MCP stub server block is
        written so codex serialises a per-task-unique tool into the outbound
        ``tools[]`` array, forcing OpenAI's prompt cache to miss across tasks
        (issue #294).

        Returns the path to the isolated config directory; ``invoke()`` is
        responsible for ``shutil.rmtree``.
        """
        self.verify_auth()
        src = os.path.expanduser("~/.codex/auth.json")

        # CODEX_HOME must NOT be under /tmp: codex refuses to install plugin
        # helper binaries to a $TMPDIR path ("Refusing to create helper
        # binaries under temporary dir"), then later dies with "No such file
        # or directory (os error 2)" when arms that exercise apps=true
        # (tool_rich, bash_only) try to spawn the missing helper. At
        # parallel=1 the race is often invisible; at parallel>=2 the failures
        # become consistent. Stage per-invocation CODEX_HOMEs under
        # ~/.cache/onlycodes-codex-home/ instead.
        codex_home_root = os.path.expanduser("~/.cache/onlycodes-codex-home")
        os.makedirs(codex_home_root, exist_ok=True)
        cfg_dir = tempfile.mkdtemp(prefix="codex-eval-", dir=codex_home_root)
        shutil.copy2(src, cfg_dir)

        # Cache-stabilization: symlink the per-task CODEX_HOME's skills dir
        # to a single shared location so the SKILL.md paths Codex injects
        # into the developer message stay byte-stable across tasks. Without
        # this, each task's prompt prefix differs and OpenAI's prompt cache
        # misses repeatedly. (See _ensure_codex_cache_dirs docstring.)
        _ensure_codex_cache_dirs()
        try:
            os.symlink(CODEX_SHARED_SKILLS_DIR, os.path.join(cfg_dir, "skills"))
        except FileExistsError:
            pass

        # Only resolve the exec-server bundle for arms that actually register
        # the codebox MCP server. tool_rich/bash_only run on Codex's native
        # tool surface and don't need the bundle to exist.
        if _arm_uses_codebox(arm):
            bundle_path = self._resolve_bundle(mcp_config_path)
        else:
            bundle_path = ""
        persistent = os.environ.get("ONLYCODES_PERSISTENT_KERNEL", "0")
        iso_server_path = _resolve_iso_nonce_server() if isolation_nonce else None
        _write_codex_config(
            cfg_dir,
            bundle_path,
            cwd,
            persistent,
            arm=arm,
            model=self.model,
            isolation_nonce=isolation_nonce,
            iso_server_path=iso_server_path,
        )

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
        wall_timeout_seconds: int = 3600,
        isolation_nonce: str | None = None,
    ) -> None:
        """Run codex exec with an isolated CODEX_HOME containing auth + MCP config."""
        arm = getattr(self, "_arm", "baseline")
        cfg_dir = self._make_isolated_config(
            mcp_config_path=mcp_config_path,
            cwd=cwd,
            arm=arm,
            isolation_nonce=isolation_nonce,
        )
        # Codex does not expose a feature flag to disable the structured
        # apply_patch tool. For arms that must mirror Claude's strict
        # restrictions, prepend a directive instructing the model to ignore it.
        # Soft enforcement only — model compliance is not guaranteed.
        effective_prompt = _apply_arm_directive(prompt, arm)

        # Cache-stabilization: arms that can run with a constant process cwd
        # use CODEX_STABLE_CWD so that the <environment_context><cwd> codex
        # injects into the prompt stays byte-stable across tasks. Other arms
        # (native shell-based) must keep their per-task cwd so the agent's
        # `pwd` matches the repo.
        if _arm_uses_stable_process_cwd(arm):
            _ensure_codex_cache_dirs()
            effective_cwd = CODEX_STABLE_CWD
        else:
            effective_cwd = cwd
        try:
            cmd = [
                binary, "exec",
                # --ephemeral REMOVED 2026-05-27: it suppresses rollout files
                # at $CODEX_HOME/sessions/YYYY/MM/DD/rollout-*.jsonl, which
                # are our only source of per-API-call usage data (token_count
                # events with last_token_usage) when not using a proxy.
                # Each codex exec is still independent (fresh thread/session
                # per invocation), so no cross-task state leakage. The
                # rollout is just a per-session log under CODEX_HOME (which
                # the harness sets to a fresh mkdtemp dir per invocation
                # — so rollouts live IN the per-invocation temp dir and get
                # deleted when it's cleaned up, unless captured first).
                "--dangerously-bypass-approvals-and-sandbox",
                "--json",
                "-m", self.model,
                "-C", effective_cwd,
                effective_prompt,
            ]
            env = os.environ.copy()
            env["CODEX_HOME"] = cfg_dir
            if isolation_nonce:
                # Required by the iso_nonce_server.mjs stub: the server reads
                # the nonce from this env var to embed it into the tool name
                # and description that codex serialises into the tools[] array.
                env["ONLYCODES_ISOLATION_NONCE"] = isolation_nonce
            effective_timeout = wall_timeout_seconds if wall_timeout_seconds != 0 else None
            with open(result_file, "a") as out:
                with subprocess.Popen(
                    cmd, cwd=effective_cwd, stdout=out, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL, env=env,
                    start_new_session=True,
                ) as proc:
                    try:
                        proc.wait(timeout=effective_timeout)
                    except subprocess.TimeoutExpired:
                        try:
                            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        proc.wait()
                        out.flush()
                        out.write(json.dumps({"type": "system", "subtype": "wall_timeout", "wall_seconds": wall_timeout_seconds}) + "\n")
                        logging.warning("wall_timeout: agent killed after %ds", wall_timeout_seconds)
        finally:
            # Preserve rollout files (per-API-call usage data) before nuking
            # the per-invocation CODEX_HOME. The rollout lives at
            # $CODEX_HOME/sessions/YYYY/MM/DD/rollout-*.jsonl and contains
            # token_count event_msg records with `info.last_token_usage`
            # (per-call) and `info.total_token_usage` (cumulative). We copy
            # it next to result_file as <result_file>.rollout.jsonl.
            try:
                import glob as _glob
                rollouts = _glob.glob(os.path.join(cfg_dir, "sessions", "*", "*", "*", "rollout-*.jsonl"))
                if rollouts:
                    # Take the most recent (should be exactly one per invocation)
                    rollouts.sort(key=os.path.getmtime)
                    target = result_file + ".rollout.jsonl"
                    shutil.copy2(rollouts[-1], target)
            except Exception as _e:
                logging.warning("failed to preserve codex rollout: %s", _e)
            if os.environ.get("ONLYCODES_KEEP_CFG_DIR") != "1":
                shutil.rmtree(cfg_dir, ignore_errors=True)

    def extract_metadata(self, jsonl_path: Path) -> tuple[float | None, int | None]:
        """Return ``(cost_usd, num_turns)`` for a Codex JSONL log.

        ``cost_usd`` is an **estimate** derived from ``turn.completed.usage``
        token counts and a price table in ``codex_prices.toml``. ChatGPT Pro
        sessions never emit a true USD cost, so this is the best we can do.

        Degrades gracefully — returns ``cost=None`` when:
        - the file cannot be read
        - the JSONL contains no ``meta`` line with a ``model`` field
        - the ``model`` is not in the price table
        - no ``turn.completed`` line carries a usage block

        Cost formula (Responses-API convention — see issue #253 investigation
        comment): ``output_tokens`` already includes ``reasoning_output_tokens``,
        and ``input_tokens`` already includes ``cached_input_tokens``::

            non_cached_input = input_tokens - cached_input_tokens
            cost = (non_cached_input * price.input
                  + cached_input_tokens * price.cached_input
                  + output_tokens * price.output) / 1_000_000
        """
        try:
            content = jsonl_path.read_text()
        except OSError:
            return (None, None)

        lines = content.splitlines()
        turns = sum(1 for line in lines if _safe_json_type(line) == "turn.started")
        turns_val = turns if turns > 0 else None

        # Read the model name from the `meta` JSONL record written by run.py.
        model = _read_meta_model(lines)
        if model is None:
            return (None, turns_val)

        prices = _load_codex_prices().get(model)
        if prices is None:
            return (None, turns_val)

        # Sum usage across all turn.completed events (a run can have many).
        total_input = 0
        total_cached = 0
        total_output = 0
        saw_usage = False
        for line in lines:
            try:
                obj = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if obj.get("type") != "turn.completed":
                continue
            usage = obj.get("usage")
            if not isinstance(usage, dict):
                continue
            # Only count this turn if the usage dict carries at least one
            # known token field. An empty dict — or a turn.completed without
            # a usage key — is treated as missing data, not zero usage.
            if not any(k in usage for k in ("input_tokens", "output_tokens", "cached_input_tokens")):
                continue
            saw_usage = True
            total_input += int(usage.get("input_tokens", 0) or 0)
            total_cached += int(usage.get("cached_input_tokens", 0) or 0)
            total_output += int(usage.get("output_tokens", 0) or 0)

        if not saw_usage:
            return (None, turns_val)

        # Defensive: cached_input may exceed input if the JSONL is malformed —
        # clamp to keep the non-cached term non-negative.
        non_cached_input = max(0, total_input - total_cached)
        cost = (
            non_cached_input * prices["input"]
            + total_cached * prices["cached_input"]
            + total_output * prices["output"]
        ) / 1_000_000.0
        return (cost, turns_val)

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
# Cache-prefix stabilization (Codex)
# ---------------------------------------------------------------------------
#
# Codex injects three pieces of per-task variance into the prompt prefix that
# break OpenAI's automatic prompt caching:
#
#   1. ``<environment_context><cwd>...`` — the codex process cwd, which
#      changes per task when subprocess.Popen(cwd=scratch_dir) varies.
#   2. ``<skills_instructions>`` — absolute SKILL.md paths under
#      ``$CODEX_HOME/skills/.system/``; CODEX_HOME is a fresh mkdtemp per
#      task, so the paths change every task.
#   3. ``tools[]`` array contents — Codex's curated-plugin sync races with
#      the first API call; about 4% of runs drop ``request_plugin_install``
#      from the advertised tools array. OpenAI treats ``instructions + tools``
#      as a combined cache key, so a one-tool delta misses cache entirely
#      (``cached_input_tokens = 0``). See issue #292.
#
# We stabilize all three by:
#   - Pointing Codex's process cwd at a single shared dir (only for arms
#     where the agent does NOT rely on starting in the task workspace).
#   - Symlinking each per-task ``CODEX_HOME/skills`` to one shared directory,
#     so the SKILL.md paths in the developer message stay byte-stable across
#     tasks (all arms benefit; no semantic change).
#   - For ``code_only`` / ``onlycode`` arms only: setting ``apps = false``
#     in the features block. This removes ``request_plugin_install`` from
#     the tools array deterministically (the tool is irrelevant to the
#     codebox-only arm anyway), eliminating the race condition.
#
# Verified empirically on a real artifact task (5 runs each):
#   without fix (cwd + skills only):
#                                mean cache_rate=77%, median uncached=27,175
#   with fix (cwd + skills):     mean cache_rate=89%, median uncached= 8,212
#                                                                      (−70%)
#   apps=false fix verified separately via local-proxy capture:
#     baseline 10 runs:  2/10 missed RPI (20% race rate)
#     apps=false 8 runs: 0/8  missed RPI, single tool_hash across all calls

CODEX_SHARED_SKILLS_DIR = "/tmp/onlycodes_codex_shared_skills"
CODEX_STABLE_CWD = "/tmp/onlycodes_codex_stable_cwd"


def _ensure_codex_cache_dirs() -> None:
    """Ensure the shared dirs used by the prompt-cache stabilization exist.

    Both dirs are read-only from Codex's view (skills are pre-staged on first
    Codex invocation; the stable cwd just needs to exist so Codex can chdir
    into it). Safe to call concurrently from multiple harness workers.
    """
    os.makedirs(CODEX_SHARED_SKILLS_DIR, exist_ok=True)
    os.makedirs(CODEX_STABLE_CWD, exist_ok=True)


def _arm_uses_stable_process_cwd(arm: str) -> bool:
    """Whether ``arm`` can safely run with codex's process cwd held constant.

    - code_only / onlycode: YES. The codebox MCP server is configured with the
      per-task workspace cwd, so the agent's tool calls land in the right
      place regardless of codex's own process cwd. The artifact / SWE-bench
      prompts already supply absolute paths to the workspace.
    - tool_rich / baseline / bash_only: NO. These arms use codex's native
      shell, which inherits codex's process cwd. SWE-bench agents expect
      ``pwd`` to be the repo dir.
    """
    return arm in ("onlycode", "code_only")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _toml_str(s: str) -> str:
    """Escape a string for use in a TOML basic string (double-quoted value).

    Escapes backslashes first, then double-quote characters, so the result
    can be safely embedded between ``"..."`` in a TOML document.
    """
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _arm_uses_codebox(arm: str) -> bool:
    """Whether ``arm`` should have the codebox MCP server registered in config.toml.

    Only the code-only arms route through codebox; tool_rich/baseline use Codex's
    native shell + apply_patch surface, and bash_only uses native shell alone.
    """
    return arm in ("onlycode", "code_only")


_CODE_ONLY_DIRECTIVE = (
    "[TOOL RESTRICTION] You may only use the `codebox` MCP server's "
    "`execute_code` tool. Do NOT call `apply_patch`, `shell`, or any other "
    "tool. All file reads, file writes, and shell commands must be performed "
    "by running code through `execute_code`.\n\n"
    "[LANGUAGE GUIDANCE] Prefer `language: \"python\"` for the main "
    "computational work — parsing, analysis, file writes, verification — "
    "because it runs in a persistent REPL keyed by cwd, so imports and "
    "loaded data carry across calls. Use `language: \"bash\"` for quick "
    "file inspection or shell utilities (`ls`, `head`, `grep`) where state "
    "isn't useful.\n\n"
)

_BASH_ONLY_DIRECTIVE = (
    "[TOOL RESTRICTION] You may only use the shell tool. Do NOT call "
    "`apply_patch` or any MCP tool. All file reads, file writes, and "
    "computations must be performed via shell commands.\n\n"
)


def _apply_arm_directive(prompt: str, arm: str) -> str:
    """Prepend an arm-specific tool-restriction directive to the user prompt.

    Codex exposes no feature flag for disabling the structured ``apply_patch``
    tool, so the only mechanism to keep ``code_only`` and ``bash_only`` aligned
    with their ClaudeRunner counterparts is to instruct the model directly in
    the prompt. This is soft enforcement; agent compliance is not guaranteed.

    Returns ``prompt`` unchanged for ``tool_rich``/``baseline``.
    """
    if arm in ("onlycode", "code_only"):
        return _CODE_ONLY_DIRECTIVE + prompt
    if arm == "bash_only":
        return _BASH_ONLY_DIRECTIVE + prompt
    return prompt


def _write_claude_iso_mcp_config(
    base_config_path: str | None,
    iso_server_path: str,
    nonce: str,
    out_dir: str,
) -> str:
    """Write a Claude mcp-config.json containing the iso_nonce stub server (#296).

    If ``base_config_path`` is given and readable, its existing ``mcpServers``
    entries are preserved so the codebox / other servers stay available for
    ``code_only`` / ``onlycode`` arms. For arms that pass no base config
    (``tool_rich`` / ``baseline`` / ``bash_only``), the output contains only
    the iso server.

    Returns the path to the new file inside ``out_dir`` — the caller's
    per-invocation temp dir, cleaned up alongside the rest of the run.
    """
    if base_config_path and Path(base_config_path).is_file():
        base = json.loads(Path(base_config_path).read_text())
    else:
        base = {}
    base.setdefault("mcpServers", {})
    base["mcpServers"]["iso_nonce"] = {
        "command": "node",
        "args": [iso_server_path],
        "env": {"ONLYCODES_ISOLATION_NONCE": nonce},
    }
    out_path = Path(out_dir) / "mcp-config-iso.json"
    out_path.write_text(json.dumps(base))
    return str(out_path)


def _splice_iso_into_claude_flags(
    flags: list[str], merged_mcp_config: str, iso_tool: str
) -> list[str]:
    """Return ``flags`` with the iso MCP config and disallowed-tool spliced in.

    - If ``--mcp-config`` is already present, its value is replaced with the
      merged config path (preserves ``--strict-mcp-config`` if also present).
    - Otherwise ``--mcp-config <merged> --strict-mcp-config`` is appended.
    - If ``--disallowedTools`` is present, its comma-separated value is
      extended with ``iso_tool``; otherwise the flag pair is appended.

    Returns a new list; the input is not mutated.
    """
    out = list(flags)
    if "--mcp-config" in out:
        idx = out.index("--mcp-config")
        out[idx + 1] = merged_mcp_config
    else:
        out += ["--mcp-config", merged_mcp_config, "--strict-mcp-config"]
    if "--disallowedTools" in out:
        idx = out.index("--disallowedTools")
        out[idx + 1] = f"{out[idx + 1]},{iso_tool}"
    else:
        out += ["--disallowedTools", iso_tool]
    return out


def _resolve_iso_nonce_server() -> str:
    """Return the absolute path to the iso_nonce stub MCP server script.

    Located next to the exec-server JS source so the existing
    ``@modelcontextprotocol/sdk`` dependency suffices. The file is checked in;
    if it is missing this is a packaging bug, surfaced as ``FileNotFoundError``.
    """
    candidate = (
        Path(__file__).parent.parent
        / "exec_server"
        / "iso_nonce_server.mjs"
    )
    if not candidate.is_file():
        raise FileNotFoundError(
            f"iso_nonce_server.mjs not found at {candidate}. "
            "Cache-isolation requires this stub MCP server."
        )
    return str(candidate)


def _write_codex_config(
    cfg_dir: str,
    bundle_path: str,
    cwd: str,
    persistent_kernel: str,
    arm: str = "baseline",
    model: str = DEFAULT_CODEX_MODEL,
    isolation_nonce: str | None = None,
    iso_server_path: str | None = None,
    mcp_command: str = "node",
    mcp_env_extra: dict[str, str] | None = None,
) -> None:
    """Write config.toml into cfg_dir for a Codex run.

    Avoids an external TOML library by rendering the known-shape config
    as a string directly.

    ``arm`` selects one of three tool-surface profiles, designed to mirror
    the corresponding ClaudeRunner arms:

    - ``tool_rich`` / ``baseline``: native Codex tool surface — ``shell_tool``
      and ``apply_patch_freeform`` are both enabled, no codebox MCP server is
      registered. Mirrors Claude's full built-in toolset (Read/Edit/Write/Bash).
    - ``code_only`` / ``onlycode``: codebox MCP is the only permitted tool.
      ``shell_tool = false``, ``apply_patch_freeform = false``,
      ``browser_use = false``, ``computer_use = false``. Mirrors Claude's
      ``mcp__codebox__execute_code``-only configuration.
    - ``bash_only``: native shell only — ``shell_tool = true``, no codebox MCP,
      no ``apply_patch_freeform``, ``browser_use = false``, ``computer_use = false``.
      Mirrors Claude's Bash-only configuration.

    The structured ``apply_patch`` tool has no Codex feature flag and remains
    available in every arm. ``CodexRunner.invoke`` prepends a soft directive
    to the prompt for ``code_only`` and ``bash_only`` to discourage its use.

    ``model`` pins the underlying ChatGPT model at the top of config.toml so
    runs are reproducible across CLI upgrades — Codex would otherwise silently
    fall back to its compiled-in default. This is belt-and-braces with the
    ``codex exec -m <model>`` CLI flag (which takes precedence on conflict).

    ``web_search = "disabled"`` is set in every arm to prevent uncontrolled
    external requests that would pollute benchmark measurements. Note this is
    a deliberate divergence from Claude ``tool_rich`` (which permits WebSearch);
    in practice the artifact tasks do not require web access.
    """
    # ``apps = false`` is set on ALL codex arms (2026-05-27): the curated-
    # plugin loader (apps=true) races at parallel>=4 — codex tries to install
    # plugin helper binaries from a shared global store and dies with
    # "Error: No such file or directory (os error 2)" on the loser of the
    # race. At parallel=6 this kills ~100% of tool_rich/bash_only invocations
    # (verified empirically: 41/41 fail). apps=false skips the plugin loader
    # entirely and is harmless — tool_rich/bash_only still have shell_tool
    # and apply_patch_freeform, which is the surface area we measure. As a
    # bonus, it stabilises the tools[] payload byte-signature across tasks,
    # which #292 documented as a separate cache-stability fix.
    if arm in ("onlycode", "code_only"):
        shell_tool = "false"
        apply_patch_freeform = "false"
        extra_features = "browser_use = false\ncomputer_use = false\napps = false\n"
    elif arm == "bash_only":
        shell_tool = "true"
        apply_patch_freeform = "false"
        extra_features = "browser_use = false\ncomputer_use = false\napps = false\n"
    else:  # tool_rich, baseline, and any unknown arm (rejected upstream)
        shell_tool = "true"
        apply_patch_freeform = "true"
        extra_features = "browser_use = false\ncomputer_use = false\napps = false\n"

    toml = (
        f'model = "{_toml_str(model)}"\n'
        'web_search = "disabled"\n'
        "\n"
        "[features]\n"
        f"shell_tool = {shell_tool}\n"
        f"apply_patch_freeform = {apply_patch_freeform}\n"
        + extra_features
    )

    if _arm_uses_codebox(arm):
        # mcp_command/mcp_env_extra let the in-container image path (#325) point
        # the codebox server at the staged node binary and inject the testbed
        # PATH so the kernel uses the project conda env. Host path keeps the
        # defaults ("node" on PATH, no extra env).
        env_lines = f'ONLYCODES_PERSISTENT_KERNEL = "{_toml_str(persistent_kernel)}"\n'
        for k, v in (mcp_env_extra or {}).items():
            env_lines += f'{k} = "{_toml_str(v)}"\n'
        toml += (
            "\n"
            "[mcp_servers.codebox]\n"
            f'command = "{_toml_str(mcp_command)}"\n'
            f'args = ["{_toml_str(bundle_path)}"]\n'
            "\n"
            "[mcp_servers.codebox.env]\n"
            + env_lines +
            "\n"
            "[mcp_servers.codebox.options]\n"
            'enabled_tools = ["execute_code", "execute_code_and_wait"]\n'
            "startup_timeout_sec = 30.0\n"
            f'cwd = "{_toml_str(cwd)}"\n'
        )

    # Per-task prompt-cache isolation (#294). When enabled, register a stub
    # MCP server that exposes one tool whose name and description embed the
    # nonce. Codex serialises this tool into the outbound Responses-API
    # ``tools[]`` array, so the cache key (instructions + tools) byte-differs
    # per task and OpenAI's prompt cache cannot serve cross-task hits.
    #
    # ⚠ INSUFFICIENT IN PRACTICE (2026-05-26): the tools[] injection
    # succeeds as designed, but OpenAI's Responses-API caching documents
    # no parameter that scopes or disables the prompt cache. The
    # ``prompt_cache_key`` parameter is a partition/routing hint, not a
    # disable switch and not a security boundary. Other prefix bytes
    # (system instructions, cwd, skills/plugins paths, model-side
    # automatic state) can still produce cross-task cache hits independent
    # of the tools[] payload — see the cwd / skills-symlink / apps=false
    # cache-stabilisation fixes that landed under #292 to recover the
    # 4 zero-cache outliers in the seed-1 artifact backup. Treat this
    # mechanism as one of several required components, not a complete
    # solution; do not interpret presence of the nonce as evidence of
    # cold cache.
    if isolation_nonce and iso_server_path:
        toml += (
            "\n"
            "[mcp_servers.iso_nonce]\n"
            'command = "node"\n'
            f'args = ["{_toml_str(iso_server_path)}"]\n'
            "\n"
            "[mcp_servers.iso_nonce.env]\n"
            f'ONLYCODES_ISOLATION_NONCE = "{_toml_str(isolation_nonce)}"\n'
            "\n"
            "[mcp_servers.iso_nonce.options]\n"
            f'enabled_tools = ["iso_nonce_{_toml_str(isolation_nonce)}"]\n'
            "startup_timeout_sec = 30.0\n"
        )

    with open(os.path.join(cfg_dir, "config.toml"), "w") as f:
        f.write(toml)


def _read_meta_model(lines: list[str]) -> str | None:
    """Return the ``model`` field from the first ``type: meta`` JSONL record.

    Returns ``None`` if no meta line exists, the meta line has no ``model``
    field, or all candidates are malformed. Defensive by design — a missing
    or broken meta line must not raise, only degrade ``cost`` to ``None``.
    """
    for line in lines:
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(obj, dict) and obj.get("type") == "meta":
            model = obj.get("model")
            if isinstance(model, str) and model:
                return model
            return None  # meta found but no usable model field
    return None


# Cache of the parsed codex_prices.toml. Reloaded on each call so a manual edit
# during a long-running multi-arm session takes effect without a restart; the
# cost is one file read per result file, which is negligible.
def _load_codex_prices() -> dict[str, dict[str, float]]:
    """Load the Codex CLI price table.

    Returns a mapping ``{model_slug: {"input": .., "cached_input": .., "output": ..}}``.
    Returns ``{}`` if the file is missing or unparseable (so unknown-model fallthrough
    to ``cost=None`` is the only consequence).
    """
    try:
        import tomllib
    except ModuleNotFoundError:
        try:
            import tomli as tomllib  # type: ignore[import-not-found]
        except ModuleNotFoundError:
            return {}

    path = Path(__file__).parent / "codex_prices.toml"
    if not path.is_file():
        return {}

    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except (OSError, ValueError):
        return {}

    # Each table is keyed by an arbitrary section name; the canonical model
    # slug is the ``model`` field inside the section. This avoids TOML key
    # quoting issues for names like ``gpt-5.5``.
    out: dict[str, dict[str, float]] = {}
    for section in data.values():
        if not isinstance(section, dict):
            continue
        name = section.get("model")
        if not isinstance(name, str):
            continue
        try:
            out[name] = {
                "input": float(section["input"]),
                "cached_input": float(section["cached_input"]),
                "output": float(section["output"]),
            }
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _safe_json_type(line: str) -> str | None:
    """Parse a JSONL line and return its 'type' field, or None on error."""
    try:
        return json.loads(line).get("type")
    except (json.JSONDecodeError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def make_runner(surface: str, *, codex_model: str = DEFAULT_CODEX_MODEL) -> AgentRunner:
    """Return an AgentRunner for the given surface name.

    ``codex_model`` is only consulted when ``surface == "codex_cli"``. It is
    threaded down into ``CodexRunner.__init__`` so the pin is applied to both
    ``config.toml`` and the ``codex exec -m`` CLI flag.
    """
    if surface == "claude_code":
        return ClaudeRunner()
    if surface == "codex_cli":
        return CodexRunner(model=codex_model)
    raise ValueError(
        f"Unknown agent surface: {surface!r}. "
        f"Valid values: 'claude_code', 'codex_cli'."
    )
