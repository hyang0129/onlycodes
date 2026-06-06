"""Tests for in-container test execution + gold gate (``swebench/container_test.py``, C5 #319).

* **Hermetic** (CI): command building, patch-target parsing, apply/run/gate with
  the docker + grading boundary mocked.
* **``@integration``** (needs Docker **and** the official venv): the real gold
  gate on ``psf__requests-1142`` → ``RESOLVED_FULL`` (the C5 acceptance proof on
  the image path), plus digest pinning.
"""

from __future__ import annotations

import json
import os
import subprocess
import types
from pathlib import Path

import pytest

from swebench import container, container_test as ct

FIXTURE = Path(__file__).parent / "fixtures" / "swe_instance_psf__requests-1142.json"


# --------------------------------------------------------------------------
# Hermetic
# --------------------------------------------------------------------------

def test_build_eval_command_quotes_node_ids() -> None:
    cmd = ct.build_eval_command("pytest -rA", ["a.py::T::test_x[1-2]", "b.py::test_y"])
    assert cmd.startswith("pytest -rA ")
    assert "'a.py::T::test_x[1-2]'" in cmd  # brackets quoted so the shell won't glob
    assert "b.py::test_y" in cmd


def test_patch_targets_parses_plus_paths() -> None:
    patch = (
        "diff --git a/src/m.py b/src/m.py\n--- a/src/m.py\n+++ b/src/m.py\n@@ -1 +1 @@\n"
        "diff --git a/t.py b/t.py\n--- /dev/null\n+++ b/t.py\n"
    )
    assert ct._patch_targets(patch) == ["src/m.py", "t.py"]


def test_apply_patch_retries_after_resetting_targets(monkeypatch) -> None:
    calls = []

    def _fake(args, **kw):
        calls.append(args)
        # first `git apply` fails; `git checkout` ok; second `git apply` ok.
        if args[-2:] == ["git", "apply"] or args[-1] == "-":
            rc = 0 if any(a == "checkout" for c in calls for a in c) else 1
            return types.SimpleNamespace(returncode=rc, stdout=b"", stderr=b"")
        return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(container, "_docker", _fake)
    patch = "--- a/t.py\n+++ b/t.py\n@@ -1 +1 @@\n-x\n+y\n"
    assert ct.apply_patch_in_container(container.ContainerHandle("i", "c", "s"), patch) is True
    assert any("checkout" in c for c in calls), "should reset targets then retry"


def test_run_eval_writes_log_and_activates_testbed(monkeypatch, tmp_path) -> None:
    captured = {}

    def _fake(args, **kw):
        captured["script"] = args[-1]  # bash -lc <script>
        return types.SimpleNamespace(returncode=0, stdout=b"PASSED a.py::test_x\n", stderr=b"")

    monkeypatch.setattr(container, "_docker", _fake)
    dest = tmp_path / "eval.log"
    log = ct.run_eval_in_container(
        container.ContainerHandle("i", "c", "s"),
        spec_test_cmd="pytest -rA", test_ids=["a.py::test_x"],
        eval_env={"LANG": "en_US.UTF-8"}, log_dest=str(dest),
    )
    assert "PASSED a.py::test_x" in log and dest.read_text() == log
    assert "activate" in captured["script"] and "testbed" in captured["script"]
    assert "export LANG=" in captured["script"]
    assert "pytest -rA a.py::test_x" in captured["script"]


def test_gold_patch_gate_orchestrates(monkeypatch, tmp_path) -> None:
    inst = json.loads(FIXTURE.read_text())
    applied = []
    monkeypatch.setattr(ct, "apply_patch_in_container",
                        lambda h, p: applied.append(p) or True)
    monkeypatch.setattr(ct, "run_eval_in_container",
                        lambda h, **kw: "PASSED everything")
    monkeypatch.setattr(ct.official_grade, "grade",
                        lambda instance, log, **kw: {"resolution": "RESOLVED_FULL"})
    res = ct.gold_patch_gate(container.ContainerHandle("i", "c", "s"), inst,
                             spec_test_cmd="pytest -rA", log_dest=str(tmp_path / "l"))
    assert res["resolution"] == "RESOLVED_FULL"
    # gold patch applied before the test patch.
    assert applied == [inst["patch"], inst["test_patch"]]


def test_grade_agent_run_checks_no_leak_then_grades(monkeypatch, tmp_path) -> None:
    inst = json.loads(FIXTURE.read_text())
    order = []
    import swebench.container_agent as ca
    monkeypatch.setattr(ca, "assert_no_leak",
                        lambda h, test_patch=None: order.append("no_leak"))
    monkeypatch.setattr(ct, "apply_patch_in_container",
                        lambda h, p: order.append("apply") or True)
    monkeypatch.setattr(ct, "run_eval_in_container", lambda h, **kw: order.append("eval") or "log")
    monkeypatch.setattr(ct.official_grade, "grade",
                        lambda instance, log, **kw: {"resolution": "RESOLVED_FULL"})
    res = ct.grade_agent_run(container.ContainerHandle("i", "c", "s"), inst,
                             spec_test_cmd="pytest -rA", log_dest=str(tmp_path / "l"))
    assert res["resolution"] == "RESOLVED_FULL"
    # no-leak runs BEFORE the test patch is applied (can't leak the held-out test).
    assert order == ["no_leak", "apply", "eval"]


def test_resolve_image_digest_parses(monkeypatch) -> None:
    monkeypatch.setattr(container, "_docker",
                        lambda args, **kw: types.SimpleNamespace(
                            returncode=0, stdout=b"repo@sha256:abc|amd64\n", stderr=b""))
    d = container.resolve_image_digest("repo:latest")
    assert d == {"ref": "repo:latest", "digest": "repo@sha256:abc", "arch": "amd64"}


# --------------------------------------------------------------------------
# Integration: real gold gate (Docker + official venv)
# --------------------------------------------------------------------------

def _docker_available() -> bool:
    try:
        return subprocess.run(["docker", "version"], capture_output=True, timeout=15).returncode == 0
    except Exception:
        return False


def _official_venv_available() -> bool:
    from swebench import official_grade as og
    try:
        og.ensure_official_venv(create=False)
        return True
    except og.OfficialGradeError:
        return False


@pytest.mark.integration
@pytest.mark.skipif(not _docker_available(), reason="docker not available")
@pytest.mark.skipif(not _official_venv_available(),
                    reason="official swebench venv not available (ONLYCODES_SWEBENCH_VENV)")
def test_gold_gate_resolves_full_on_image_path() -> None:
    from swebench import container_agent as ca, specs
    inst = json.loads(FIXTURE.read_text())
    img = container.official_image_for(inst["instance_id"])
    if not container.image_present(img):
        pytest.skip(f"image not present: {img}")
    snapshot = container.prepared_tag(inst["instance_id"])
    if container.image_present(snapshot):
        pytest.skip(f"would clobber existing snapshot: {snapshot}")

    spec = specs.spec_for(inst["repo"], inst["version"])
    handle = None
    try:
        prepared = container.prepare_instance(
            inst["instance_id"], force=True,
            post_strip_exec=ca.agent_user_setup_commands())
        # Digest is resolvable + records arch (integrity criterion).
        dig = container.resolve_image_digest(prepared.base_image)
        assert dig["arch"] in ("amd64", "x86_64") and "sha256:" in dig["digest"]

        handle = container.start_arm_container(prepared)
        import tempfile
        log = os.path.join(tempfile.mkdtemp(), "gold_eval.log")
        res = ct.gold_patch_gate(handle, inst, spec_test_cmd=spec["test_cmd"],
                                 eval_env=specs.eval_env(spec), log_dest=log, timeout=600)
        assert res["resolution"] == "RESOLVED_FULL", (
            f"gold patch should fully resolve a faithful image; got {res['resolution']}"
        )
    finally:
        if handle is not None:
            container.teardown(handle)
        subprocess.run(["docker", "rmi", "-f", snapshot], capture_output=True)
