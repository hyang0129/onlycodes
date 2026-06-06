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


def test_build_eval_command_empty_directives_runs_whole_suite() -> None:
    # no directives (test_patch touched only data files) -> bare test_cmd.
    assert ct.build_eval_command("pytest -rA", []) == "pytest -rA"


def test_eval_directives_pytest_file_passthrough() -> None:
    inst = {"repo": "psf/requests",
            "test_patch": "diff --git a/test_requests.py b/test_requests.py\n"
                          "--- a/test_requests.py\n+++ b/test_requests.py\n@@ -1 +1 @@\n"}
    # pytest repos: the test FILE is the directive (not the F2P/P2P method-ids).
    assert ct.eval_directives(inst) == ["test_requests.py"]


def test_eval_directives_django_transform() -> None:
    inst = {"repo": "django/django",
            "test_patch": "diff --git a/tests/auth_tests/test_validators.py "
                          "b/tests/auth_tests/test_validators.py\n@@ -1 +1 @@\n"}
    # tests/foo/bar.py -> foo.bar (django runtests label), the #335 fix.
    assert ct.eval_directives(inst) == ["auth_tests.test_validators"]


def test_eval_directives_filters_non_test_files_to_empty() -> None:
    # django-10097's real shape: test_patch touches only data files -> [] -> full suite.
    inst = {"repo": "django/django",
            "test_patch": "diff --git a/tests/validators/invalid_urls.txt "
                          "b/tests/validators/invalid_urls.txt\n@@ -1 +1 @@\n"
                          "diff --git a/tests/validators/valid_urls.txt "
                          "b/tests/validators/valid_urls.txt\n@@ -1 +1 @@\n"}
    assert ct.eval_directives(inst) == []


def test_eval_directives_humaneval_fixed() -> None:
    assert ct.eval_directives({"repo": "swe-bench/humaneval", "test_patch": ""}) == ["test.py"]


def test_gold_patch_gate_feeds_directives_not_method_ids(monkeypatch, tmp_path) -> None:
    inst = {"repo": "django/django", "patch": "P", "version": "2.2",
            "FAIL_TO_PASS": ["test_x (auth_tests.test_validators.T)"],
            "PASS_TO_PASS": ["test_y (auth_tests.test_validators.T)"],
            "test_patch": "diff --git a/tests/auth_tests/test_validators.py "
                          "b/tests/auth_tests/test_validators.py\n@@ -1 +1 @@\n"}
    seen = {}
    monkeypatch.setattr(ct, "apply_patch_in_container", lambda h, p: True)
    monkeypatch.setattr(ct, "run_eval_in_container",
                        lambda h, **kw: seen.update(test_ids=kw["test_ids"]) or "log")
    monkeypatch.setattr(ct.official_grade, "grade",
                        lambda instance, log, **kw: {"resolution": "RESOLVED_FULL"})
    ct.gold_patch_gate(container.ContainerHandle("i", "c", "s"), inst,
                       spec_test_cmd="./tests/runtests.py", log_dest=str(tmp_path / "l"))
    # directive (transformed file), NOT the unittest-format method-ids.
    assert seen["test_ids"] == ["auth_tests.test_validators"]


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
        captured["args"] = args
        captured["script"] = (kw.get("input_bytes") or b"").decode()  # piped via stdin
        return types.SimpleNamespace(returncode=0, stdout=b"PASSED a.py::test_x\n", stderr=b"")

    monkeypatch.setattr(container, "_docker", _fake)
    dest = tmp_path / "eval.log"
    log = ct.run_eval_in_container(
        container.ContainerHandle("i", "c", "s"),
        spec_test_cmd="pytest -rA", test_ids=["a.py::test_x"],
        eval_env={"LANG": "en_US.UTF-8"}, log_dest=str(dest),
    )
    assert "PASSED a.py::test_x" in log and dest.read_text() == log
    # script goes over stdin (``bash -ls`` + ``-i``), never as a ``-lc`` argv element (#333).
    assert "-i" in captured["args"] and captured["args"][-2:] == ["bash", "-ls"]
    assert "activate" in captured["script"] and "testbed" in captured["script"]
    assert "export LANG=" in captured["script"]
    assert "pytest -rA a.py::test_x" in captured["script"]


def test_run_eval_merges_stderr_for_unittest_runners(monkeypatch, tmp_path) -> None:
    # django/unittest writes per-test results to stderr; the combined log must
    # include them or the parser sees no results -> false RESOLVED_NO (#335).
    def _fake(args, **kw):
        return types.SimpleNamespace(
            returncode=1, stdout=b"Creating test database...\n",
            stderr=b"test_x (auth_tests.T) ... ok\nRan 1 test in 0.1s\n")
    monkeypatch.setattr(container, "_docker", _fake)
    dest = tmp_path / "eval.log"
    log = ct.run_eval_in_container(
        container.ContainerHandle("i", "c", "s"),
        spec_test_cmd="./tests/runtests.py", test_ids=["auth_tests.test_x"],
        eval_env={}, log_dest=str(dest),
    )
    assert "Creating test database" in log  # stdout
    assert "test_x (auth_tests.T) ... ok" in log and "Ran 1 test" in log  # stderr
    assert dest.read_text() == log


def test_run_eval_large_id_list_stays_under_max_arg_strlen(monkeypatch, tmp_path) -> None:
    """High-test-count instances must not blow MAX_ARG_STRLEN (128 KiB per argv
    string). With 1870 django-style ids the eval line is ~150 KiB; it must travel
    over stdin, leaving every individual argv element small (#333)."""
    MAX_ARG_STRLEN = 128 * 1024
    captured = {}

    def _fake(args, **kw):
        captured["args"] = args
        captured["script"] = (kw.get("input_bytes") or b"").decode()
        return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(container, "_docker", _fake)
    ids = [f"tests.deeply.nested.module.path.SomeReallyLongTestClassName"
           f".test_case_with_a_descriptive_name_number_{i:04d}" for i in range(1870)]
    ct.run_eval_in_container(
        container.ContainerHandle("i", "c", "s"),
        spec_test_cmd="pytest -rA", test_ids=ids,
        eval_env={}, log_dest=str(tmp_path / "eval.log"),
    )
    # the giant id list lands in the stdin script, not argv...
    assert len(captured["script"].encode()) > MAX_ARG_STRLEN
    # ...and no single argv string is anywhere near the per-arg cap.
    assert all(len(a.encode()) < MAX_ARG_STRLEN for a in captured["args"])
    assert all(id_ in captured["script"] for id_ in (ids[0], ids[-1]))


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
