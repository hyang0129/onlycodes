"""Image-runtime arm orchestrator (C5 #319 wiring).

Runs SWE-bench arms end-to-end on the **official prebuilt images**, tying the
merged building blocks into one graded loop (dispatched from ``run.py`` when
``--runtime image``):

    image_store.ensure_image      # pull-by-digest + LRU prune to the disk cap
    container.prepare_instance    # strip /testbed -> snapshot (+ agent user)
    container.start_arm_container  # fresh container per (arm, run) from the snapshot
    container_agent.stage_arm      # mount runtime volume + creds + exec-server
    container_agent.run_agent      # one Claude turn in-container (restricted, net-iso)
    container_test.grade_agent_run # no-leak -> apply test patch -> eval -> official grade

This is a **dedicated, serial** orchestrator — deliberately separate from the
overlay path's serial/parallel loop in ``run.py`` (no surgery on that code).
Instances are processed in repo+version-grouped order so the shared conda layer
is reused before eviction (C3b).

Scope: a working graded ``--runtime image`` arm. Parallelism, ``--resume`` for
the image path, and the Codex surface are follow-ups.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path

from swebench import container, container_agent, container_test, image_store, official_grade, specs
from swebench.container_agent import runtime_volume_spec
from swebench.models import Problem

#: SWE-bench image canonical paths.
_TESTBED = "/testbed"
_TESTBED_PY = "/opt/miniconda3/envs/testbed/bin/python"


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
    not required (``make_test_spec`` builds without it — verified)."""
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
    grading_instance: dict,
    spec_test_cmd: str,
    eval_env: dict,
    results_dir: str,
    agent_surface: str = "claude_code",
    codex_model: str | None = None,
    wall_timeout: int = 1800,
    install_cmd: str | None = None,
    _now=None,
) -> str:
    """Run + grade one (arm, run) in a fresh container; write the record. Returns the verdict."""
    handle = container.start_arm_container(prepared, volumes=[runtime_volume_spec()])
    transcript = os.path.join(tempfile.mkdtemp(prefix="img-arm-"), "transcript.jsonl")
    verdict, resolution, cost, turns = "ERROR", None, None, None
    try:
        container_agent.stage_arm(handle, surface=agent_surface, arm=arm, model=codex_model)
        rc = container_agent.run_agent(
            handle, arm=arm, prompt=_build_prompt(problem, arm),
            result_path=transcript, wall_timeout=wall_timeout,
            surface=agent_surface, model=codex_model,
        )
        log_dest = os.path.join(os.path.dirname(transcript), "eval.txt")
        grade = container_test.grade_agent_run(
            handle, grading_instance, spec_test_cmd=spec_test_cmd,
            eval_env=eval_env, log_dest=log_dest, install_cmd=install_cmd,
        )
        resolution = grade.get("resolution")
        verdict = "PASS" if official_grade.is_resolved(grade) else "FAIL"
        cost, turns = _extract_cost_turns(transcript, agent_surface=agent_surface,
                                          codex_model=codex_model)
        logging.info("image_run %s %s run%d: rc=%s resolution=%s -> %s",
                     problem.instance_id, arm, run_idx, rc, resolution, verdict)
    finally:
        _write_record(
            results_dir, problem, arm, run_idx,
            transcript=transcript, verdict=verdict, resolution=resolution,
            digest_info=digest_info, cost=cost, turns=turns, agent_surface=agent_surface,
            now=_now if _now is not None else time.time(),
        )
        container.teardown(handle)
    return verdict


def _write_record(results_dir, problem, arm, run_idx, *, transcript, verdict, resolution,
                  digest_info, cost, turns, agent_surface, now) -> None:
    """Write ``<instance>_<arm>_run<N>.jsonl``: meta line + agent transcript + verdict line."""
    out = os.path.join(results_dir, f"{problem.instance_id}_{arm}_run{run_idx}.jsonl")
    meta = {
        "type": "meta", "instance_id": problem.instance_id, "arm": arm, "run": run_idx,
        "agent_surface": agent_surface, "runtime": "image",
        "image_digest": digest_info.get("digest"), "image_arch": digest_info.get("arch"),
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
    echo=print,
) -> list[tuple[str, str, str]]:
    """Run ``arms`` over ``problems`` on the image runtime. Returns
    ``(instance_id, arm, verdict)`` triples."""
    image_store.registry_login()
    # Populate the shared runtime volume for the chosen surface (#325).
    if agent_surface == "codex_cli":
        container_agent.ensure_codex_runtime()
    else:
        container_agent.ensure_agent_runtime(agent_binary)
    root = Path(os.environ.get("ONLYCODES_REPO_ROOT", ".")).resolve()

    order = {iid: i for i, iid in enumerate(
        image_store.group_by_repo_version([p.instance_id for p in problems]))}
    problems = sorted(problems, key=lambda p: order.get(p.instance_id, 1 << 30))

    results: list[tuple[str, str, str]] = []
    for problem in problems:
        if not problem.fail_to_pass:
            echo(f"  SKIP {problem.instance_id}: no fail_to_pass (re-run `add` to backfill grading data)")
            continue
        spec = specs.spec_for(problem.repo_slug, problem.version)
        if not spec or not spec.get("test_cmd"):
            echo(f"  SKIP {problem.instance_id}: no spec test_cmd for {problem.repo_slug}@{problem.version}")
            continue

        echo(f"--- Instance: {problem.instance_id} ({problem.repo_slug}@{problem.version}) ---")
        digest_info = image_store.ensure_image(problem.instance_id)
        prepared = container.prepare_instance(
            problem.instance_id, post_strip_exec=container_agent.agent_user_setup_commands())
        gi = _grading_instance(problem, _read_test_patch(problem, root))
        eval_env = specs.eval_env(spec)

        for arm in arms:
            for run_idx in range(num_runs):
                verdict = run_one_arm(
                    problem, arm=arm, run_idx=run_idx, prepared=prepared,
                    digest_info=digest_info, grading_instance=gi,
                    spec_test_cmd=spec["test_cmd"], eval_env=eval_env,
                    results_dir=results_dir, wall_timeout=wall_timeout,
                    agent_surface=agent_surface, codex_model=codex_model,
                    install_cmd=spec.get("install"),
                )
                echo(f"  [{arm} run {run_idx}] {verdict}")
                results.append((problem.instance_id, arm, verdict))
    return results
