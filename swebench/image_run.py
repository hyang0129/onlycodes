"""Image-runtime arm orchestrator (C5 #319 wiring; verbatim grading #354).

Runs SWE-bench arms end-to-end on the **official prebuilt images** in two
decoupled passes (``docs/VERBATIM_GRADING_PLAN.md``):

**Agent pass (Concern A — our contribution).** For each (instance, arm, run):

    image_store.ensure_image       # pull-by-digest + reuse-forever store
    container.prepare_instance     # strip /testbed -> snapshot (+ agent user)
    container.start_arm_container   # fresh container per (arm, run) from the snapshot
    container_agent.stage_arm       # mount runtime volume + creds + exec-server
    container_agent.run_agent       # one agent turn in-container (restricted, net-iso)
    container_agent.extract_agent_diff  # capture the agent's diff = model_patch

The partial record is written with ``verdict: "PENDING"``; no grading happens
here, and the agent never shares a container with the held-out test.

**Grading pass (Concern B — verbatim SWE-bench).** Per (arm, run), the captured
``model_patch`` set is graded byte-for-byte through
``grading_official.grade_predictions`` (official ``run_evaluation`` over the
**unmodified** image). The verdict is merged back into each partial record.

This is a **dedicated** agent orchestrator — deliberately separate from the
overlay path's loop in ``run.py`` (no surgery on that code). The agent pass runs
``agent_max_workers`` instances concurrently (``--parallel``); instances are
disjoint (own image, snapshot, container, and output files), so the only shared
state is the predictions dict (lock-guarded). Work is submitted in
repo+version-grouped order so same-repo images are reused. The agent pass is
API-bound (the agent turn blocks on the model API while the GIL is released), so
threads give real parallelism. The grading pass parallelism is independent
(``grading_max_workers``).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from swebench import container, container_agent, grading_official, image_store, specs
from swebench.container_agent import runtime_volume_spec
from swebench.models import Problem
from swebench.run_audit import is_account_limited


class AccountLimitHalt(Exception):
    """Raised when the agent hits an account rate-limit / quota (HTTP 429) and the
    run backs off. The clean agent work captured so far is graded and committed
    first; rate-limited instances stay PENDING so a later ``--resume`` re-runs
    only them. The run does **not** auto-retry — the operator approves the resume
    once quota recovers (or maxmanager rotates credentials)."""

    def __init__(self, n_limited: int, n_done: int):
        self.n_limited = n_limited
        self.n_done = n_done
        super().__init__(
            f"account rate-limit (429) hit: backed off after {n_done} clean run(s); "
            f"{n_limited} rate-limited instance(s) left PENDING. "
            f"Resume with --resume once quota recovers.")

#: SWE-bench image canonical paths.
_TESTBED = "/testbed"
_TESTBED_PY = "/opt/miniconda3/envs/testbed/bin/python"

#: Terminal verdicts that --resume treats as "done" (matches the overlay path's
#: ``run._is_triple_complete``). ``PENDING`` (agent ran, grading interrupted),
#: ``ERROR`` (grader/patch error), and a missing record are all re-run.
_RESUME_TERMINAL = {"PASS", "FAIL", "env_fail"}


def _record_verdict(results_dir: str, instance_id: str, arm: str, run_idx: int) -> str | None:
    """Terminal verdict already recorded for a triple, or ``None`` if the record
    is absent/unreadable/PENDING. The image record stores the verdict in its meta
    line (first line), rewritten in place by :func:`_finalize_record` at grade time."""
    path = Path(results_dir) / f"{instance_id}_{arm}_run{run_idx}.jsonl"
    if not path.is_file():
        return None
    try:
        with path.open() as f:
            meta = json.loads(f.readline())
    except (OSError, ValueError):
        return None
    v = meta.get("verdict")
    return v if v in _RESUME_TERMINAL else None


def _build_prompt(problem: Problem, arm: str) -> str:
    """Faithful in-container prompt (mirrors ``run.py`` for /testbed paths)."""
    parts = [
        f"You are working in the repository at: {_TESTBED}\n",
        f"The project's Python interpreter and dependencies are pre-installed at: {_TESTBED_PY}\n",
    ]
    if arm in ("onlycode", "code_only"):
        parts.append(
            "A `codebox` helper module is auto-imported into your cwd. Workflow: "
            "OUTLINE -> GREP -> READ_LINES -> EDIT_REPLACE -> RUN.\n"
            "  import codebox\n"
            "  codebox.outline(path); codebox.read_lines(path, 200, 250); codebox.peek(path, 182, around=10)\n"
            "  codebox.grep('pattern', path); codebox.source_of(symbol, root); codebox.files(root)\n"
            "  codebox.edit_replace(path, old, new)  # exact-once swap\n"
            "  codebox.write(path, content); codebox.run('cmd', tail=20)\n"
            "Do NOT use subprocess to run tests; use codebox.run. Do NOT hand-build edits with re.sub.\n"
            "The execute_code interpreter is a PERSISTENT REPL keyed by cwd: state survives across calls.\n"
        )
    parts.append("Fix the following bug. Make the minimal change needed.\n\n" + problem.problem_statement)
    return "\n".join(parts)


def _grading_instance(problem: Problem, test_patch_text: str) -> dict:
    """Build the SWE-bench instance dict the official grader needs from a Problem.

    The agent arm grades against the agent's own diff, so the gold ``patch`` is
    not required (``make_test_spec`` builds without it — verified).

    .. note::
       No longer used by the image runtime's grading path (verbatim grading
       supplies test_patch/F2P/P2P from the official dataset, #354). Retained
       because ``scripts/{diagnose_drift,verify_agent_grade,validate_verified_image}.py``
       still import it (Phase 4 collapses those scripts).
    """
    return {
        "instance_id": problem.instance_id,
        "repo": problem.repo_slug,
        "version": problem.version,
        "base_commit": problem.base_commit,
        "environment_setup_commit": problem.environment_setup_commit or problem.base_commit,
        "problem_statement": problem.problem_statement,
        "FAIL_TO_PASS": problem.fail_to_pass or [],
        "PASS_TO_PASS": problem.pass_to_pass or [],
        "test_patch": test_patch_text,
        "patch": "",
    }


def _read_test_patch(problem: Problem, root: Path) -> str:
    """Read a problem's vendored test patch file (host-side).

    .. note::
       Like :func:`_grading_instance`, no longer used by the image runtime
       itself; kept for the validation scripts (Phase 4).
    """
    if not problem.patch_file:
        return ""
    p = root / problem.patch_file
    return p.read_text() if p.is_file() else ""


def _extract_cost_turns(transcript_path: str, *, agent_surface: str = "claude_code",
                        codex_model: str | None = None) -> tuple[float | None, int | None]:
    """(cost_usd, num_turns) from the transcript. Codex uses the runner's
    token-based estimator (its ``--json`` shape differs from Claude's); its cost
    needs a ``meta`` line naming the model to hit the price table, which the raw
    ``codex exec`` stdout lacks — so we prepend one before estimating."""
    if agent_surface == "codex_cli":
        from swebench.runner import CodexRunner
        try:
            lines = Path(transcript_path).read_text().splitlines()
            meta = json.dumps({"type": "meta", "model": codex_model or "gpt-5.5"})
            primed = transcript_path + ".priced.jsonl"
            Path(primed).write_text(meta + "\n" + "\n".join(lines) + "\n")
            return CodexRunner().extract_metadata(Path(primed))
        except Exception:  # noqa: BLE001 — cost is best-effort
            return (None, None)
    cost = turns = None
    try:
        for line in Path(transcript_path).read_text().splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            rec = json.loads(line)
            if rec.get("type") == "result":
                cost = rec.get("total_cost_usd", cost)
                turns = rec.get("num_turns", turns)
    except (OSError, json.JSONDecodeError):
        pass
    return cost, turns


def run_one_arm(
    problem: Problem,
    *,
    arm: str,
    run_idx: int,
    prepared: container.PreparedImage,
    digest_info: dict,
    results_dir: str,
    agent_surface: str = "claude_code",
    codex_model: str | None = None,
    wall_timeout: int = 1800,
    _now=None,
) -> dict:
    """Run one (arm, run) agent turn in a fresh container; write the PENDING record.

    Agent pass only (Concern A): runs the agent, captures its diff
    (``model_patch``) via :func:`container_agent.extract_agent_diff`, and writes a
    partial record with ``verdict="PENDING"`` / ``resolution=None``. Grading is the
    separate pass (:func:`run_image_arms`).

    Returns a prediction dict ``{instance_id, arm, run_idx, model_patch,
    record_path}`` the orchestrator uses to build the per-arm grading batch.
    """
    handle = container.start_arm_container(prepared, volumes=[runtime_volume_spec()])
    transcript = os.path.join(tempfile.mkdtemp(prefix="img-arm-"), "transcript.jsonl")
    model_patch = ""
    cost, turns = None, None
    # ``codex_model`` is codex-specific (default "gpt-5.5"). Only pass it to the
    # codex surface; for claude_code, model=None lets the runner use its pinned
    # claude model (passing gpt-5.5 to claude is a 404). #354.
    model = codex_model if agent_surface == "codex_cli" else None
    try:
        container_agent.stage_arm(handle, surface=agent_surface, arm=arm, model=model)
        rc = container_agent.run_agent(
            handle, arm=arm, prompt=_build_prompt(problem, arm),
            result_path=transcript, wall_timeout=wall_timeout,
            surface=agent_surface, model=model,
        )
        diff_dest = os.path.join(os.path.dirname(transcript), "model_patch.diff")
        # Empty-diff case (agent made no change) yields an empty string — fine.
        model_patch = container_agent.extract_agent_diff(handle, diff_dest)
        cost, turns = _extract_cost_turns(transcript, agent_surface=agent_surface,
                                          codex_model=codex_model)
        logging.info("image_run %s %s run%d: rc=%s patch_bytes=%d (PENDING grade)",
                     problem.instance_id, arm, run_idx, rc, len(model_patch))
    finally:
        record_path = _write_record(
            results_dir, problem, arm, run_idx,
            transcript=transcript, verdict="PENDING", resolution=None,
            model_patch=model_patch, digest_info=digest_info, cost=cost, turns=turns,
            agent_surface=agent_surface,
            now=_now if _now is not None else time.time(),
        )
        container.teardown(handle)
    return {
        "instance_id": problem.instance_id, "arm": arm, "run_idx": run_idx,
        "model_patch": model_patch, "record_path": record_path,
    }


def _write_record(results_dir, problem, arm, run_idx, *, transcript, verdict, resolution,
                  model_patch, digest_info, cost, turns, agent_surface, now) -> str:
    """Write ``<instance>_<arm>_run<N>.jsonl``: meta line + agent transcript + verdict line.

    Returns the record path so the grading pass can finalize it in place.
    """
    out = os.path.join(results_dir, f"{problem.instance_id}_{arm}_run{run_idx}.jsonl")
    meta = {
        "type": "meta", "instance_id": problem.instance_id, "arm": arm, "run": run_idx,
        "agent_surface": agent_surface, "runtime": "image",
        "image_digest": digest_info.get("digest"), "image_arch": digest_info.get("arch"),
        "model_patch": model_patch,
        "resolution": resolution, "verdict": verdict,
        "total_cost_usd": cost, "num_turns": turns, "graded_utc": now,
    }
    os.makedirs(results_dir, exist_ok=True)
    with open(out, "w") as f:
        f.write(json.dumps(meta) + "\n")
        if os.path.isfile(transcript):
            with open(transcript) as t:
                for line in t:
                    if line.strip():
                        f.write(line if line.endswith("\n") else line + "\n")
        f.write(json.dumps({"type": "verdict", "verdict": verdict, "resolution": resolution}) + "\n")
    return out


def _finalize_record(record_path: str, verdict: str, resolution) -> None:
    """Merge the grading verdict into a PENDING record, in place.

    Rewrites the meta line's ``verdict``/``resolution`` and replaces the trailing
    verdict line, preserving the transcript lines in between. Final shape stays:
    meta line (with ``model_patch``) -> transcript lines -> verdict line.
    """
    lines = Path(record_path).read_text().splitlines()
    if not lines:
        return
    meta = json.loads(lines[0])
    meta["verdict"] = verdict
    meta["resolution"] = resolution
    # Body = everything between the meta line and the trailing verdict line. The
    # last line is the (PENDING) verdict line we replace; transcript is in between.
    body = lines[1:]
    if body and body[-1].lstrip().startswith("{"):
        try:
            if json.loads(body[-1]).get("type") == "verdict":
                body = body[:-1]
        except json.JSONDecodeError:
            pass
    with open(record_path, "w") as f:
        f.write(json.dumps(meta) + "\n")
        for line in body:
            if line.strip():
                f.write(line + "\n")
        f.write(json.dumps({"type": "verdict", "verdict": verdict, "resolution": resolution}) + "\n")


def _verdict_from_report(report: dict) -> tuple[str, str | None]:
    """Map a ``grade_predictions`` per-instance report to (verdict, resolution).

    ``{"resolved": True}`` -> PASS, error report -> ERROR, otherwise FAIL.
    """
    if report.get("error"):
        return "ERROR", report.get("error")
    if report.get("resolved"):
        return "PASS", "RESOLVED_FULL"
    return "FAIL", None


def run_image_arms(
    problems: list[Problem],
    *,
    arms: list[str],
    num_runs: int,
    results_dir: str,
    agent_binary: str,
    agent_surface: str = "claude_code",
    codex_model: str | None = None,
    wall_timeout: int = 1800,
    agent_max_workers: int = 1,
    grading_max_workers: int = 1,
    resume: bool = False,
    halt_on_rate_limit: bool = True,
    echo=print,
) -> list[tuple[str, str, str]]:
    """Run ``arms`` over ``problems`` on the image runtime in two passes.

    Pass 1 (agent): for each problem x arm x run, pull + prepare + run the agent,
    capturing each ``model_patch`` into a PENDING record. Predictions are grouped
    by ``(arm, run_idx)``. Runs ``agent_max_workers`` problems concurrently
    (default 1 = serial); arms/runs within a problem stay serial (they share the
    instance's prepared snapshot).

    Pass 2 (grading): per ``(arm, run_idx)`` group, grade the captured patches
    verbatim via :func:`grading_official.grade_predictions` (official
    ``run_evaluation``, ``grading_max_workers`` instances in parallel), then merge
    each verdict back into its record via :func:`_finalize_record`.

    Returns ``(instance_id, arm, verdict)`` triples.

    .. todo:: wire ``grading_max_workers`` to a CLI flag (currently a default
       threaded from ``run.py``).
    """
    image_store.registry_login()
    # Populate the shared runtime volume for the chosen surface (#325).
    if agent_surface == "codex_cli":
        container_agent.ensure_codex_runtime()
    else:
        container_agent.ensure_agent_runtime(agent_binary)

    order = {iid: i for i, iid in enumerate(
        image_store.group_by_repo_version([p.instance_id for p in problems]))}
    problems = sorted(problems, key=lambda p: order.get(p.instance_id, 1 << 30))

    # --- Pass 1: agent. Collect predictions grouped by (arm, run_idx). ---
    # FAIL_TO_PASS / test_patch come from the official dataset at grade time, so
    # we no longer skip on missing grading data — only on un-promptable instances.
    #
    # Instances are independent (own image/snapshot/container/output files); the
    # only shared state is ``predictions`` (lock-guarded). ``ensure_image`` raises
    # ``DiskFullError`` when free space drops below the safety margin — on that we
    # set ``stop_event`` so in-flight work drains and no new instance is started,
    # then re-raise after the pool quiesces ("stop and add disk, then --resume").
    predictions: dict[tuple[str, int], list[dict]] = {}
    pred_lock = threading.Lock()
    stop_event = threading.Event()
    disk_full: list[image_store.DiskFullError] = []
    # Account rate-limit (429) back-off: when an agent turn comes back throttled we
    # stop launching new instances, let in-flight drain, grade the clean work, and
    # leave the rate-limited records PENDING for a later --resume.
    rate_limited: list[str] = []

    workers = max(1, agent_max_workers)
    free = image_store.free_disk_gb()
    echo(f"Agent pass: {len(problems)} instance(s) x {len(arms)} arm(s), "
         f"parallel={workers}" + (f", {free:.0f} GB free" if free is not None else ""))

    def _process_problem(problem: Problem) -> None:
        if stop_event.is_set():
            return
        if not problem.problem_statement:
            echo(f"  SKIP {problem.instance_id}: no problem_statement (cannot prompt the agent)")
            return

        # --resume: only run (arm, run) triples without a terminal verdict, and
        # skip the image pull + snapshot entirely when the whole instance is done.
        if resume:
            todo = [(arm, r) for arm in arms for r in range(num_runs)
                    if _record_verdict(results_dir, problem.instance_id, arm, r) is None]
            if not todo:
                echo(f"  SKIP {problem.instance_id}: all triples already complete (--resume)")
                return
        else:
            todo = [(arm, r) for arm in arms for r in range(num_runs)]

        try:
            echo(f"--- Instance: {problem.instance_id} ({problem.repo_slug}@{problem.version}) ---")
            digest_info = image_store.ensure_image(problem.instance_id)
            prepared = container.prepare_instance(
                problem.instance_id,
                post_strip_exec=container_agent.agent_user_setup_commands())
        except image_store.DiskFullError as e:
            disk_full.append(e)
            stop_event.set()
            echo(f"  DISK FULL at {problem.instance_id}: {e} "
                 "— draining in-flight work, starting no new instances")
            return

        for arm, run_idx in todo:
            if stop_event.is_set():
                return
            pred = run_one_arm(
                problem, arm=arm, run_idx=run_idx, prepared=prepared,
                digest_info=digest_info, results_dir=results_dir,
                wall_timeout=wall_timeout, agent_surface=agent_surface,
                codex_model=codex_model,
            )
            # Account-limit (429) back-off: a throttled turn is not a result. Leave
            # its PENDING record for --resume, stop launching new work, and don't
            # grade it. Distinct from a task FAIL or a non-quota api_error.
            if halt_on_rate_limit and is_account_limited(pred["record_path"]):
                with pred_lock:
                    rate_limited.append(pred["instance_id"])
                stop_event.set()
                echo(f"  RATE LIMIT (429) at {problem.instance_id} {arm} run {run_idx} "
                     "— backing off, draining in-flight, no new instances")
                return
            echo(f"  [{problem.instance_id} {arm} run {run_idx}] agent done (PENDING grade)")
            with pred_lock:
                predictions.setdefault((arm, run_idx), []).append(pred)

    if workers == 1:
        for problem in problems:
            if stop_event.is_set():
                break
            _process_problem(problem)
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = [ex.submit(_process_problem, p) for p in problems]
            for fut in as_completed(futures):
                fut.result()  # surface unexpected (non-DiskFull) worker exceptions

    if disk_full:
        # Agent work already captured is on disk as PENDING records; add disk and
        # re-run with --resume. Re-raise so the operator sees the hard stop.
        raise disk_full[0]

    # --- Pass 2: grade verbatim per (arm, run_idx), merge verdicts. ---
    results: list[tuple[str, str, str]] = []
    for (arm, run_idx), preds in predictions.items():
        ids = [p["instance_id"] for p in preds]
        run_id = f"img_{arm}_run{run_idx}_{os.getpid()}_{run_idx}"
        echo(f"--- Grading {len(preds)} prediction(s): {arm} run {run_idx} ---")
        reports = grading_official.grade_predictions(
            [{"instance_id": p["instance_id"], "model_patch": p["model_patch"]} for p in preds],
            run_id=run_id, model_name=arm, max_workers=grading_max_workers,
            instance_ids=ids,
        )
        for pred in preds:
            iid = pred["instance_id"]
            report = reports.get(iid, {"resolved": False, "error": "no report returned"})
            verdict, resolution = _verdict_from_report(report)
            _finalize_record(pred["record_path"], verdict, resolution)
            echo(f"  [{arm} run {run_idx}] {iid}: {verdict}")
            results.append((iid, arm, verdict))

    # Clean work is now graded + committed. If we backed off on an account limit,
    # halt loudly so the operator approves the resume once quota recovers.
    if rate_limited:
        raise AccountLimitHalt(n_limited=len(set(rate_limited)), n_done=len(results))
    return results
