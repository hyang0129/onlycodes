"""In-container Claude agent execution (epic #314 / ADR-0004, C4 #318).

Runs the **Claude** agent *inside* a prepared instance container (C3
:mod:`swebench.container`), for both arms, with the same tool-restriction and
isolation guarantees as the host path — only relocated into the container.

Staging strategy (de-risked in the C4 spike):

* **Shared read-only runtime volume** ``onlycodes-agent-rt`` holds the big,
  instance-independent binaries — the host's ``node`` and the Claude native
  binary — populated **once** (~12 s) and mounted ``:ro`` at ``/opt/agent`` in
  every arm container.  Named volumes live in the daemon, so they sidestep the
  DooD "bind-mount source resolves on the host" problem (C2).  The base SWE-bench
  images ship **no node** (contrary to #318's premise — verified absent), hence
  node is staged here too.
* **Per-arm writable config** ``/opt/cfg`` holds the small bits: the exec-server
  bundle + python helpers (~0.8 MB — staged per arm rather than on the ro volume
  so the server never assumes its own dir is writable), a rewritten
  ``mcp-config.json`` pointing at the staged node/bundle, and the **credentials**.
* **Agent user** (non-root — Claude refuses ``--dangerously-skip-permissions``
  as uid 0) and ``chown /testbed`` are baked into the snapshot at *prepare* time
  (see :func:`agent_user_setup_commands`), so no per-arm ``chown -R``.

**Credentials never persist in an image/commit:** the snapshot is committed at
prepare time, before any creds exist; creds are ``docker cp``'d only into
ephemeral arm containers, which are ``docker rm``'d and never committed.

The **executed-code network isolation** (`unshare -n`, hard-required in the
exec-server) needs only ``CAP_SYS_ADMIN``, which :mod:`swebench.container`
already grants — C2 confirmed both unshare strategies work in-container.  The
agent process keeps API network; only *executed code* is isolated.

Tool-restriction logic is **not** duplicated here — :func:`run_agent` calls
``ClaudeRunner.build_tools_flags`` so the ``--tools`` / ``--disallowedTools``
contract stays single-sourced with the host path.

Scope (C4): the agent runs correctly in-container.  Getting the transcript +
result *out* with a no-leak scan is C4b (#324); the Codex surface is #325.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path

from swebench import container
from swebench.container import ContainerHandle
from swebench.runner import ClaudeRunner, DEFAULT_CODEX_MODEL, _apply_arm_directive, _write_codex_config


# --------------------------------------------------------------------------
# Layout constants
# --------------------------------------------------------------------------

RUNTIME_VOLUME = "onlycodes-agent-rt"   # shared, read-only
AGENT_MOUNT = "/opt/agent"              # where the volume mounts (node, claude)
CFG_DIR = "/opt/cfg"                    # per-arm, writable (exec-server, mcp-config, creds)
AGENT_USER = "agent"
AGENT_UID = 4000
AGENT_HOME = f"/home/{AGENT_USER}"

NODE_BIN = f"{AGENT_MOUNT}/node"
CLAUDE_BIN = f"{AGENT_MOUNT}/claude"
BUNDLE_IN_CFG = f"{CFG_DIR}/exec_server/exec-server.bundle.mjs"
MCP_CONFIG_IN_CFG = f"{CFG_DIR}/mcp-config.json"
RESULT_IN_CONTAINER = f"{CFG_DIR}/transcript.jsonl"

#: Pinned model — mirrors ``ClaudeRunner.invoke`` on the host path.
MODEL = "claude-sonnet-4-6"
#: Codex default model (mirrors ``runner.DEFAULT_CODEX_MODEL``).
CODEX_MODEL = DEFAULT_CODEX_MODEL

#: The SWE-bench image's project conda env (repo installed editable here).
TESTBED_ENV = "/opt/miniconda3/envs/testbed"

#: PATH for the in-container codebox kernel — testbed conda env first so executed
#: code imports the package under test (shared by the Claude mcp-config and the
#: Codex config.toml MCP env).
_TESTBED_PATH = (
    f"{TESTBED_ENV}/bin:/opt/miniconda3/bin:"
    "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
)

# --- Codex surface (#325): native static-musl binary staged in the RO volume ---
CODEX_VENDOR_DIR = f"{AGENT_MOUNT}/codex"          # vendor dir on the runtime volume
CODEX_BIN = f"{CODEX_VENDOR_DIR}/bin/codex"        # native binary (no node needed for codex itself)
CODEX_PATH_DIR = f"{CODEX_VENDOR_DIR}/codex-path"  # bundled rg etc. — must be on PATH
CODEX_HOME_IN_CFG = f"{CFG_DIR}/codex_home"        # per-arm CODEX_HOME (auth.json + config.toml)
#: The platform triple whose vendor dir we stage (x86_64 images).
_CODEX_TARGET = "x86_64-unknown-linux-musl"

#: MCP init timeout (ms).  The exec-server's persistent python kernel cold-starts
#: slower under the in-container conda env than Claude Code's default MCP timeout,
#: which leaves the codebox server stuck ``status:pending`` (init record
#: ``tools:[]``).  A generous timeout absorbs the cold-start variance (warm
#: ~6 s; a truly cold conda import can exceed 60 s).  Note the init record's
#: ``mcp_servers`` status is only a snapshot at emit time — it may read
#: ``pending`` even when the server connects microseconds later and the tool
#: works, so don't treat it as the readiness signal (the tool_result is).
MCP_TIMEOUT_MS = 120000

#: Sentinel inside the volume marking a complete population.
_VOLUME_SENTINEL = f"{AGENT_MOUNT}/.populated"

#: exec-server runtime files staged per-arm (alongside the bundle, read via
#: ``__dirname``).  Sourced from the built ``exec_server/dist/``.
_EXEC_SERVER_FILES = (
    "exec-server.bundle.mjs",
    "codebox.py",
    "mcp_bridge.py",
    "python_kernel.py",
    "passthrough-config.json",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _exec_server_dist() -> Path:
    return _repo_root() / "exec_server" / "dist"


class AgentRuntimeError(RuntimeError):
    """Agent runtime staging or invocation failed."""


# --------------------------------------------------------------------------
# Snapshot-time setup (baked in by container.prepare_instance(post_strip_exec=))
# --------------------------------------------------------------------------

def agent_user_setup_commands(
    testbed: str = "/testbed", *, uid: int = AGENT_UID
) -> list[list[str]]:
    """argv lists for :func:`container.prepare_instance`'s ``post_strip_exec``.

    Creates the non-root agent user and chowns ``/testbed`` to it — baked into
    the snapshot once, so per-arm starts pay no ``chown -R``.  Secret-free, as
    required for anything committed into the image.
    """
    return [
        ["bash", "-c",
         f"id {AGENT_USER} >/dev/null 2>&1 || useradd -m -u {uid} {AGENT_USER}"],
        ["chown", "-R", f"{AGENT_USER}:{AGENT_USER}", testbed],
    ]


# --------------------------------------------------------------------------
# Shared read-only runtime volume (node + claude), populated once
# --------------------------------------------------------------------------

def runtime_volume_spec(*, read_only: bool = True) -> str:
    """The ``docker -v`` spec to mount the runtime volume in an arm container."""
    return f"{RUNTIME_VOLUME}:{AGENT_MOUNT}" + (":ro" if read_only else "")


def _volume_exists(name: str) -> bool:
    return container._docker(["volume", "inspect", name], check=False).returncode == 0


def _find_node() -> str:
    node = shutil.which("node")
    if not node:
        raise AgentRuntimeError(
            "host `node` not found on PATH — required to stage the exec-server "
            "runtime (base SWE-bench images ship no node)."
        )
    return node


def ensure_agent_runtime(
    claude_binary: str,
    *,
    helper_image: str = "busybox:latest",
    force: bool = False,
) -> str:
    """Create + populate the shared read-only runtime volume (node + claude).

    Idempotent: returns immediately if the volume already carries the sentinel
    (unless ``force``).  Population copies the host ``node`` and ``claude_binary``
    into the volume via a throwaway helper container — paid once globally, not
    per arm.  Returns the volume name.
    """
    if not force and _volume_exists(RUNTIME_VOLUME):
        probe = container._docker(
            ["run", "--rm", "-v", f"{RUNTIME_VOLUME}:{AGENT_MOUNT}:ro",
             helper_image, "test", "-f", _VOLUME_SENTINEL],
            check=False,
        )
        if probe.returncode == 0:
            return RUNTIME_VOLUME

    node = _find_node()
    container.pull_image(helper_image)
    container._docker(["volume", "create", RUNTIME_VOLUME], check=False)

    # Stage a host tree, then cp it into the volume in one shot (preserves the
    # executable bits on node/claude; auto-creates the dir).
    staging = tempfile.mkdtemp(prefix="agent-rt-")
    helper = ""
    try:
        shutil.copy2(node, os.path.join(staging, "node"))
        shutil.copy2(claude_binary, os.path.join(staging, "claude"))
        os.chmod(os.path.join(staging, "node"), 0o755)
        os.chmod(os.path.join(staging, "claude"), 0o755)
        Path(staging, ".populated").write_text("1\n")

        helper = container._decode(container._docker(
            ["run", "-d", "-v", f"{RUNTIME_VOLUME}:/stage", helper_image,
             "sleep", "86400"]
        ))
        # `cp <dir>/.` copies the directory *contents* into /stage.
        container._docker(["cp", f"{staging}/.", f"{helper}:/stage"])
    finally:
        if helper:
            container._rm_force(helper)
        shutil.rmtree(staging, ignore_errors=True)
    return RUNTIME_VOLUME


def _find_codex_vendor() -> str:
    """Resolve the host codex install's platform vendor dir (#325).

    ``codex`` is an npm node shim that dispatches to a static-musl native binary
    under ``@openai/codex-linux-x64/vendor/<target>``; that whole dir (binary +
    bundled ``rg``/``bwrap``) is what we stage. Returns its absolute path.
    """
    codex = shutil.which("codex")
    if not codex:
        raise AgentRuntimeError(
            "host `codex` not found on PATH — install with `npm install -g @openai/codex` "
            "(needs sudo; the global prefix is root-owned)."
        )
    # which -> .../@openai/codex/bin/codex.js ; pkg root is two dirs up.
    pkg_root = os.path.dirname(os.path.dirname(os.path.realpath(codex)))
    vendor = os.path.join(
        pkg_root, "node_modules", "@openai", "codex-linux-x64", "vendor", _CODEX_TARGET
    )
    if not os.path.isdir(vendor):
        raise AgentRuntimeError(
            f"codex platform vendor dir not found at {vendor} — reinstall codex."
        )
    return vendor


def ensure_codex_runtime(
    codex_vendor: str | None = None,
    *,
    helper_image: str = "busybox:latest",
    force: bool = False,
) -> str:
    """Populate the shared runtime volume with ``node`` + the codex vendor dir (#325).

    Idempotent on the presence of the staged codex binary (independent of the
    Claude sentinel, so both surfaces can coexist in the one volume). ``node`` is
    (re)staged too so the codebox MCP bundle works even if the Claude path never
    populated the volume. Returns the volume name.
    """
    if not force and _volume_exists(RUNTIME_VOLUME):
        probe = container._docker(
            ["run", "--rm", "-v", f"{RUNTIME_VOLUME}:{AGENT_MOUNT}:ro",
             helper_image, "test", "-f", CODEX_BIN],
            check=False,
        )
        if probe.returncode == 0:
            return RUNTIME_VOLUME

    vendor = codex_vendor or _find_codex_vendor()
    node = _find_node()
    container.pull_image(helper_image)
    container._docker(["volume", "create", RUNTIME_VOLUME], check=False)

    helper = ""
    try:
        helper = container._decode(container._docker(
            ["run", "-d", "-v", f"{RUNTIME_VOLUME}:/stage", helper_image, "sleep", "86400"]
        ))
        container._docker(["cp", node, f"{helper}:/stage/node"])
        container._docker(["exec", helper, "chmod", "0755", "/stage/node"])
        container._docker(["exec", helper, "mkdir", "-p", "/stage/codex"])
        # copy vendor *contents* into /stage/codex
        container._docker(["cp", f"{vendor}/.", f"{helper}:/stage/codex"])
        container._docker(["exec", helper, "chmod", "-R", "a+rX", "/stage/codex"])
    finally:
        if helper:
            container._rm_force(helper)
    return RUNTIME_VOLUME


# --------------------------------------------------------------------------
# Per-arm staging: exec-server bundle + mcp-config + credentials -> /opt/cfg
# --------------------------------------------------------------------------

def _incontainer_mcp_config(*, persistent_kernel: bool = True) -> dict:
    # Prepend the testbed env's bin so the exec-server's python kernel runs in the
    # *project* conda env (where the repo is installed editable) — not the base
    # env — so executed code can import the package under test.
    path = _TESTBED_PATH
    return {
        "mcpServers": {
            "codebox": {
                "type": "stdio",
                "command": NODE_BIN,
                "args": [BUNDLE_IN_CFG],
                "cwd": "/testbed",
                "env": {
                    "ONLYCODES_PERSISTENT_KERNEL": "1" if persistent_kernel else "0",
                    "PATH": path,
                },
            }
        }
    }


def _stage_exec_server(cid: str) -> None:
    """Copy the full exec-server file set into ``/opt/cfg/exec_server`` (both surfaces)."""
    dist = _exec_server_dist()
    for fname in _EXEC_SERVER_FILES:
        if not (dist / fname).is_file():
            raise AgentRuntimeError(
                f"exec-server file missing: {dist / fname} — run `npm run build` "
                "in exec_server/ first."
            )
    container._docker(["exec", cid, "mkdir", "-p", f"{CFG_DIR}/exec_server"])
    for fname in _EXEC_SERVER_FILES:
        container._docker(["cp", str(dist / fname), f"{cid}:{CFG_DIR}/exec_server/{fname}"])


def stage_arm(
    handle: ContainerHandle,
    *,
    surface: str = "claude_code",
    arm: str = "onlycode",
    model: str | None = None,
    creds_src: str | None = None,
    persistent_kernel: bool = True,
) -> None:
    """Stage the per-arm config into ``/opt/cfg`` of a running arm container.

    Surface-aware (#325): the Claude path writes ``mcp-config.json`` + Claude
    credentials; the Codex path writes a ``CODEX_HOME`` (auth.json + config.toml).
    Both stage the exec-server bundle + helpers and chown ``/opt/cfg`` to the
    agent user.  Nothing is ever committed — arm containers are torn down.
    """
    if surface == "codex_cli":
        _stage_arm_codex(handle, arm=arm, model=model, creds_src=creds_src,
                         persistent_kernel=persistent_kernel)
        return

    creds_src = creds_src or os.path.expanduser("~/.claude")
    cid = handle.container_id
    _stage_exec_server(cid)

    # In-container mcp-config.
    tmp = tempfile.mkdtemp(prefix="arm-cfg-")
    try:
        cfg_path = os.path.join(tmp, "mcp-config.json")
        Path(cfg_path).write_text(json.dumps(_incontainer_mcp_config(
            persistent_kernel=persistent_kernel)))
        container._docker(["cp", cfg_path, f"{cid}:{MCP_CONFIG_IN_CFG}"])

        # Credentials — copied last, then the whole /opt/cfg chowned to agent.
        for fname in (".credentials.json", ".claude.json"):
            src = os.path.join(creds_src, fname)
            if os.path.isfile(src):
                container._docker(["cp", src, f"{cid}:{CFG_DIR}/{fname}"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    container._docker(["exec", cid, "chown", "-R", f"{AGENT_USER}:{AGENT_USER}", CFG_DIR])


#: Minimum access-token life required at stage time. The codex auth is copied
#: into the container and discarded; if it expires mid-run codex refreshes there
#: and writes the rotated (one-time) token to the throwaway copy, leaving the host
#: token dead and breaking every subsequent run. ChatGPT access tokens last ~10
#: days, so a fresh ``codex login`` clears this by a wide margin; we just refuse
#: to start with a token that won't outlive the run.
_CODEX_TOKEN_MIN_REMAINING_SEC = 3600


def _assert_codex_token_fresh(auth_path: str, *, _now: float | None = None) -> None:
    """Raise if the codex access token is expired / expiring within the margin.

    Fails loudly so a stale token (needing an in-container refresh that would
    consume the one-time refresh token and break the rest of a sweep) surfaces as
    a clear 're-login' error instead. API-key auth (no ``tokens`` block) is
    exempt. Decoding is best-effort — an undecodable token is allowed through
    rather than blocking on a parser quirk."""
    import base64
    import time as _time
    try:
        data = json.loads(Path(auth_path).read_text())
    except (OSError, json.JSONDecodeError):
        return
    if data.get("OPENAI_API_KEY"):
        return  # API key never expires/rotates
    tok = (data.get("tokens") or {}).get("access_token")
    if not tok or tok.count(".") < 2:
        return
    try:
        payload = tok.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        exp = json.loads(base64.urlsafe_b64decode(payload)).get("exp")
    except Exception:  # noqa: BLE001 — undecodable token: don't block
        return
    if exp is None:
        return
    now = _now if _now is not None else _time.time()
    if exp <= now + _CODEX_TOKEN_MIN_REMAINING_SEC:
        raise AgentRuntimeError(
            f"codex access token at {auth_path} expires too soon "
            f"({int((exp - now) / 60)} min left) — run `codex login` to refresh. "
            "Staging a near-expiry OAuth token risks an in-container refresh that "
            "consumes the one-time refresh token and breaks subsequent runs."
        )


def _stage_arm_codex(
    handle: ContainerHandle,
    *,
    arm: str,
    model: str | None,
    creds_src: str | None,
    persistent_kernel: bool,
) -> None:
    """Codex staging: exec-server set + a ``CODEX_HOME`` (auth.json + config.toml).

    ``config.toml`` reuses ``runner._write_codex_config`` (single-sourced
    tool-restriction profile) but with in-container paths — the codebox MCP
    ``command`` is the staged node and its env carries the testbed ``PATH`` so the
    kernel runs in the project conda env.
    """
    creds_src = creds_src or os.path.expanduser("~/.codex")
    cid = handle.container_id
    _stage_exec_server(cid)
    container._docker(["exec", cid, "mkdir", "-p", CODEX_HOME_IN_CFG])

    auth = os.path.join(creds_src, "auth.json")
    if not os.path.isfile(auth):
        raise AgentRuntimeError(
            f"codex auth not found at {auth} — Codex CLI requires a valid auth token."
        )
    _assert_codex_token_fresh(auth)

    tmp = tempfile.mkdtemp(prefix="arm-codex-")
    try:
        _write_codex_config(
            tmp,
            bundle_path=BUNDLE_IN_CFG,
            cwd="/testbed",
            persistent_kernel="1" if persistent_kernel else "0",
            arm=arm,
            model=model or CODEX_MODEL,
            mcp_command=NODE_BIN,
            mcp_env_extra={"PATH": _TESTBED_PATH},
        )
        container._docker(["cp", os.path.join(tmp, "config.toml"),
                           f"{cid}:{CODEX_HOME_IN_CFG}/config.toml"])
        container._docker(["cp", auth, f"{cid}:{CODEX_HOME_IN_CFG}/auth.json"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    container._docker(["exec", cid, "chown", "-R", f"{AGENT_USER}:{AGENT_USER}", CFG_DIR])


# --------------------------------------------------------------------------
# Invocation
# --------------------------------------------------------------------------

def build_agent_argv(
    arm: str,
    *,
    prompt: str,
    system_prompt: str,
    model: str | None = None,
    wall_timeout: int = 3600,
    surface: str = "claude_code",
) -> list[str]:
    """The in-container agent argv for an arm (no docker wrapper).

    Surface-aware (#325). Claude: tool flags from ``ClaudeRunner.build_tools_flags``
    (single-sourced with the host path); only the mcp-config path is in-container.
    Codex: ``codex exec`` against the native binary (restriction lives in
    config.toml from :func:`_stage_arm_codex`). A ``timeout`` prefix bounds wall
    time *inside* the container so the agent is killed even if the host
    ``docker exec`` client is interrupted.
    """
    if surface == "codex_cli":
        return _build_codex_argv(arm, prompt=prompt, model=model or CODEX_MODEL,
                                 wall_timeout=wall_timeout)
    tools_flags = ClaudeRunner().build_tools_flags(arm, MCP_CONFIG_IN_CFG)
    argv = [
        CLAUDE_BIN,
        "-p", prompt,
        "--model", model or MODEL,
        "--system-prompt", system_prompt,
        *tools_flags,
        "--dangerously-skip-permissions",
        "--no-session-persistence",
        "--output-format", "stream-json",
        "--verbose",
    ]
    if wall_timeout and wall_timeout > 0:
        argv = ["timeout", f"{wall_timeout}s", *argv]
    return argv


def _build_codex_argv(arm: str, *, prompt: str, model: str, wall_timeout: int) -> list[str]:
    """``codex exec`` argv (native binary). Restriction is in config.toml; the soft
    arm directive is prepended to the prompt (codex can't hard-disable apply_patch)."""
    effective_prompt = _apply_arm_directive(prompt, arm)
    argv = [
        CODEX_BIN, "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "--json",
        "-m", model,
        "-C", "/testbed",
        effective_prompt,
    ]
    if wall_timeout and wall_timeout > 0:
        argv = ["timeout", f"{wall_timeout}s", *argv]
    return argv


#: Arms whose only tools are the codebox MCP — a turn with zero ``mcp__codebox__``
#: use means the MCP server never connected (the agent had no tools), not that
#: the task needed none.
_MCP_REQUIRED_ARMS = {"code_only", "onlycode"}


def _codebox_was_used(result_path: str) -> bool:
    try:
        text = Path(result_path).read_text()
    except OSError:
        return False
    # Claude stream-json names the tool ``mcp__codebox__*``; Codex ``--json``
    # emits ``mcp_tool_call`` items with ``"server":"codebox"``. Match either.
    return "mcp__codebox__" in text or '"server":"codebox"' in text or '"server": "codebox"' in text


def _invoke_once(
    handle: ContainerHandle, agent_argv: list[str], result_path: str,
    host_timeout: int | None, *, surface: str = "claude_code",
) -> int:
    if surface == "codex_cli":
        env_flags = [
            "-e", f"CODEX_HOME={CODEX_HOME_IN_CFG}",
            "-e", f"HOME={AGENT_HOME}",
            # codex-path (rg) + staged node (codebox MCP) + testbed env on PATH.
            "-e", f"PATH={CODEX_PATH_DIR}:{AGENT_MOUNT}:{_TESTBED_PATH}",
        ]
    else:
        env_flags = [
            "-e", f"CLAUDE_CONFIG_DIR={CFG_DIR}",
            "-e", f"HOME={AGENT_HOME}",
            "-e", "FORCE_PROMPT_CACHING_5M=1",
            "-e", f"MCP_TIMEOUT={MCP_TIMEOUT_MS}",
        ]
    docker_argv = [
        container._docker_bin(), "exec",
        "-u", AGENT_USER,
        "-w", "/testbed",
        *env_flags,
        handle.container_id,
        *agent_argv,
    ]
    with open(result_path, "wb") as out:
        with subprocess.Popen(
            docker_argv, stdout=out, stderr=subprocess.STDOUT, start_new_session=True,
        ) as proc:
            try:
                return proc.wait(timeout=host_timeout)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
                return 124


def run_agent(
    handle: ContainerHandle,
    *,
    arm: str,
    prompt: str,
    system_prompt: str = "You are a helpful assistant.",
    result_path: str,
    model: str | None = None,
    wall_timeout: int = 3600,
    mcp_required: bool | None = None,
    max_attempts: int = 4,
    surface: str = "claude_code",
) -> int:
    """Run one Claude turn inside the arm container, streaming the JSONL
    transcript to ``result_path`` on the host.

    Runs as the non-root agent user, ``CLAUDE_CONFIG_DIR=/opt/cfg``, cwd
    ``/testbed``.  Returns the exit code (124 = wall timeout from the in-container
    ``timeout``).  Requires :func:`stage_arm` to have run on this container and
    the runtime volume to be mounted.

    **MCP-startup-race retry.** Claude Code's MCP init is a nondeterministic race
    (documented "uncontrolled" — cf. the iso-nonce note in ``runner.py``); under
    the in-container cold start the codebox server sometimes registers too late
    and a ``code_only`` turn sees no ``execute_code``.  For arms that *require*
    the codebox tool (``mcp_required``, defaulting to ``code_only``/``onlycode``),
    a turn that used zero ``mcp__codebox__`` tools is retried (up to
    ``max_attempts``).  Failed rolls are cheap — the tool-less agent gives up in
    seconds — and successful turns are never retried.

    NOTE: writing the transcript to the host here is the minimal capture C4 needs
    to verify a turn; the full transcript/result + no-leak contract is C4b
    (#324).
    """
    if mcp_required is None:
        mcp_required = arm in _MCP_REQUIRED_ARMS
    agent_argv = build_agent_argv(
        arm, prompt=prompt, system_prompt=system_prompt,
        model=model, wall_timeout=wall_timeout, surface=surface,
    )
    host_timeout = (wall_timeout + 120) if wall_timeout and wall_timeout > 0 else None

    rc = 0
    for attempt in range(1, max_attempts + 1):
        rc = _invoke_once(handle, agent_argv, result_path, host_timeout, surface=surface)
        if not mcp_required or _codebox_was_used(result_path):
            return rc
        if attempt < max_attempts:
            logging.warning(
                "container_agent: codebox MCP did not connect (arm=%s, attempt %d/%d) "
                "— retrying (Claude Code MCP startup race)", arm, attempt, max_attempts,
            )
    if mcp_required and not _codebox_was_used(result_path):
        logging.error(
            "container_agent: codebox MCP failed to connect after %d attempts (arm=%s)",
            max_attempts, arm,
        )
    return rc


# --------------------------------------------------------------------------
# Output capture + no-leak (C4b #324)
# --------------------------------------------------------------------------

class ContainerLeakError(RuntimeError):
    """A held-out grader / reference / test artifact was visible to the agent.

    The image-runtime analog of artifact ``MaterializationError`` — raised by
    :func:`assert_no_leak` (mirror of ``artifact_materialize._assert_no_leak``).
    """


def extract_agent_diff(handle: ContainerHandle, dest_path: str) -> str:
    """Write the agent's repo diff (``git diff`` over ``/testbed``) to the host.

    The snapshot's ``/testbed`` is a single orphan commit at the instance's
    ``base_commit`` tree (C3 strip), so ``git diff`` is exactly the agent's
    change set vs base — the *model patch* C5 grades.  Run as the agent user
    (it owns ``/testbed``).  ``dest_path`` is a **host** path, never mounted into
    the container, so the agent cannot read its own captured result.  Returns the
    diff text.
    """
    proc = container._docker(
        ["exec", "-u", AGENT_USER, "-w", "/testbed", handle.container_id,
         "git", "diff"],
        check=True,
    )
    diff = proc.stdout.decode("utf-8", "replace") if proc.stdout else ""
    Path(dest_path).write_text(diff)
    return diff


def held_out_markers_from_patch(test_patch: str) -> list[str]:
    """Names of test functions/classes *added* by a held-out test patch.

    These are the content markers that must NOT already be present in the
    agent's ``/testbed`` (the SWE-bench leak vector is added assertions in
    existing files, which a filename scan can't catch).  Parses ``+def test_*``
    / ``+class *Test*`` from the patch's added lines.
    """
    markers: list[str] = []
    for line in test_patch.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        s = line[1:].strip()
        if s.startswith("def "):
            name = s[4:].split("(", 1)[0].strip()
            if name.startswith("test") or name.startswith("Test"):
                markers.append(name)
        elif s.startswith("class ") and "Test" in s:
            markers.append(s[6:].split("(", 1)[0].split(":", 1)[0].strip())
    return markers


#: Held-out artifact basenames that must never be visible in-container — mirrors
#: the artifact no-leak scan (``hidden.py`` grader module, ``reference_output.*``
#: golden artifact) plus the SWE-bench held-out test patch file.
_LEAK_FIND_SCRIPT = r"""
set -eu
for root in "$@"; do
    [ -e "$root" ] || continue
    find "$root" -type f \( \
        -name hidden.py -o \
        -name 'reference_output*' -o \
        -name '*_tests.patch' -o \
        -name '*.gold.patch' \
    \) 2>/dev/null
done
"""


def assert_no_leak(
    handle: ContainerHandle,
    *,
    test_patch: str | None = None,
    extra_markers: tuple[str, ...] = (),
    roots: tuple[str, ...] = ("/testbed", CFG_DIR),
) -> None:
    """Fail loudly if any held-out grader/reference/test artifact is visible to
    the agent inside the container (mirror of ``_assert_no_leak``).

    Two checks over ``roots`` (default ``/testbed`` + the agent-readable
    ``/opt/cfg``):

    1. **Filenames** — ``hidden.py``, ``reference_output*``, ``*_tests.patch``,
       ``*.gold.patch`` must not exist.
    2. **Content markers** — the held-out test names added by ``test_patch``
       (plus ``extra_markers``) must not already appear in ``/testbed`` sources;
       their presence means the held-out assertions leaked.

    Call after the agent finishes and **before** the held-out test patch is
    applied (C5).  Raises :class:`ContainerLeakError` on any hit.
    """
    cid = handle.container_id
    leaks: list[str] = []

    found = container._docker(
        ["exec", cid, "bash", "-c", _LEAK_FIND_SCRIPT, "scan", *roots], check=False,
    )
    names = [l for l in (found.stdout or b"").decode("utf-8", "replace").splitlines() if l.strip()]
    leaks += [f"file: {n}" for n in names]

    markers = list(held_out_markers_from_patch(test_patch or "")) + list(extra_markers)
    if markers:
        # grep -F (fixed strings) -r -l: list files in /testbed containing a marker.
        pattern = "\n".join(markers)
        hit = container._docker(
            ["exec", "-i", cid, "bash", "-c",
             'grep -rlF -f - /testbed 2>/dev/null || true'],
            check=False, input_bytes=pattern.encode(),
        )
        hits = [l for l in (hit.stdout or b"").decode("utf-8", "replace").splitlines() if l.strip()]
        leaks += [f"held-out marker in: {h}" for h in hits]

    if leaks:
        raise ContainerLeakError(
            "held-out artifacts visible to the agent in-container:\n  "
            + "\n  ".join(leaks)
        )
