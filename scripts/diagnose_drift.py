#!/usr/bin/env python3
"""Root-cause gold-gate 'fidelity drift' (not_resolved) instances (#308).

For each instance id, replay the gold-gate (pull -> strip+agent-user snapshot ->
apply gold+test patch -> eval -> official grade) but capture EVERYTHING the
gate's result row throws away: the full grade dict (resolution, report,
status_map) and the raw eval log. Prints a per-instance verdict that tells us
*why* RESOLVED_NO:

  - status_map EMPTY            -> parser/eval found no tests (collection error,
                                   wrong test_cmd, or parser mismatch)
  - F2P present but not passing -> env drift: the fix didn't take
  - P2P present but broke       -> env drift: regression in the env
  - patch did not apply         -> gold/test patch mismatch vs the image tree

Usage: python scripts/diagnose_drift.py <iid> [<iid> ...]
Images are reused if present (no pull). Eval logs are kept under /tmp/drift-<iid>/.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("ONLYCODES_REPO_ROOT", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))          # scripts/ (validate_verified_image)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # repo root (swebench package)

from swebench import container, container_agent, container_test, image_store, official_grade, specs  # noqa: E402
from swebench.image_run import _grading_instance, _read_test_patch  # noqa: E402
from validate_verified_image import _load_problems, _load_gold_patches  # noqa: E402

ROOT = Path(os.environ["ONLYCODES_REPO_ROOT"])


def _coerce(v):
    import json
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return [v]
    return list(v or [])


def diagnose(iid: str, gold: dict[str, str]) -> None:
    print(f"\n{'='*78}\n{iid}\n{'='*78}")
    problems, missing = _load_problems([iid], ROOT / "problems" / "swe" / "swebench-verified")
    if missing or not problems:
        print(f"  !! could not load Problem ({missing})"); return
    p = problems[0]
    spec = specs.spec_for(p.repo_slug, p.version)
    if not (spec and spec.get("test_cmd")):
        print(f"  !! no spec test_cmd for {p.repo_slug}@{p.version}"); return

    inst = _grading_instance(p, _read_test_patch(p, ROOT))
    inst["patch"] = gold.get(iid, "")
    f2p, p2p = _coerce(inst["FAIL_TO_PASS"]), _coerce(inst["PASS_TO_PASS"])
    print(f"  repo={p.repo_slug}@{p.version}  F2P={len(f2p)}  P2P={len(p2p)}  "
          f"gold_patch={'yes' if inst['patch'] else 'MISSING'}  "
          f"test_patch={'yes' if inst['test_patch'] else 'MISSING'}")

    image_store.ensure_image(iid)
    prepared = container.prepare_instance(
        iid, post_strip_exec=container_agent.agent_user_setup_commands())
    handle = container.start_arm_container(prepared)
    log_dir = Path(f"/tmp/drift-{iid}"); log_dir.mkdir(parents=True, exist_ok=True)
    log_dest = str(log_dir / "eval.txt")
    try:
        # apply patches separately so we can see which (if either) fails
        gold_ok = container_test.apply_patch_in_container(handle, inst["patch"])
        test_ok = container_test.apply_patch_in_container(handle, inst["test_patch"])
        print(f"  gold patch applies: {gold_ok}   test patch applies: {test_ok}")
        if not (gold_ok and test_ok):
            print("  >> VERDICT: PATCH-APPLY FAILURE (gold/test patch vs image tree)")
            return
        log = container_test.run_eval_in_container(
            handle, spec_test_cmd=spec["test_cmd"],
            test_ids=container_test.eval_directives(inst),
            eval_env=specs.eval_env(spec), log_dest=log_dest, timeout=1800,
            install_cmd=spec.get("install"),   # Fix B: faithful reinstall step
        )
        grade = official_grade.grade(inst, log)
        sm = grade.get("status_map") or {}
        res = grade.get("resolution")
        f2p_seen = [t for t in f2p if t in sm]
        f2p_pass = [t for t in f2p_seen if sm[t] == "PASSED"]
        p2p_seen = [t for t in p2p if t in sm]
        p2p_pass = [t for t in p2p_seen if sm[t] == "PASSED"]
        print(f"  log: {len(log)} bytes, {log.count(chr(10))} lines -> {log_dest}")
        print(f"  status_map entries: {len(sm)}")
        print(f"  F2P: {len(f2p_seen)}/{len(f2p)} parsed, {len(f2p_pass)} PASSED")
        print(f"  P2P: {len(p2p_seen)}/{len(p2p)} parsed, {len(p2p_pass)} PASSED")
        print(f"  resolution = {res}")
        # classify
        if len(sm) == 0:
            print("  >> VERDICT: EMPTY STATUS_MAP (parser/eval found nothing — "
                  "collection error, wrong test_cmd, or parser mismatch)")
        elif len(f2p_seen) < len(f2p):
            print(f"  >> VERDICT: {len(f2p)-len(f2p_seen)} F2P test(s) MISSING from "
                  "the log (not collected/named differently)")
        elif len(f2p_pass) < len(f2p_seen):
            print("  >> VERDICT: F2P present but NOT passing (gold fix didn't take — env drift)")
        elif len(p2p_pass) < len(p2p_seen):
            print("  >> VERDICT: P2P regressed (env drift)")
        else:
            print("  >> VERDICT: looks resolvable now (re-run flake?)")
        # sample a few statuses for context
        sample = list(sm.items())[:5]
        print(f"  sample status_map: {sample}")
        if len(sm) == 0:
            print("  --- eval.txt tail (last 25 lines) ---")
            print("\n".join(log.splitlines()[-25:]))
    finally:
        container.teardown(handle)


def main() -> None:
    ids = sys.argv[1:]
    if not ids:
        print("usage: diagnose_drift.py <iid> [<iid> ...]"); sys.exit(1)
    gold = _load_gold_patches(set(ids))
    for iid in ids:
        try:
            diagnose(iid, gold)
        except Exception as e:
            import traceback
            print(f"  !! diagnose raised: {type(e).__name__}: {e}")
            traceback.print_exc()


if __name__ == "__main__":
    main()
