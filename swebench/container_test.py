"""In-container test execution + gold-patch fidelity gate (C5 #319).

Productionises the real-solve spike: after the agent (and C4b's no-leak scan),
apply the held-out ``test_patch`` to ``/testbed``, run the spec's test command
over ``FAIL_TO_PASS + PASS_TO_PASS`` in the testbed conda env, capture the log to
the host, and grade it with the **official** parsers (:mod:`swebench.official_grade`).

The eval command is the faithful SWE-bench one: ``<spec test_cmd> <directives>``,
where the directives are the test FILES touched by the ``test_patch`` (via
:func:`eval_directives`, ported from the official harness) — NOT the F2P/P2P
method-ids.  pytest accepts node-ids so the old method-id form worked for pytest
repos, but non-pytest runners (django ``runtests.py``, etc.) reject it and select
zero tests (#335).  The per-test ``PASSED``/``FAILED`` lines are what
``MAP_REPO_TO_PARSER`` consumes; the official parser then extracts the F2P/P2P
statuses, so resolution still checks both transitions (bug tests flip
red->green, regression tests stay green) regardless of how many tests the
directives run.
"""

from __future__ import annotations

import re
import shlex

from swebench import container, official_grade
from swebench.container import ContainerHandle
from swebench.container_agent import AGENT_USER, AGENT_HOME, TESTBED_ENV


class InContainerTestError(RuntimeError):
    """Applying a patch or running the eval in-container failed irrecoverably."""


def apply_patch_in_container(handle: ContainerHandle, patch_text: str) -> bool:
    """``git apply`` ``patch_text`` inside ``/testbed`` as the agent user.

    Used for both the held-out **test** patch (post-agent grading) and the
    **gold** patch (fidelity gate).  If a straight apply fails — e.g. a code_only
    agent edited a file the test patch also touches — reset that patch's target
    files to HEAD and retry, mirroring ``harness.apply_test_patch``.  Returns
    ``True`` on success.
    """
    cid = handle.container_id
    base = ["exec", "-i", "-u", AGENT_USER, "-w", "/testbed", cid]
    if container._docker(base + ["git", "apply", "-v", "-"],
                         check=False, input_bytes=patch_text.encode()).returncode == 0:
        return True
    # Contamination fallback: reset the patch's targets, then retry.
    targets = _patch_targets(patch_text)
    if targets:
        container._docker(
            ["exec", "-u", AGENT_USER, "-w", "/testbed", cid,
             "git", "checkout", "HEAD", "--", *targets], check=False)
        if container._docker(base + ["git", "apply", "-v", "-"],
                             check=False, input_bytes=patch_text.encode()).returncode == 0:
            return True
    return False


def _patch_targets(patch_text: str) -> list[str]:
    """Files a unified diff touches (``+++ b/<path>`` lines)."""
    out: list[str] = []
    for line in patch_text.splitlines():
        if line.startswith("+++ "):
            p = line[4:].strip()
            if p.startswith("b/"):
                p = p[2:]
            if p and p != "/dev/null":
                out.append(p)
    return out


# Non-test file extensions, mirrored from swebench==4.1.0
# (harness/constants NON_TEST_EXTS) — the grader package pinned in
# :mod:`official_grade`.  Keep in sync if PINNED_SWEBENCH changes.
_NON_TEST_EXTS = (".json", ".png", "csv", ".txt", ".md", ".jpg", ".jpeg",
                  ".pkl", ".yml", ".yaml", ".toml")
_DIFF_PAT = re.compile(r"diff --git a/.* b/(.*)")


def eval_directives(instance: dict) -> list[str]:
    """Test-selection directives for the eval command, derived the **official**
    way: the test FILES touched by the held-out ``test_patch`` — NOT the
    FAIL_TO_PASS/PASS_TO_PASS method-ids.

    Ported verbatim from ``swebench.harness.test_spec.python.get_test_directives``
    (swebench==4.1.0, the package pinned in :mod:`official_grade`) so our test
    selection matches the grader **by construction** (#335).  pytest accepts
    node-ids, so the old "append the method-ids" approach happened to work for
    pytest repos; but django's ``runtests.py`` (and other non-pytest runners)
    reject that format and select **zero** tests -> false ``RESOLVED_NO``.

    An empty result (e.g. the test_patch touched only data files) means "run the
    whole suite" — which the official harness also does; the parser then extracts
    the F2P/P2P statuses from the full output.  By construction every F2P/P2P test
    lies within this selection (that is how the benchmark measured them).
    """
    repo = instance.get("repo", "")
    # seq2seq repos use a fixed test file.
    if repo == "swe-bench/humaneval":
        return ["test.py"]
    directives = _DIFF_PAT.findall(instance.get("test_patch") or "")
    directives = [d for d in directives
                  if not any(d.endswith(ext) for ext in _NON_TEST_EXTS)]
    # Django: tests/foo/bar.py -> foo.bar (strip ext + "tests/" prefix, / -> .).
    if repo == "django/django":
        transformed = []
        for d in directives:
            if d.endswith(".py"):
                d = d[: -len(".py")]
            if d.startswith("tests/"):
                d = d[len("tests/"):]
            transformed.append(d.replace("/", "."))
        directives = transformed
    return directives


def build_eval_command(spec_test_cmd: str, test_ids: list[str]) -> str:
    """``<spec test_cmd> <quoted directives>`` — the faithful SWE-bench eval line.

    ``test_ids`` are the :func:`eval_directives` (test files/modules), not
    method-ids.  An empty list yields the bare ``spec_test_cmd`` (run the whole
    suite), matching the official harness."""
    ids = " ".join(shlex.quote(t) for t in test_ids)
    return f"{spec_test_cmd} {ids}".strip()


def _activate(testbed_env: str) -> str:
    """Shell snippet that activates the testbed conda env (two ways, for image
    layout drift)."""
    return (f"source {testbed_env}/bin/activate 2>/dev/null || "
            f"source /opt/miniconda3/bin/activate {testbed_env.rsplit('/', 1)[-1]}\n")


def reinstall_in_container(
    handle: ContainerHandle,
    install_cmd: str,
    *,
    testbed_env: str = TESTBED_ENV,
    timeout: float = 1800,
) -> None:
    """Run the spec's ``install`` step (e.g. ``pip install -e .[test]``) in the
    testbed env, **as root**.

    This is the official eval_script's install step, which we otherwise skip.
    Skipping it diverges from a faithful SWE-bench eval: it regenerates package
    metadata and installs declared deps that may be missing from the published
    image (e.g. pylint's ``appdirs``) — without it the gold patch can fail to
    resolve a faithfully-resolvable instance (#308). Run as root because it
    writes to the root-owned conda ``site-packages``; failures are non-fatal
    (the eval that follows surfaces any real breakage)."""
    script = f"{_activate(testbed_env)}cd /testbed\n{install_cmd}\n"
    container._docker(
        ["exec", "-i", handle.container_id, "bash", "-ls"],   # default user = root
        check=False, timeout=timeout, input_bytes=script.encode(),
    )


def run_eval_in_container(
    handle: ContainerHandle,
    *,
    spec_test_cmd: str,
    test_ids: list[str],
    eval_env: dict[str, str] | None = None,
    log_dest: str,
    testbed_env: str = TESTBED_ENV,
    timeout: float = 1800,
    install_cmd: str | None = None,
) -> str:
    """Run the eval command in the testbed conda env, capturing the combined log
    to the host file ``log_dest`` (returns the log text).

    Runs as the agent user, cwd ``/testbed``, with the testbed env activated and
    the spec's ``eval_env`` (locale pins etc.) exported.  When ``install_cmd`` is
    given, the official eval_script's install step runs first (as root, via
    :func:`reinstall_in_container`) for a faithful eval.  The log is what
    :func:`swebench.official_grade.grade` parses.
    """
    if install_cmd:
        reinstall_in_container(handle, install_cmd, testbed_env=testbed_env, timeout=timeout)
    exports = "".join(
        f"export {k}={shlex.quote(v)}\n" for k, v in (eval_env or {}).items()
    )
    cmd = build_eval_command(spec_test_cmd, test_ids)
    script = (
        f"{_activate(testbed_env)}"
        f"{exports}cd /testbed\n{cmd}\n"
    )
    # Feed the script over stdin (``bash -ls``), NOT as a ``-lc`` argv element.
    # High-test-count instances (e.g. django-10097: 1870 ids) produce a >128 KiB
    # eval line, and a single argv string is capped at MAX_ARG_STRLEN (32 pages =
    # 128 KiB) by execve -> E2BIG / "Argument list too long" before docker starts
    # (#333). Over stdin the per-arg cap does not apply; the ids still reach the
    # test command as separate words, well under the ~2 MB total ARG_MAX.
    proc = container._docker(
        ["exec", "-i", "-u", AGENT_USER, "-e", f"HOME={AGENT_HOME}", handle.container_id,
         "bash", "-ls"],
        check=False, timeout=timeout, input_bytes=script.encode(),
    )
    # Combine stdout + stderr: pytest writes results to stdout, but unittest-based
    # runners (django ``runtests.py``) write per-test results to STDERR. The
    # official parsers consume the combined log, so capturing stdout alone loses
    # every django result -> all F2P/P2P appear missing -> false RESOLVED_NO (#335).
    out = (proc.stdout or b"").decode("utf-8", "replace")
    err = (proc.stderr or b"").decode("utf-8", "replace")
    log = out + err
    with open(log_dest, "w") as f:
        f.write(log)
    return log


def gold_patch_gate(
    handle: ContainerHandle,
    instance: dict,
    *,
    spec_test_cmd: str,
    eval_env: dict[str, str] | None = None,
    log_dest: str,
    timeout: float = 1800,
    install_cmd: str | None = None,
) -> dict:
    """Fidelity gate (#322 on the image path): apply the **gold** patch + the
    held-out test patch to a pristine ``/testbed``, run the eval, and grade.

    A faithful image returns ``RESOLVED_FULL`` (gold flips FAIL_TO_PASS->pass and
    PASS_TO_PASS stay green).  Anything else means the image env drifted from the
    benchmark — surfaced via the returned grade (caller asserts/loud-logs).
    Pass ``install_cmd`` (the spec's install step) for a faithful eval. Returns
    the :func:`official_grade.grade` result.
    """
    if not apply_patch_in_container(handle, instance["patch"]):
        raise InContainerTestError("gold patch did not apply cleanly in-container")
    if not apply_patch_in_container(handle, instance["test_patch"]):
        raise InContainerTestError("held-out test patch did not apply cleanly")

    log = run_eval_in_container(
        handle, spec_test_cmd=spec_test_cmd, test_ids=eval_directives(instance),
        eval_env=eval_env, log_dest=log_dest, timeout=timeout, install_cmd=install_cmd,
    )
    return official_grade.grade(instance, log)


def grade_agent_run(
    handle: ContainerHandle,
    instance: dict,
    *,
    spec_test_cmd: str,
    eval_env: dict[str, str] | None = None,
    log_dest: str,
    verify_no_leak: bool = True,
    timeout: float = 1800,
    install_cmd: str | None = None,
) -> dict:
    """Grade an arm: the agent has already edited ``/testbed``; apply the held-out
    test patch, run the eval over the test_patch's directives, and grade.

    The agent-side counterpart to :func:`gold_patch_gate` (no gold patch — the
    agent's own diff is the change under test).  When ``verify_no_leak`` (C4b),
    asserts the held-out test wasn't visible to the agent **before** applying it.
    Returns the :func:`official_grade.grade` result (``RESOLVED_FULL`` == solved).
    """
    if verify_no_leak:
        from swebench.container_agent import assert_no_leak
        assert_no_leak(handle, test_patch=instance.get("test_patch"))
    if not apply_patch_in_container(handle, instance["test_patch"]):
        raise InContainerTestError("held-out test patch did not apply cleanly")

    log = run_eval_in_container(
        handle, spec_test_cmd=spec_test_cmd, test_ids=eval_directives(instance),
        eval_env=eval_env, log_dest=log_dest, timeout=timeout, install_cmd=install_cmd,
    )
    return official_grade.grade(instance, log)
