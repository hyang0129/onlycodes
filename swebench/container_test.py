"""In-container test execution + gold-patch fidelity gate (C5 #319).

Productionises the real-solve spike: after the agent (and C4b's no-leak scan),
apply the held-out ``test_patch`` to ``/testbed``, run the spec's test command
over ``FAIL_TO_PASS + PASS_TO_PASS`` in the testbed conda env, capture the log to
the host, and grade it with the **official** parsers (:mod:`swebench.official_grade`).

The eval command is the faithful SWE-bench one: ``<spec test_cmd> <test ids>``
(e.g. ``pytest -rA <node ids>`` for pytest repos; ``./tests/runtests.py ...
<dotted ids>`` for django).  The ``-rA``-style per-test ``PASSED``/``FAILED``
lines are what ``MAP_REPO_TO_PARSER`` consumes.

Grading runs over the union of FAIL_TO_PASS + PASS_TO_PASS so resolution checks
both transitions (bug tests flip red->green, regression tests stay green).
"""

from __future__ import annotations

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


def build_eval_command(spec_test_cmd: str, test_ids: list[str]) -> str:
    """``<spec test_cmd> <quoted test ids>`` — the faithful SWE-bench eval line."""
    ids = " ".join(shlex.quote(t) for t in test_ids)
    return f"{spec_test_cmd} {ids}".strip()


def run_eval_in_container(
    handle: ContainerHandle,
    *,
    spec_test_cmd: str,
    test_ids: list[str],
    eval_env: dict[str, str] | None = None,
    log_dest: str,
    testbed_env: str = TESTBED_ENV,
    timeout: float = 1800,
) -> str:
    """Run the eval command in the testbed conda env, capturing the combined log
    to the host file ``log_dest`` (returns the log text).

    Runs as the agent user, cwd ``/testbed``, with the testbed env activated and
    the spec's ``eval_env`` (locale pins etc.) exported.  The log is what
    :func:`swebench.official_grade.grade` parses.
    """
    exports = "".join(
        f"export {k}={shlex.quote(v)}\n" for k, v in (eval_env or {}).items()
    )
    cmd = build_eval_command(spec_test_cmd, test_ids)
    script = (
        f"source {testbed_env}/bin/activate 2>/dev/null || "
        f"source /opt/miniconda3/bin/activate {testbed_env.rsplit('/', 1)[-1]}\n"
        f"{exports}cd /testbed\n{cmd}\n"
    )
    proc = container._docker(
        ["exec", "-u", AGENT_USER, "-e", f"HOME={AGENT_HOME}", handle.container_id,
         "bash", "-lc", script],
        check=False, timeout=timeout,
    )
    log = (proc.stdout or b"").decode("utf-8", "replace")
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
) -> dict:
    """Fidelity gate (#322 on the image path): apply the **gold** patch + the
    held-out test patch to a pristine ``/testbed``, run the eval, and grade.

    A faithful image returns ``RESOLVED_FULL`` (gold flips FAIL_TO_PASS->pass and
    PASS_TO_PASS stay green).  Anything else means the image env drifted from the
    benchmark — surfaced via the returned grade (caller asserts/loud-logs).
    Returns the :func:`official_grade.grade` result.
    """
    if not apply_patch_in_container(handle, instance["patch"]):
        raise InContainerTestError("gold patch did not apply cleanly in-container")
    if not apply_patch_in_container(handle, instance["test_patch"]):
        raise InContainerTestError("held-out test patch did not apply cleanly")

    test_ids = _coerce_ids(instance.get("FAIL_TO_PASS")) + _coerce_ids(instance.get("PASS_TO_PASS"))
    log = run_eval_in_container(
        handle, spec_test_cmd=spec_test_cmd, test_ids=test_ids,
        eval_env=eval_env, log_dest=log_dest, timeout=timeout,
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
) -> dict:
    """Grade an arm: the agent has already edited ``/testbed``; apply the held-out
    test patch, run the eval over FAIL_TO_PASS + PASS_TO_PASS, and grade.

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

    test_ids = _coerce_ids(instance.get("FAIL_TO_PASS")) + _coerce_ids(instance.get("PASS_TO_PASS"))
    log = run_eval_in_container(
        handle, spec_test_cmd=spec_test_cmd, test_ids=test_ids,
        eval_env=eval_env, log_dest=log_dest, timeout=timeout,
    )
    return official_grade.grade(instance, log)


def _coerce_ids(v) -> list[str]:
    import json
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return [v]
    return list(v or [])
