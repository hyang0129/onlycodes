#!/usr/bin/env python3
"""Tier 0 e2e check: verify the AGENT-ARM grading path across a set (#308).

The gold-gate validated ``gold_patch_gate`` (image + gold-patch grading). This
exercises the *other* path the real benchmark uses — ``grade_agent_run``: the
no-leak check, the held-out test-patch apply, the faithful reinstall (Fix B), the
eval, and the official grade — **without spending agent tokens**, by simulating
the agent's edit:

  --mode gold   : apply the GOLD patch as the agent's diff  -> expect PASS (~100%)
  --mode empty  : leave /testbed untouched (no diff)        -> expect FAIL (~0%)

gold≈100% confirms the agent-arm grading path resolves every buildable instance;
empty≈0% confirms it isn't trivially passing (held-out test / no-leak intact).
Any instance that breaks the *bracket* is a harness bug, not a model result.

Resumable (skip instances already recorded for the mode), continue-on-error,
images reused (no pull). See docs/E2E_VERIFICATION_PLAN.md.

    python scripts/verify_agent_grade.py --mode gold  --from-file sets/verified-buildable.txt
    python scripts/verify_agent_grade.py --mode empty --from-file sets/verified-buildable.txt --limit 30
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))          # scripts/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # repo root

from swebench import (container, container_agent, container_test, image_store,  # noqa: E402
                      official_grade, specs)
from swebench.image_run import _grading_instance, _read_test_patch  # noqa: E402
from validate_verified_image import (_load_problems, _load_gold_patches,  # noqa: E402
                                      _await_pull_budget, _is_rate_limit_error)

log = logging.getLogger("verify_agent_grade")
ROOT = Path(os.environ.setdefault("ONLYCODES_REPO_ROOT",
                                  str(Path(__file__).resolve().parent.parent)))
PROBLEMS = ROOT / "problems" / "swe" / "swebench-verified"


def _grade_one(problem, *, mode: str, gold_patch: str, timeout: float) -> dict:
    """Run the agent-arm grading path with a simulated edit. Returns a row."""
    iid = problem.instance_id
    row = {"instance_id": iid, "repo": problem.repo_slug, "mode": mode,
           "status": "error", "verdict": None, "resolution": None, "reason": None}
    spec = specs.spec_for(problem.repo_slug, problem.version)
    if not (spec and spec.get("test_cmd")):
        row["status"] = "skipped"; row["reason"] = "no spec test_cmd"; return row
    if mode == "gold" and not gold_patch:
        row["status"] = "skipped"; row["reason"] = "no gold patch"; return row

    instance = _grading_instance(problem, _read_test_patch(problem, ROOT))
    handle = None
    try:
        while True:
            _await_pull_budget()
            try:
                image_store.ensure_image(iid); break
            except Exception as exc:
                if _is_rate_limit_error(exc):
                    import time; time.sleep(60); continue
                raise
        prepared = container.prepare_instance(
            iid, post_strip_exec=container_agent.agent_user_setup_commands())
        handle = container.start_arm_container(prepared)
        if mode == "gold":
            if not container_test.apply_patch_in_container(handle, gold_patch):
                row["reason"] = "gold patch did not apply (as agent edit)"; return row
        log_dest = os.path.join(tempfile.mkdtemp(prefix="t0-"), "eval.txt")
        grade = container_test.grade_agent_run(
            handle, instance, spec_test_cmd=spec["test_cmd"],
            eval_env=specs.eval_env(spec), log_dest=log_dest, timeout=timeout,
            install_cmd=spec.get("install"), verify_no_leak=True,
        )
        row["resolution"] = grade.get("resolution")
        resolved = official_grade.is_resolved(grade)
        row["verdict"] = "PASS" if resolved else "FAIL"
        # Bracket check: gold should PASS, empty should FAIL.
        row["status"] = "ok" if ((mode == "gold") == resolved) else "BRACKET_VIOLATION"
    except image_store.DiskFullError:
        raise
    except Exception as exc:
        row["reason"] = f"{type(exc).__name__}: {exc}"
        log.warning("%s: %s", iid, row["reason"])
    finally:
        if handle is not None:
            try: container.teardown(handle)
            except Exception: pass
    return row


_TERMINAL = ("ok", "skipped", "BRACKET_VIOLATION")  # 'error' re-attempted on resume


def _load_prior(out: Path, mode: str) -> list:
    """Prior terminal rows for this mode (carried over on resume)."""
    p = out / f"results_{mode}.json"
    if not p.is_file(): return []
    try:
        return [r for r in json.loads(p.read_text()).get("rows", [])
                if r.get("status") in _TERMINAL and r.get("instance_id")]
    except (OSError, json.JSONDecodeError):
        return []


def _write(rows, out: Path, mode: str):
    from collections import Counter
    c = Counter(r["verdict"] for r in rows if r.get("verdict"))
    viol = [r["instance_id"] for r in rows if r["status"] == "BRACKET_VIOLATION"]
    errs = [r["instance_id"] for r in rows if r["status"] == "error"]
    (out / f"results_{mode}.json").write_text(json.dumps(
        {"mode": mode, "counts": dict(c), "bracket_violations": viol,
         "errors": errs, "rows": rows}, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["gold", "empty"], required=True)
    ap.add_argument("--from-file")
    ap.add_argument("--ids")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out-dir", default="runs/validation/agent-grade-t0")
    ap.add_argument("--timeout", type=float, default=1800)
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--parallel", type=int, default=1,
                    help="instances to grade concurrently (default 1 = serial). "
                         "Instances are independent; one thread per instance. On a "
                         "SHARED host keep N small (~2-3): evals are CPU/RAM-heavy "
                         "and oversubscription starves co-tenants (#349).")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.ids:
        ids = [s.strip() for s in args.ids.split(",") if s.strip()]
    elif args.from_file:
        ids = [l.strip() for l in Path(args.from_file).read_text().splitlines()
               if l.strip() and not l.startswith("#")]
    else:
        ap.error("need --from-file or --ids")
    problems, missing = _load_problems(ids, PROBLEMS)
    if missing:
        log.warning("%d ids not materialized: %s", len(missing), missing[:5])
    problems.sort(key=lambda p: p.instance_id.rsplit("-", 1)[0])  # repo-grouped
    if args.limit:
        # stratified: first per repo until limit
        seen, strat = {}, []
        for p in problems:
            k = p.instance_id.rsplit("-", 1)[0]
            if seen.get(k, 0) < max(1, args.limit // 12):
                strat.append(p); seen[k] = seen.get(k, 0) + 1
            if len(strat) >= args.limit: break
        problems = strat

    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
    gold = _load_gold_patches({p.instance_id for p in problems}) if args.mode == "gold" else {}
    prior = [] if args.fresh else _load_prior(out, args.mode)
    done = {r["instance_id"] for r in prior}
    log.info("Tier 0 (%s): %d instances -> %s (%d already done)",
             args.mode, len(problems), out, len(done))

    rows = list(prior)            # carry over so resume doesn't drop earlier verdicts
    todo = [p for p in problems if p.instance_id not in done]
    n_par = max(1, args.parallel)
    if n_par > 1:
        log.info("Parallel: %d workers (one instance each; prepare/eval are "
                 "per-instance so partitioning avoids the prepare race)", n_par)
    lock = threading.Lock()       # guards rows + the results-file write
    stop = threading.Event()      # set on DiskFullError -> drain, submit no more
    prog = {"n": len(done)}

    def _do(p):
        """Grade one instance and checkpoint under the lock. Thread-safe because
        instances are disjoint (own image/container) — only the results write is
        shared. Returns True unless skipped due to a disk-full stop."""
        if stop.is_set():
            return False
        try:
            row = _grade_one(p, mode=args.mode, gold_patch=gold.get(p.instance_id, ""),
                             timeout=args.timeout)
        except image_store.DiskFullError as e:
            stop.set()
            log.error("DiskFull — stopping new work: %s", e)
            return False
        with lock:
            rows.append(row)
            prog["n"] += 1
            _write(rows, out, args.mode)
            log.info("[%d/%d] %s (%s) -> %s", prog["n"], len(problems),
                     p.instance_id, args.mode, row.get("verdict") or row["status"])
        return True

    if n_par == 1:
        for p in todo:
            if stop.is_set():
                break
            _do(p)
    else:
        with ThreadPoolExecutor(max_workers=n_par) as ex:
            futures = [ex.submit(_do, p) for p in todo]
            for f in as_completed(futures):
                f.result()        # surface unexpected (non-DiskFull) failures

    _write(rows, out, args.mode)
    from collections import Counter
    c = Counter(r["verdict"] for r in rows if r.get("verdict"))
    viol = sum(1 for r in rows if r["status"] == "BRACKET_VIOLATION")
    log.info("DONE %s: %s | bracket_violations=%d | errors=%d",
             args.mode, dict(c), viol, sum(1 for r in rows if r["status"] == "error"))


if __name__ == "__main__":
    main()
