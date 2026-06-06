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
from swebench.runner import ClaudeRunner


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

#: The SWE-bench image's project conda env (repo installed editable here).
TESTBED_ENV = "/opt/miniconda3/envs/testbed"

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


# --------------------------------------------------------------------------
# Per-arm staging: exec-server bundle + mcp-config + credentials -> /opt/cfg
# --------------------------------------------------------------------------

def _incontainer_mcp_config(*, persistent_kernel: bool = True) -> dict:
    # Prepend the testbed env's bin so the exec-server's python kernel runs in the
    # *project* conda env (where the repo is installed editable) — not the base
    # env — so executed code can import the package under test.
    path = (
        f"{TESTBED_ENV}/bin:/opt/miniconda3/bin:"
        "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    )
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


def stage_arm(
    handle: ContainerHandle,
    *,
    creds_src: str | None = None,
    persistent_kernel: bool = True,
) -> None:
    """Stage the per-arm config into ``/opt/cfg`` of a running arm container.

    Copies the exec-server bundle + helpers, writes the in-container
    ``mcp-config.json``, and ``docker cp``'s the Claude credentials
    (``.credentials.json`` + ``.claude.json``) from ``creds_src`` (default
    ``~/.claude``).  Everything is chowned to the agent user.  None of this is
    ever committed — arm containers are torn down, not snapshotted.
    """
    creds_src = creds_src or os.path.expanduser("~/.claude")
    dist = _exec_server_dist()
    for fname in _EXEC_SERVER_FILES:
        if not (dist / fname).is_file():
            raise AgentRuntimeError(
                f"exec-server file missing: {dist / fname} — run `npm run build` "
                "in exec_server/ first."
            )

    cid = handle.container_id
    container._docker(["exec", cid, "mkdir", "-p", f"{CFG_DIR}/exec_server"])
    for fname in _EXEC_SERVER_FILES:
        container._docker(["cp", str(dist / fname), f"{cid}:{CFG_DIR}/exec_server/{fname}"])

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


# --------------------------------------------------------------------------
# Invocation
# --------------------------------------------------------------------------

def build_agent_argv(
    arm: str,
    *,
    prompt: str,
    system_prompt: str,
    model: str = MODEL,
    wall_timeout: int = 3600,
) -> list[str]:
    """The in-container claude argv for an arm (no docker wrapper).

    Tool flags come from ``ClaudeRunner.build_tools_flags`` (single-sourced with
    the host path); only the mcp-config path is in-container.  A ``timeout``
    prefix bounds wall time *inside* the container so the agent is killed even if
    the host ``docker exec`` client is interrupted.
    """
    tools_flags = ClaudeRunner().build_tools_flags(arm, MCP_CONFIG_IN_CFG)
    argv = [
        CLAUDE_BIN,
        "-p", prompt,
        "--model", model,
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


#: Arms whose only tools are the codebox MCP — a turn with zero ``mcp__codebox__``
#: use means the MCP server never connected (the agent had no tools), not that
#: the task needed none.
_MCP_REQUIRED_ARMS = {"code_only", "onlycode"}


def _codebox_was_used(result_path: str) -> bool:
    try:
        text = Path(result_path).read_text()
    except OSError:
        return False
    # Cheap + robust: the tool name appears in the assistant's tool_use blocks.
    return "mcp__codebox__" in text


def _invoke_once(
    handle: ContainerHandle, agent_argv: list[str], result_path: str,
    host_timeout: int | None,
) -> int:
    docker_argv = [
        container._docker_bin(), "exec",
        "-u", AGENT_USER,
        "-w", "/testbed",
        "-e", f"CLAUDE_CONFIG_DIR={CFG_DIR}",
        "-e", f"HOME={AGENT_HOME}",
        "-e", "FORCE_PROMPT_CACHING_5M=1",
        "-e", f"MCP_TIMEOUT={MCP_TIMEOUT_MS}",
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
    model: str = MODEL,
    wall_timeout: int = 3600,
    mcp_required: bool | None = None,
    max_attempts: int = 4,
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
        model=model, wall_timeout=wall_timeout,
    )
    host_timeout = (wall_timeout + 120) if wall_timeout and wall_timeout > 0 else None

    rc = 0
    for attempt in range(1, max_attempts + 1):
        rc = _invoke_once(handle, agent_argv, result_path, host_timeout)
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
