"""Tests for in-container Claude agent execution (``swebench/container_agent.py``, C4 #318).

Layers:

* **Hermetic** (CI) — argv / mcp-config / setup-command assembly and per-arm
  staging, with the ``docker`` boundary mocked. No daemon, no cost.
* **``@integration``** (needs Docker + an image) — the cred-never-persists
  guarantee: prepare a snapshot and assert no credentials are baked in. No agent
  turn, so no cost.
* **``@integration`` + ``ONLYCODES_RUN_AGENT_TESTS=1``** — real in-container
  agent turns proving tool restriction (`code_only` can't reach native tools),
  executed-code network isolation, and that the baseline arm keeps native tools.
  These cost money and need live credentials, so they are off by default.
"""

from __future__ import annotations

import json
import os
import subprocess
import types
from pathlib import Path

import pytest

from swebench import container, container_agent as ca
from swebench.container import ContainerHandle
from swebench.runner import BLOCKED_BUILTINS


# --------------------------------------------------------------------------
# Hermetic: assembly
# --------------------------------------------------------------------------

def test_agent_user_setup_commands_are_secret_free_useradd_and_chown() -> None:
    cmds = ca.agent_user_setup_commands("/testbed")
    assert cmds[0][:2] == ["bash", "-c"]
    assert f"useradd -m -u {ca.AGENT_UID} {ca.AGENT_USER}" in cmds[0][2]
    assert cmds[1] == ["chown", "-R", f"{ca.AGENT_USER}:{ca.AGENT_USER}", "/testbed"]
    # Nothing secret-bearing — these are baked into the committed snapshot.
    assert not any("cred" in part.lower() for cmd in cmds for part in cmd)


def test_runtime_volume_spec_ro_and_rw() -> None:
    assert ca.runtime_volume_spec() == f"{ca.RUNTIME_VOLUME}:{ca.AGENT_MOUNT}:ro"
    assert ca.runtime_volume_spec(read_only=False) == f"{ca.RUNTIME_VOLUME}:{ca.AGENT_MOUNT}"


def test_incontainer_mcp_config_points_at_staged_node_and_bundle() -> None:
    cfg = ca._incontainer_mcp_config()
    box = cfg["mcpServers"]["codebox"]
    assert box["command"] == ca.NODE_BIN == f"{ca.AGENT_MOUNT}/node"
    assert box["args"] == [ca.BUNDLE_IN_CFG]
    assert ca.BUNDLE_IN_CFG.startswith(ca.CFG_DIR)   # writable per-arm dir, not the ro volume
    assert box["cwd"] == "/testbed"
    assert box["env"]["ONLYCODES_PERSISTENT_KERNEL"] == "1"
    # kernel runs in the testbed conda env so executed code imports the project.
    assert box["env"]["PATH"].startswith(f"{ca.TESTBED_ENV}/bin:")
    assert ca._incontainer_mcp_config(persistent_kernel=False)[
        "mcpServers"]["codebox"]["env"]["ONLYCODES_PERSISTENT_KERNEL"] == "0"


def test_build_agent_argv_code_only_restricts_to_codebox() -> None:
    argv = ca.build_agent_argv(
        "code_only", prompt="do x", system_prompt="sys", wall_timeout=300)
    # in-container timeout prefix bounds wall time.
    assert argv[:2] == ["timeout", "300s"]
    assert ca.CLAUDE_BIN in argv
    # single-sourced tool flags: mcp-config (in-container) + codebox tools + disallow natives.
    assert "--mcp-config" in argv and ca.MCP_CONFIG_IN_CFG in argv
    assert "--strict-mcp-config" in argv
    i = argv.index("--tools")
    assert argv[i + 1] == "mcp__codebox__execute_code,mcp__codebox__list_tools"
    j = argv.index("--disallowedTools")
    assert argv[j + 1] == BLOCKED_BUILTINS
    for flag in ("--dangerously-skip-permissions", "--no-session-persistence"):
        assert flag in argv
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert argv[argv.index("--model") + 1] == ca.MODEL


def test_build_agent_argv_baseline_has_no_tool_restriction() -> None:
    argv = ca.build_agent_argv(
        "baseline", prompt="p", system_prompt="s", wall_timeout=0)
    # No timeout prefix when wall_timeout == 0.
    assert argv[0] == ca.CLAUDE_BIN
    # baseline => native tools; no restriction flags.
    assert "--tools" not in argv and "--disallowedTools" not in argv
    assert "--mcp-config" not in argv


def test_run_agent_builds_isolated_nonroot_docker_exec(monkeypatch, tmp_path) -> None:
    captured = {}

    class _FakeProc:
        def __init__(self, argv, **kw):
            captured["argv"] = argv
            captured["stdout"] = kw.get("stdout")
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def wait(self, timeout=None):
            # Prove the transcript file handle is what we stream into.
            captured["stdout"].write(b'{"type":"result"}\n')
            return 0

    monkeypatch.setattr(ca.subprocess, "Popen", _FakeProc)
    result = tmp_path / "t.jsonl"
    rc = ca.run_agent(
        ContainerHandle("i", "cid123", "snap"),
        arm="code_only", prompt="p", result_path=str(result), wall_timeout=60,
        mcp_required=False,  # isolate the argv assembly from the MCP retry path
    )
    assert rc == 0
    argv = captured["argv"]
    assert argv[0] == container._docker_bin() and argv[1] == "exec"
    # Non-root, isolated config dir, cwd /testbed.
    assert argv[argv.index("-u") + 1] == ca.AGENT_USER
    assert argv[argv.index("-w") + 1] == "/testbed"
    assert f"CLAUDE_CONFIG_DIR={ca.CFG_DIR}" in argv
    assert f"MCP_TIMEOUT={ca.MCP_TIMEOUT_MS}" in argv  # avoids the codebox pending race
    assert "cid123" in argv
    assert result.read_text() == '{"type":"result"}\n'


def test_stage_arm_copies_bundle_creds_and_chowns(monkeypatch, tmp_path) -> None:
    calls: list[list[str]] = []

    def _fake_docker(args, **kw):
        calls.append(args)
        return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(container, "_docker", _fake_docker)
    # Fake the (gitignored, build-only) exec-server dist so the test is hermetic.
    dist = tmp_path / "dist"
    dist.mkdir()
    for fname in ca._EXEC_SERVER_FILES:
        (dist / fname).write_text("x")
    monkeypatch.setattr(ca, "_exec_server_dist", lambda: dist)
    creds = tmp_path / "creds"
    creds.mkdir()
    (creds / ".credentials.json").write_text("{}")
    (creds / ".claude.json").write_text("{}")

    ca.stage_arm(ContainerHandle("i", "cidX", "snap"), creds_src=str(creds))

    joined = [" ".join(a) for a in calls]
    # exec-server bundle staged under the writable cfg dir.
    assert any("exec-server.bundle.mjs" in s and f"cidX:{ca.CFG_DIR}/exec_server" in s
               for s in joined)
    # mcp-config + both cred files cp'd in.
    assert any(ca.MCP_CONFIG_IN_CFG in s for s in joined)
    assert any(".credentials.json" in s for s in joined)
    assert any(".claude.json" in s for s in joined)
    # final chown -R of the whole cfg dir to the agent user.
    assert calls[-1] == ["exec", "cidX", "chown", "-R",
                         f"{ca.AGENT_USER}:{ca.AGENT_USER}", ca.CFG_DIR]


def test_stage_arm_raises_if_exec_server_unbuilt(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(ca, "_exec_server_dist", lambda: tmp_path / "nope")
    with pytest.raises(ca.AgentRuntimeError, match="npm run build"):
        ca.stage_arm(ContainerHandle("i", "c", "s"))


def test_run_agent_retries_code_only_until_codebox_connects(monkeypatch, tmp_path) -> None:
    # Simulate the MCP startup race: first two invocations produce a transcript
    # with no codebox use; the third connects.
    result = tmp_path / "r.jsonl"
    calls = {"n": 0}

    def _fake_invoke(handle, argv, path, host_timeout):
        calls["n"] += 1
        if calls["n"] < 3:
            Path(path).write_text('{"type":"assistant"}\n')  # no codebox tool
        else:
            Path(path).write_text('{"type":"assistant"}\n'
                                  '{"tool":"mcp__codebox__execute_code"}\n')
        return 0

    monkeypatch.setattr(ca, "_invoke_once", _fake_invoke)
    rc = ca.run_agent(ContainerHandle("i", "c", "s"), arm="code_only",
                      prompt="p", result_path=str(result), max_attempts=4)
    assert rc == 0
    assert calls["n"] == 3, "should retry until codebox connects, then stop"


def test_run_agent_baseline_never_retries(monkeypatch, tmp_path) -> None:
    result = tmp_path / "b.jsonl"
    calls = {"n": 0}

    def _fake_invoke(handle, argv, path, host_timeout):
        calls["n"] += 1
        Path(path).write_text('{"type":"assistant"}\n')  # no codebox — irrelevant for baseline
        return 0

    monkeypatch.setattr(ca, "_invoke_once", _fake_invoke)
    ca.run_agent(ContainerHandle("i", "c", "s"), arm="baseline",
                 prompt="p", result_path=str(result), max_attempts=4)
    assert calls["n"] == 1, "baseline does not require codebox; no retry"


def test_run_agent_gives_up_after_max_attempts(monkeypatch, tmp_path) -> None:
    result = tmp_path / "g.jsonl"
    calls = {"n": 0}

    def _fake_invoke(handle, argv, path, host_timeout):
        calls["n"] += 1
        Path(path).write_text('{"type":"assistant"}\n')  # never connects
        return 0

    monkeypatch.setattr(ca, "_invoke_once", _fake_invoke)
    ca.run_agent(ContainerHandle("i", "c", "s"), arm="code_only",
                 prompt="p", result_path=str(result), max_attempts=3)
    assert calls["n"] == 3, "exhausts max_attempts then returns"


# --------------------------------------------------------------------------
# Hermetic: output capture + no-leak (C4b #324)
# --------------------------------------------------------------------------

_TEST_PATCH = (
    "diff --git a/test_requests.py b/test_requests.py\n"
    "--- a/test_requests.py\n"
    "+++ b/test_requests.py\n"
    "@@ -58,6 +58,13 @@ def test_basic_building(self):\n"
    "+    def test_no_content_length(self):\n"
    "+        get_req = requests.Request('GET', httpbin('get')).prepare()\n"
    "+        self.assertTrue('Content-Length' not in get_req.headers)\n"
    "+class ExtraTestCase(unittest.TestCase):\n"
)


def test_held_out_markers_from_patch_extracts_added_test_names() -> None:
    markers = ca.held_out_markers_from_patch(_TEST_PATCH)
    assert "test_no_content_length" in markers
    assert "ExtraTestCase" in markers
    # context/removed lines and the +++ header are not markers.
    assert "test_basic_building" not in markers


def test_extract_agent_diff_writes_host_file(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(container, "_docker",
                        lambda args, **kw: types.SimpleNamespace(
                            returncode=0, stdout=b"diff --git a/m.py b/m.py\n-x\n", stderr=b""))
    dest = tmp_path / "model.patch"
    out = ca.extract_agent_diff(ContainerHandle("i", "c", "s"), str(dest))
    assert "diff --git a/m.py" in out
    assert dest.read_text() == out  # host file written, agent can't reach host fs


def test_assert_no_leak_passes_when_clean(monkeypatch) -> None:
    # find -> nothing; grep -> nothing.
    monkeypatch.setattr(container, "_docker",
                        lambda args, **kw: types.SimpleNamespace(
                            returncode=0, stdout=b"", stderr=b""))
    ca.assert_no_leak(ContainerHandle("i", "c", "s"), test_patch=_TEST_PATCH)  # no raise


def test_assert_no_leak_raises_on_forbidden_filename(monkeypatch) -> None:
    def _fake(args, **kw):
        # the find script (bash -c ... scan) returns a grader file.
        if "bash" in args and any("find" in a for a in args):
            return types.SimpleNamespace(returncode=0, stdout=b"/testbed/grader/hidden.py\n", stderr=b"")
        return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
    monkeypatch.setattr(container, "_docker", _fake)
    with pytest.raises(ca.ContainerLeakError, match="hidden.py"):
        ca.assert_no_leak(ContainerHandle("i", "c", "s"))


def test_assert_no_leak_raises_on_held_out_marker(monkeypatch) -> None:
    def _fake(args, **kw):
        if "grep" in " ".join(a for a in args if isinstance(a, str)):
            return types.SimpleNamespace(returncode=0, stdout=b"/testbed/test_requests.py\n", stderr=b"")
        return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
    monkeypatch.setattr(container, "_docker", _fake)
    with pytest.raises(ca.ContainerLeakError, match="held-out marker"):
        ca.assert_no_leak(ContainerHandle("i", "c", "s"), test_patch=_TEST_PATCH)


# --------------------------------------------------------------------------
# Integration scaffolding
# --------------------------------------------------------------------------

def _docker_available() -> bool:
    try:
        return subprocess.run(
            ["docker", "version"], capture_output=True, timeout=15
        ).returncode == 0
    except Exception:
        return False


def _test_image() -> str:
    return os.environ.get(
        "ONLYCODES_TEST_IMAGE",
        "swebench/sweb.eval.x86_64.psf_1776_requests-1142:latest",
    )


requires_docker = lambda fn: pytest.mark.integration(  # noqa: E731
    pytest.mark.skipif(not _docker_available(), reason="docker daemon not available")(fn)
)

requires_agent_run = pytest.mark.skipif(
    os.environ.get("ONLYCODES_RUN_AGENT_TESTS") != "1",
    reason="live agent turn (costs money, needs creds); set ONLYCODES_RUN_AGENT_TESTS=1",
)


def _instance_from_image(img: str) -> str:
    slug = img.split("sweb.eval.x86_64.", 1)[1].rsplit(":", 1)[0]
    return slug.replace(container._NAMESPACE_TOKEN, "__")


# --------------------------------------------------------------------------
# Integration (no cost): credentials never persist into the snapshot
# --------------------------------------------------------------------------

@requires_docker
def test_credentials_absent_from_snapshot_image() -> None:
    img = _test_image()
    if not container.image_present(img):
        pytest.skip(f"test image not present: {img}")
    instance_id = _instance_from_image(img)
    snapshot = container.prepared_tag(instance_id)
    if container.image_present(snapshot):
        pytest.skip(f"would clobber an existing snapshot: {snapshot}")
    try:
        container.prepare_instance(
            instance_id, force=True,
            post_strip_exec=ca.agent_user_setup_commands(),
        )
        # A fresh container off the snapshot must carry NO credentials and no
        # /opt/cfg — those only ever exist in ephemeral arm containers.
        probe = container._docker(
            ["run", "--rm", snapshot, "bash", "-c",
             "find / -name .credentials.json 2>/dev/null; ls -d /opt/cfg 2>/dev/null; "
             "id agent >/dev/null 2>&1 && echo AGENT_USER_BAKED"],
            check=False,
        )
        out = probe.stdout.decode("utf-8", "replace")
        assert ".credentials.json" not in out, f"creds leaked into snapshot:\n{out}"
        assert "/opt/cfg" not in out
        # But the agent user IS baked in (post_strip_exec ran).
        assert "AGENT_USER_BAKED" in out
    finally:
        subprocess.run(["docker", "rmi", "-f", snapshot], capture_output=True)


# --------------------------------------------------------------------------
# Integration (costs money): real in-container agent turns
# --------------------------------------------------------------------------

@pytest.fixture()
def staged_arm():
    """A prepared+started arm container with runtime mounted and creds staged."""
    img = _test_image()
    if not container.image_present(img):
        pytest.skip(f"test image not present: {img}")
    instance_id = _instance_from_image(img)
    snapshot = container.prepared_tag(instance_id)
    clobbers = container.image_present(snapshot)
    if clobbers:
        pytest.skip(f"would clobber an existing snapshot: {snapshot}")

    claude = __import__("swebench.runner", fromlist=["ClaudeRunner"]).ClaudeRunner().find_binary()
    ca.ensure_agent_runtime(claude)
    prepared = container.prepare_instance(
        instance_id, force=True, post_strip_exec=ca.agent_user_setup_commands())
    handle = container.start_arm_container(
        prepared, volumes=[ca.runtime_volume_spec()])
    ca.stage_arm(handle)
    try:
        yield handle
    finally:
        container.teardown(handle)
        subprocess.run(["docker", "rmi", "-f", snapshot], capture_output=True)


def _records(path: Path) -> list[dict]:
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def _tool_uses(recs: list[dict]) -> list[dict]:
    return [
        c for r in recs if r.get("type") == "assistant"
        for c in r.get("message", {}).get("content", []) if c.get("type") == "tool_use"
    ]


def _tool_result_text(recs: list[dict]) -> str:
    """Concatenated text of all tool_result blocks — the *actual* executed
    output, distinct from the assistant's prose (which may paraphrase code)."""
    parts = []
    for r in recs:
        if r.get("type") != "user":
            continue
        for c in r.get("message", {}).get("content", []):
            if isinstance(c, dict) and c.get("type") == "tool_result":
                body = c.get("content")
                if isinstance(body, list):
                    body = "".join(b.get("text", "") for b in body if isinstance(b, dict))
                parts.append(body if isinstance(body, str) else json.dumps(body))
    return "\n".join(parts)


@requires_docker
@requires_agent_run
def test_code_only_turn_restriction_and_netiso(staged_arm, tmp_path) -> None:
    # One paid turn covering: codebox reachable, executed-code net-iso, and no
    # native file tools.
    prompt = (
        "Use the execute_code tool to run this exact Python and report what it "
        "prints:\n"
        "print('SENTINEL_42')\n"
        "import urllib.request\n"
        "try:\n"
        "    urllib.request.urlopen('http://1.1.1.1', timeout=5); print('NET_REACHABLE')\n"
        "except Exception as e:\n"
        "    print('NET_ISOLATED', type(e).__name__)\n"
    )
    result = tmp_path / "code_only.jsonl"
    rc = ca.run_agent(staged_arm, arm="code_only", prompt=prompt,
                      result_path=str(result), wall_timeout=300)
    assert rc == 0, f"agent exited {rc}"
    recs = _records(result)
    uses = _tool_uses(recs)
    # The codebox MCP tool was reachable and actually used (proves it connected —
    # the init-record mcp_servers status is an unreliable snapshot).
    assert any(u.get("name", "").startswith("mcp__codebox__") for u in uses), (
        f"execute_code was never used; tools used: {[u.get('name') for u in uses]}"
    )
    # Assert on the *executed output* (tool_result), not the agent's prose.
    out = _tool_result_text(recs)
    assert "SENTINEL_42" in out, "executed code did not run via codebox"
    # executed code could NOT reach the network (unshare -n active in-container).
    assert "NET_ISOLATED" in out and "NET_REACHABLE" not in out, f"net-iso failed:\n{out}"
    # restriction: no native file-tool use anywhere in the transcript.
    native = {"Read", "Write", "Edit", "Bash", "Glob", "Grep"}
    assert not (native & {u.get("name") for u in uses}), (
        f"native tool used under code_only: {[u.get('name') for u in uses]}"
    )


@requires_docker
@requires_agent_run
def test_baseline_turn_keeps_native_tools(staged_arm, tmp_path) -> None:
    prompt = "Use the Read tool to read /testbed/setup.py and report its first line."
    result = tmp_path / "baseline.jsonl"
    rc = ca.run_agent(staged_arm, arm="baseline", prompt=prompt,
                      result_path=str(result), wall_timeout=300)
    assert rc == 0
    recs = _records(result)
    used = {
        c.get("name")
        for r in recs if r.get("type") == "assistant"
        for c in r.get("message", {}).get("content", []) if c.get("type") == "tool_use"
    }
    # baseline arm has native tools available and used at least one.
    assert used and used & {"Read", "Bash", "Glob", "Grep"}, f"tools used: {used}"


# --------------------------------------------------------------------------
# Integration (no cost — no agent turn): output capture + no-leak (C4b #324)
# --------------------------------------------------------------------------

@requires_docker
def test_extract_diff_and_no_leak_on_clean_container(staged_arm, tmp_path) -> None:
    # A freshly staged container (no agent edits yet): the model diff is empty,
    # and the held-out test markers are absent from /testbed.
    dest = tmp_path / "model.patch"
    diff = ca.extract_agent_diff(staged_arm, str(dest))
    assert diff == "" and dest.read_text() == "", "pristine /testbed should have empty diff"
    # No-leak passes: requests-1142's held-out test name isn't in base /testbed.
    ca.assert_no_leak(staged_arm, test_patch=_TEST_PATCH)


@requires_docker
def test_assert_no_leak_catches_a_real_in_container_leak(staged_arm) -> None:
    # Simulate the held-out test leaking into /testbed; the scan must catch it.
    container._docker(
        ["exec", "-u", ca.AGENT_USER, staged_arm.container_id, "bash", "-c",
         "echo 'def test_no_content_length(self): pass' > /testbed/leaked_test.py"],
        check=True,
    )
    with pytest.raises(ca.ContainerLeakError, match="held-out marker"):
        ca.assert_no_leak(staged_arm, test_patch=_TEST_PATCH)
    # And a forbidden filename is caught too.
    container._docker(
        ["exec", staged_arm.container_id, "bash", "-c",
         "mkdir -p /testbed/grader && touch /testbed/grader/hidden.py"],
        check=True,
    )
    with pytest.raises(ca.ContainerLeakError, match="hidden.py"):
        ca.assert_no_leak(staged_arm)
