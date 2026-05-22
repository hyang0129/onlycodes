"""Regression tests for Issue #287: test patch is invisible to the agent.

Issue #226 closed the ``git diff`` vector by committing the test patch
pre-agent.  Issue #287 closes the remaining vector — the test files on
disk — by deferring ``apply_test_patch`` to *after* the agent terminates.

These tests assert two invariants, both captured at the moment ``invoke()``
runs:

1. The test patch file's contents are NOT present in the repo working tree
   (no leak via ``cat tests/test_added.py`` / ``ls tests/`` / ``grep -r``).
2. ``git diff`` and ``git diff HEAD`` are both empty (the #226 invariant
   continues to hold under the new ordering).

The trick: install a stub ``AgentRunner`` whose ``invoke()`` *snapshots*
the repo state at exactly the moment the agent would have been running.
After ``_run_arm`` returns, inspect those snapshots.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from swebench import run as run_mod
from swebench.harness import strip_git_history
from swebench.models import Problem


# Unique sentinel that the agent would see if the test_patch leaked. Picked
# to be obviously not a coincidence in any source file.
SECRET_ASSERTION = "ASSERT_HIDDEN_287_FINGERPRINT == 42"


def _git(repo: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True,
        text=True,
        check=True,
    )


def _make_repo_with_history(root: Path) -> str:
    """Create a small repo with a base commit; matches what ``_setup_problem``
    leaves behind once ``strip_git_history`` has run."""
    repo = root / "repo"
    repo.mkdir()
    _git(str(repo), "init", "-q", "-b", "main")
    _git(str(repo), "config", "user.email", "test@test")
    _git(str(repo), "config", "user.name", "test")
    (repo / "src.py").write_text("def f():\n    return 1\n")
    _git(str(repo), "add", "src.py")
    _git(str(repo), "commit", "-q", "-m", "base commit")
    # The harness always runs strip_git_history before handing the repo to
    # the agent — mirror that here so the test reflects real conditions.
    strip_git_history(str(repo))
    return str(repo)


def _write_test_patch(root: Path) -> Path:
    """Write a test_patch that introduces a new tests/ file containing the
    secret sentinel.  Patch is shaped like real SWE-bench test_patches."""
    patches_dir = root / "patches"
    patches_dir.mkdir()
    patch = patches_dir / "leak_probe_tests.patch"
    patch.write_text(
        "diff --git a/tests/test_added.py b/tests/test_added.py\n"
        "new file mode 100644\n"
        "index 0000000..1111111\n"
        "--- /dev/null\n"
        "+++ b/tests/test_added.py\n"
        "@@ -0,0 +1,3 @@\n"
        "+def test_leaks():\n"
        f"+    {SECRET_ASSERTION}\n"
        "+\n"
    )
    return patch


def _make_problem(root: Path, patch_rel: str) -> Problem:
    return Problem(
        instance_id="probe__instance-287",
        repo_slug="probe/instance",
        base_commit="HEAD",
        test_cmd="python -m pytest tests/test_added.py",
        problem_statement="Fix the leak probe.",
        patch_file=patch_rel,
        added_at="2026-05-22",
        hf_split="test",
    )


class _SnapshottingRunner:
    """At ``invoke()`` time, snapshot exactly what an agent on this machine
    would observe: the file listing under tests/, the contents of any test
    file the patch would add, and the output of ``git diff`` / ``git diff HEAD``.
    """

    surface = "claude_code"

    def __init__(self) -> None:
        self.snapshot: dict[str, object] = {}

    def build_tools_flags(self, arm, mcp_config_path):
        return []

    def get_version(self, binary):
        return "snapshot-runner"

    def extract_metadata(self, path):
        return (None, None)

    def invoke(self, **kw):
        cwd = kw["cwd"]
        tests_dir = os.path.join(cwd, "tests")
        if os.path.isdir(tests_dir):
            self.snapshot["tests_dir_listing"] = sorted(os.listdir(tests_dir))
        else:
            self.snapshot["tests_dir_listing"] = None

        added_path = os.path.join(cwd, "tests", "test_added.py")
        if os.path.isfile(added_path):
            self.snapshot["test_added_contents"] = Path(added_path).read_text()
        else:
            self.snapshot["test_added_contents"] = None

        # grep -r equivalent across the working tree.
        any_leak = False
        for base, dirs, files in os.walk(cwd):
            # don't descend into .git
            if ".git" in dirs:
                dirs.remove(".git")
            for name in files:
                p = os.path.join(base, name)
                try:
                    if SECRET_ASSERTION in Path(p).read_text(errors="ignore"):
                        any_leak = True
                        break
                except OSError:
                    continue
            if any_leak:
                break
        self.snapshot["secret_found_on_disk"] = any_leak

        self.snapshot["git_diff"] = _git(cwd, "diff").stdout
        self.snapshot["git_diff_head"] = _git(cwd, "diff", "HEAD").stdout


@pytest.fixture
def integrity_setup(tmp_path, monkeypatch):
    """Build a real git repo + test patch, then run ``_run_arm`` with the
    snapshotting runner.  Returns the populated snapshot dict."""
    repo_dir = _make_repo_with_history(tmp_path)
    patch = _write_test_patch(tmp_path)

    # venv dir — _run_arm only checks that bin/python exists; doesn't run it
    # because we stub out resolve_test_node_ids / run_preflight_collect.
    venv_dir = tmp_path / "venv"
    (venv_dir / "bin").mkdir(parents=True)
    (venv_dir / "bin" / "python").write_text("#!/bin/sh\nexec python3 \"$@\"\n")
    results_dir = tmp_path / "results"
    results_dir.mkdir()

    # Skip the resolver and preflight subprocess calls — they aren't part of
    # what we're asserting and would require a real venv.
    monkeypatch.setattr(run_mod, "resolve_test_node_ids", lambda cmd, **kw: cmd)
    monkeypatch.setattr(run_mod, "run_preflight_collect", lambda **kw: (True, ""))
    monkeypatch.setattr(run_mod, "run_tests", lambda **kw: "PASS")
    # Keep the real git operations intact (apply_test_patch + git_reset).
    monkeypatch.setattr(run_mod, "git_reset", lambda *a, **kw: None)
    # Skip the cloudpickle patch — only relevant for sklearn instances.
    monkeypatch.setattr(run_mod, "_patch_vendored_cloudpickle", lambda *a, **kw: False)

    snapshotter = _SnapshottingRunner()

    patch_rel = os.path.relpath(patch, tmp_path)
    problem = _make_problem(tmp_path, patch_rel)

    run_mod._run_arm(
        problem=problem,
        arm="baseline",
        run_idx=1,
        repo_dir=repo_dir,
        venv_dir=str(venv_dir),
        results_dir=str(results_dir),
        agent_binary="/usr/bin/claude",
        mcp_config_path=str(tmp_path / "mcp.json"),
        root=tmp_path,
        runner=snapshotter,
    )

    return snapshotter.snapshot, repo_dir


def test_test_patch_file_absent_during_agent_run(integrity_setup):
    """The test_added.py file from the patch must NOT exist on disk while
    the agent is running (closes the ``cat tests/test_added.py`` vector)."""
    snapshot, _ = integrity_setup
    assert snapshot["test_added_contents"] is None, (
        "tests/test_added.py was readable during agent execution — Issue #287 "
        "integrity invariant violated.\n"
        f"Contents: {snapshot['test_added_contents']!r}"
    )


def test_tests_directory_does_not_show_added_file_during_agent_run(integrity_setup):
    """``ls tests/`` must not list the patch's new file during agent execution."""
    snapshot, _ = integrity_setup
    listing = snapshot["tests_dir_listing"]
    if listing is not None:
        assert "test_added.py" not in listing, (
            "tests/test_added.py was visible to ``ls tests/`` during agent run; "
            f"directory listing: {listing}"
        )


def test_secret_assertion_not_grep_able_during_agent_run(integrity_setup):
    """A ``grep -r ASSERT_HIDDEN_287_FINGERPRINT`` over the working tree during
    agent execution must find zero matches."""
    snapshot, _ = integrity_setup
    assert snapshot["secret_found_on_disk"] is False, (
        "The hidden assertion fingerprint was discoverable via grep during "
        "agent execution — the test patch contents leaked onto disk."
    )


def test_git_diff_remains_empty_during_agent_run(integrity_setup):
    """Re-assert the Issue #226 invariant under the #287 ordering: both
    ``git diff`` and ``git diff HEAD`` must be empty from the agent's POV."""
    snapshot, _ = integrity_setup
    assert snapshot["git_diff"] == "", (
        f"git diff was non-empty during agent run: {snapshot['git_diff']!r}"
    )
    assert snapshot["git_diff_head"] == "", (
        f"git diff HEAD was non-empty during agent run: {snapshot['git_diff_head']!r}"
    )


def test_test_patch_applied_after_agent_terminates(integrity_setup):
    """Post-agent, the test patch must be applied and committed — otherwise
    ``run_tests`` would never see the held-out assertions."""
    _, repo_dir = integrity_setup
    added = Path(repo_dir) / "tests" / "test_added.py"
    assert added.exists(), (
        "tests/test_added.py must exist after _run_arm completes (post-agent "
        "apply_test_patch). File is missing — Issue #287 ordering is broken."
    )
    assert SECRET_ASSERTION in added.read_text()
    # Working tree must be clean (patch was committed, not left as a diff).
    assert _git(repo_dir, "diff").stdout == ""
    assert _git(repo_dir, "diff", "HEAD").stdout == ""


# ---------------------------------------------------------------------------
# Contamination guard — agent edits the test file the patch touches
# ---------------------------------------------------------------------------


class _ContaminatingRunner:
    """Stub runner that *edits* a file inside the patch's blast radius
    during ``invoke()`` — simulating a real agent that changed test files
    as part of its work.  Used to verify that ``apply_test_patch`` resets
    the agent's edits before applying the held-out patch.
    """

    surface = "claude_code"

    def __init__(self, target_rel: str, contamination: str) -> None:
        self._target_rel = target_rel
        self._contamination = contamination

    def build_tools_flags(self, arm, mcp_config_path):
        return []

    def get_version(self, binary):
        return "contaminating-runner"

    def extract_metadata(self, path):
        return (None, None)

    def invoke(self, **kw):
        cwd = kw["cwd"]
        target = Path(cwd) / self._target_rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self._contamination)


def _modify_patch(root: Path) -> Path:
    """A patch that MODIFIES an existing file (the typical case — ~95% of
    SWE-bench test_patches modify rather than add)."""
    patches_dir = root / "patches"
    patches_dir.mkdir(exist_ok=True)
    patch = patches_dir / "modify_existing.patch"
    patch.write_text(
        "diff --git a/tests/test_existing.py b/tests/test_existing.py\n"
        "--- a/tests/test_existing.py\n"
        "+++ b/tests/test_existing.py\n"
        "@@ -1,2 +1,3 @@\n"
        " def test_existing():\n"
        "     assert True\n"
        "+    assert HELDOUT_SENTINEL_287 == 42\n"
    )
    return patch


def test_agent_edits_to_patched_test_file_are_overwritten(monkeypatch, tmp_path):
    """End-to-end: an agent that rewrites the held-out test file gets its
    edits force-reset by ``apply_test_patch``; the run lands cleanly with
    the held-out assertion present in the committed tree."""
    # Build repo with a tests/test_existing.py at HEAD.
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(str(repo), "init", "-q", "-b", "main")
    _git(str(repo), "config", "user.email", "test@test")
    _git(str(repo), "config", "user.name", "test")
    tests_dir = repo / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_existing.py").write_text("def test_existing():\n    assert True\n")
    _git(str(repo), "add", "tests/test_existing.py")
    _git(str(repo), "commit", "-q", "-m", "base")
    strip_git_history(str(repo))

    patch = _modify_patch(tmp_path)

    venv_dir = tmp_path / "venv"
    (venv_dir / "bin").mkdir(parents=True)
    (venv_dir / "bin" / "python").write_text("#!/bin/sh\nexec python3 \"$@\"\n")
    results_dir = tmp_path / "results"
    results_dir.mkdir()

    monkeypatch.setattr(run_mod, "resolve_test_node_ids", lambda cmd, **kw: cmd)
    monkeypatch.setattr(run_mod, "run_preflight_collect", lambda **kw: (True, ""))
    monkeypatch.setattr(run_mod, "run_tests", lambda **kw: "PASS")
    monkeypatch.setattr(run_mod, "git_reset", lambda *a, **kw: None)
    monkeypatch.setattr(run_mod, "_patch_vendored_cloudpickle", lambda *a, **kw: False)

    runner = _ContaminatingRunner(
        target_rel="tests/test_existing.py",
        contamination="def test_existing():\n    pass  # CONTAMINATION\n",
    )

    problem = Problem(
        instance_id="probe__instance-contamination",
        repo_slug="probe/instance",
        base_commit="HEAD",
        test_cmd="python -m pytest tests/test_existing.py",
        problem_statement="dummy",
        patch_file=os.path.relpath(patch, tmp_path),
        added_at="2026-05-22",
        hf_split="test",
    )

    verdict = run_mod._run_arm(
        problem=problem,
        arm="baseline",
        run_idx=1,
        repo_dir=str(repo),
        venv_dir=str(venv_dir),
        results_dir=str(results_dir),
        agent_binary="/usr/bin/claude",
        mcp_config_path=str(tmp_path / "mcp.json"),
        root=tmp_path,
        runner=runner,
    )

    assert verdict == "PASS", (
        f"_run_arm must land cleanly after the contaminating runner runs; "
        f"got {verdict!r}"
    )
    final = (repo / "tests" / "test_existing.py").read_text()
    assert "HELDOUT_SENTINEL_287" in final, (
        f"Held-out patch did not land — file contents: {final!r}"
    )
    assert "CONTAMINATION" not in final, (
        f"Agent's contamination survived the patch — file contents: {final!r}"
    )


def test_unrecoverable_patch_apply_failure_scores_fail(monkeypatch, tmp_path):
    """If apply_test_patch ultimately returns False, ``_run_arm`` must score
    the run as ``FAIL`` immediately and skip ``run_tests`` — otherwise we'd
    measure the agent's own assertions, not the upstream contract."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(str(repo), "init", "-q", "-b", "main")
    _git(str(repo), "config", "user.email", "test@test")
    _git(str(repo), "config", "user.name", "test")
    (repo / "marker").write_text("x\n")
    _git(str(repo), "add", "marker")
    _git(str(repo), "commit", "-q", "-m", "base")
    strip_git_history(str(repo))

    venv_dir = tmp_path / "venv"
    (venv_dir / "bin").mkdir(parents=True)
    (venv_dir / "bin" / "python").write_text("#!/bin/sh\nexec python3 \"$@\"\n")
    results_dir = tmp_path / "results"
    results_dir.mkdir()

    monkeypatch.setattr(run_mod, "resolve_test_node_ids", lambda cmd, **kw: cmd)
    monkeypatch.setattr(run_mod, "git_reset", lambda *a, **kw: None)
    monkeypatch.setattr(run_mod, "_patch_vendored_cloudpickle", lambda *a, **kw: False)

    # apply_test_patch returns False unconditionally — simulates an
    # unrecoverable conflict that the reset+rm logic could not clear.
    monkeypatch.setattr(run_mod, "apply_test_patch", lambda *a, **kw: False)

    # If _run_arm reaches run_tests or run_preflight_collect after the
    # patch-apply failure, the test must fail loudly.
    def _boom(**kw):  # pragma: no cover
        raise AssertionError(
            "must not run pre-flight or run_tests against the contaminated tree"
        )

    monkeypatch.setattr(run_mod, "run_preflight_collect", _boom)
    monkeypatch.setattr(run_mod, "run_tests", _boom)

    # A patch_file path that exists is needed to enter the apply block at all.
    patch = tmp_path / "tests.patch"
    patch.write_text("not even a real patch\n")

    class _NoopRunner:
        surface = "claude_code"
        def build_tools_flags(self, arm, cfg): return []
        def get_version(self, b): return "stub"
        def extract_metadata(self, p): return (None, None)
        def invoke(self, **kw): pass

    problem = Problem(
        instance_id="probe__unrecoverable",
        repo_slug="probe/instance",
        base_commit="HEAD",
        test_cmd="python -m pytest x",
        problem_statement="dummy",
        patch_file=os.path.relpath(patch, tmp_path),
        added_at="2026-05-22",
        hf_split="test",
    )

    verdict = run_mod._run_arm(
        problem=problem,
        arm="baseline",
        run_idx=1,
        repo_dir=str(repo),
        venv_dir=str(venv_dir),
        results_dir=str(results_dir),
        agent_binary="/usr/bin/claude",
        mcp_config_path=str(tmp_path / "mcp.json"),
        root=tmp_path,
        runner=_NoopRunner(),
    )

    assert verdict == "FAIL", (
        f"Patch-apply failure must produce FAIL; got {verdict!r}"
    )
    # _test.txt's last non-empty line must be FAIL.
    test_txt = results_dir / "probe__unrecoverable_baseline_run1_test.txt"
    last = [ln for ln in test_txt.read_text().splitlines() if ln.strip()][-1]
    assert last.strip() == "FAIL"
    # Meta record must carry the verdict + a reason mentioning the apply failure.
    import json as _json
    jsonl = results_dir / "probe__unrecoverable_baseline_run1.jsonl"
    meta = _json.loads(jsonl.read_text().splitlines()[0])
    assert meta["verdict"] == "FAIL"
    assert "apply" in meta.get("reason", "").lower()
