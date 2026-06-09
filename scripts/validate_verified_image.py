#!/usr/bin/env python3
"""Image-runtime gold-patch fidelity gate over a Verified pool (C3, #308).

The image-native counterpart to ``scripts/validate_verified_setup.py`` (which
validates the deprecated overlay/conda build). For each instance it pulls the
official SWE-bench image (pinned by digest, auto-pinning any missing digest as a
pull side-effect), builds the stripped per-instance snapshot, applies the **gold**
patch + the held-out test patch in a fresh container, runs the official eval, and
grades. An instance is **buildable** (image-faithful) iff the gold patch yields
``RESOLVED_FULL`` — FAIL_TO_PASS flip red->green and PASS_TO_PASS stay green.
Anything else means our image+grading path drifted from the benchmark for that
instance and it must be excluded from the spine denominator (#299).

The held-out test patch, FAIL_TO_PASS/PASS_TO_PASS, and version->spec test_cmd
come from the materialized ``Problem`` — identical to the agent arm's grading
instance (``image_run._grading_instance``). The **gold patch is not stored
locally** (only the test patch is), so it is sourced per-instance from the HF
Verified split.

    # smoke: first 5 (repo-grouped) of the spine
    python scripts/validate_verified_image.py --limit 5
    # full pool -> committed buildable set
    python scripts/validate_verified_image.py \
        --from-file sets/verified-spine.txt \
        --buildable-out sets/verified-buildable.txt

Auth (full pool): set ``ONLYCODES_DOCKERHUB_TOKEN`` (+ optional
``ONLYCODES_DOCKERHUB_USER``) first — anonymous Docker Hub throttles after ~150
pulls. Disk: images are pulled once and **kept for reuse** (no eviction — see
``image_store``); if the docker store fills, the sweep stops and asks for more
disk (resume reuses everything already pulled). Continue-on-error: one bad
instance never aborts the pass — the report is the deliverable, and the
shortfall (total - buildable) is logged, never silently truncated.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import logging
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from swebench import (  # noqa: E402
    container, container_agent, container_test, image_store, official_grade, specs,
)
from swebench.image_run import _grading_instance, _read_test_patch  # noqa: E402
from swebench.models import Problem  # noqa: E402

log = logging.getLogger("validate_verified_image")

HF_DATASETS = [("princeton-nlp/SWE-bench_Verified", "test"),
               ("princeton-nlp/SWE-bench", "test")]


# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------

def _read_ids(args: argparse.Namespace) -> list[str]:
    ids: list[str] = []
    if args.ids:
        ids += [s.strip() for s in args.ids.split(",") if s.strip()]
    if args.from_file:
        for line in Path(args.from_file).read_text().splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                ids.append(line)
    seen: set[str] = set()
    return [i for i in ids if not (i in seen or seen.add(i))]


def _load_problems(ids: list[str], problems_dir: Path) -> tuple[list[Problem], list[str]]:
    """Load materialized Problems for ``ids``; return (problems, missing_ids)."""
    problems, missing = [], []
    for iid in ids:
        path = problems_dir / f"{iid}.yaml"
        if not path.is_file():
            missing.append(iid)
            continue
        problems.append(Problem.from_yaml(path))
    return problems, missing


def _load_gold_patches(ids: set[str]) -> dict[str, str]:
    """Stream the HF Verified split once and collect the gold ``patch`` per id.

    The gold patch is the only field not materialized locally. We fetch only the
    ids we need (the split is small, ~500 rows) and fall back to SWE-bench full
    for any id absent from Verified.
    """
    from datasets import load_dataset  # local import: heavy, optional dep

    want = set(ids)
    out: dict[str, str] = {}
    for name, split in HF_DATASETS:
        if not want:
            break
        log.info("Loading gold patches from %s (%d still needed)...", name, len(want))
        ds = load_dataset(name, split=split, streaming=True)
        for row in ds:
            iid = row.get("instance_id")
            if iid in want:
                out[iid] = row.get("patch", "")
                want.discard(iid)
                if not want:
                    break
    if want:
        log.warning("gold patch not found on HF for %d ids: %s",
                    len(want), ", ".join(sorted(want)[:10]) + (" ..." if len(want) > 10 else ""))
    return out


# --------------------------------------------------------------------------
# Docker Hub pull-rate pacing (free tier = 200 GET/6h)
# --------------------------------------------------------------------------
#
# A full sweep is ~500 image pulls; the free authenticated tier allows 200
# *counted* requests per rolling 6h window. A naive pull storm exhausts the
# budget and image_store._pull_with_backoff gives up after ~7.5 min — which is
# far shorter than the 6h window, so throttled instances would be mis-marked
# "error" (non-buildable). Instead we pace: before each pull, probe the remaining
# budget via a HEAD manifest request (HEAD is NOT counted, only GET is — verified
# against the ratelimit-* headers) and sleep until the window refills. This keeps
# us under 200/6h and guarantees no instance is mis-marked due to throttling.

_RATE_PROBE_REPO = "swebench/sweb.eval.x86_64.psf_1776_requests-1142"
_ACCEPT = ("application/vnd.docker.distribution.manifest.list.v2+json,"
           "application/vnd.oci.image.index.v1+json,"
           "application/vnd.docker.distribution.manifest.v2+json")


def _dockerhub_pull_budget(repo: str = _RATE_PROBE_REPO) -> tuple[int, int] | None:
    """Return ``(remaining, limit)`` of the Docker Hub pull budget via a free HEAD
    manifest probe, or ``None`` if it can't be determined (no creds / parse miss /
    account is unlimited — Pro/mirror omit the ratelimit headers)."""
    user = os.environ.get("ONLYCODES_DOCKERHUB_USER", "")
    token = os.environ.get("ONLYCODES_DOCKERHUB_TOKEN", "")
    try:
        scope = f"repository:{repo}:pull"
        auth_url = f"https://auth.docker.io/token?service=registry.docker.io&scope={scope}"
        headers = {}
        if user and token:
            headers["Authorization"] = "Basic " + base64.b64encode(
                f"{user}:{token}".encode()).decode()
        with urllib.request.urlopen(
                urllib.request.Request(auth_url, headers=headers), timeout=30) as r:
            bearer = json.load(r)["token"]
        req = urllib.request.Request(
            f"https://registry-1.docker.io/v2/{repo}/manifests/latest",
            method="HEAD", headers={"Authorization": f"Bearer {bearer}", "Accept": _ACCEPT})
        with urllib.request.urlopen(req, timeout=30) as resp:
            rem = resp.headers.get("ratelimit-remaining")
            lim = resp.headers.get("ratelimit-limit")
        if rem is None or lim is None:
            return None  # unlimited account / mirror: no headers
        return int(rem.split(";")[0]), int(lim.split(";")[0])
    except Exception:
        return None


def _await_pull_budget(*, min_remaining: int = 8, poll_s: int = 300,
                       _sleep=time.sleep, _probe=_dockerhub_pull_budget) -> None:
    """Block until the pull budget is at least ``min_remaining`` (or undeterminable).

    No-op when the probe returns ``None`` (unlimited account / mirror / offline) —
    image_store's own backoff still covers transient errors there.
    """
    while True:
        budget = _probe()
        if budget is None:
            return
        remaining, limit = budget
        if remaining >= min_remaining:
            return
        log.warning("Docker Hub pull budget %d/%d — sleeping %ds for the 6h window to refill",
                    remaining, limit, poll_s)
        _sleep(poll_s)


def _is_rate_limit_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "toomanyrequests" in msg or "rate limit" in msg or "rate limited" in msg


# --------------------------------------------------------------------------
# Per-instance gate
# --------------------------------------------------------------------------

def _gate_one(problem: Problem, *, gold_patch: str, root: Path,
              timeout: float) -> dict:
    """Pull -> prepare -> gold gate -> grade one instance. Returns a result row.

    ``status`` is one of: ``buildable`` (RESOLVED_FULL), ``not_resolved`` (image
    ran but gold did not flip cleanly -> fidelity drift), or ``error`` (pull /
    prepare / apply / eval blew up). Never raises *except* on
    :class:`image_store.DiskFullError`, which propagates so the sweep halts and
    asks for more disk (images are kept for reuse — resume picks up where it
    stopped).
    """
    iid = problem.instance_id
    row: dict = {"instance_id": iid, "repo": problem.repo_slug, "version": problem.version,
                 "status": "error", "resolution": None, "reason": None,
                 "digest": None, "pruned": []}

    instance = _grading_instance(problem, _read_test_patch(problem, root))
    instance["patch"] = gold_patch  # the gold fix the gate applies (not stored locally)

    handle = None
    try:
        spec = specs.spec_for(problem.repo_slug, problem.version)
        # Pace the pull under Docker Hub's rate limit. Rate-limit hits are NOT a
        # fidelity verdict — wait out the window and retry the same instance so it
        # is never mis-marked "error". Only non-rate-limit failures fall through.
        while True:
            _await_pull_budget()
            try:
                info = image_store.ensure_image(iid)
                break
            except Exception as exc:
                if _is_rate_limit_error(exc):
                    log.warning("%s: rate-limited mid-pull; awaiting window refill", iid)
                    time.sleep(60)
                    continue
                raise
        row["digest"], row["pruned"] = info.get("digest"), info.get("pruned", [])
        # Create the non-root `agent` user + chown /testbed into the snapshot,
        # exactly as image_run.run_image_arms does. gold_patch_gate applies/evals
        # as AGENT_USER; without this the snapshot has no such user and every
        # apply fails with "unable to find user agent" (false-negative errors).
        prepared = container.prepare_instance(
            iid, post_strip_exec=container_agent.agent_user_setup_commands())
        handle = container.start_arm_container(prepared)
        log_dest = os.path.join(tempfile.mkdtemp(prefix="goldgate-"), "eval.txt")
        grade = container_test.gold_patch_gate(
            handle, instance, spec_test_cmd=spec["test_cmd"],
            eval_env=specs.eval_env(spec), log_dest=log_dest, timeout=timeout,
        )
        row["resolution"] = grade.get("resolution")
        if official_grade.is_resolved(grade):
            row["status"] = "buildable"
        else:
            row["status"] = "not_resolved"
            row["reason"] = "gold patch did not yield RESOLVED_FULL (fidelity drift)"
            row["grade"] = {k: grade.get(k) for k in
                            ("FAIL_TO_PASS", "PASS_TO_PASS", "FAIL_TO_FAIL", "PASS_TO_FAIL")}
    except image_store.DiskFullError:
        raise  # halt the sweep — add disk and resume; not a per-instance error
    except Exception as exc:  # continue-on-error: the report is the deliverable
        row["reason"] = f"{type(exc).__name__}: {exc}"
        log.warning("%s: %s", iid, row["reason"])
    finally:
        if handle is not None:
            try:
                container.teardown(handle)
            except Exception:
                pass
    return row


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

_TERMINAL_STATUSES = {"buildable", "not_resolved", "skipped"}


def _load_terminal_rows(out_dir: Path) -> dict:
    """Prior-run rows with a terminal status, keyed by instance_id (for --resume).
    'error' rows are intentionally excluded so they get re-attempted."""
    p = out_dir / "results.json"
    if not p.is_file():
        return {}
    try:
        rows = json.loads(p.read_text()).get("rows", [])
    except (OSError, json.JSONDecodeError):
        return {}
    return {r["instance_id"]: r for r in rows
            if r.get("status") in _TERMINAL_STATUSES and r.get("instance_id")}


def run(args: argparse.Namespace) -> int:
    root = Path(__file__).resolve().parent.parent
    problems_dir = root / "problems" / args.set

    ids = _read_ids(args)
    if not ids:
        ids = sorted(p.stem for p in problems_dir.glob("*.yaml"))
    problems, missing = _load_problems(ids, problems_dir)
    if missing:
        log.warning("%d requested ids have no materialized YAML (run `swebench add` first): %s",
                    len(missing), ", ".join(missing[:10]) + (" ..." if len(missing) > 10 else ""))

    # Repo-version grouped order so the shared base layers are reused before prune.
    order = {iid: i for i, iid in enumerate(
        image_store.group_by_repo_version([p.instance_id for p in problems]))}
    problems.sort(key=lambda p: order.get(p.instance_id, 1 << 30))
    if args.limit:
        problems = problems[:args.limit]

    gold = _load_gold_patches({p.instance_id for p in problems})

    if not image_store.registry_login():
        log.warning("no ONLYCODES_DOCKERHUB_TOKEN — pulling anonymously "
                    "(Docker Hub throttles after ~150; set a token for the full pool).")

    out_dir = args.out_dir or (root / "runs" / "validation" /
                               f"swebench-verified-image_{dt.datetime.utcnow():%Y%m%dT%H%M%SZ}")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Resume: a full sweep is ~1.5-2 days under the free pull-rate cap and may be
    # interrupted. Carry over instances already recorded with a TERMINAL status
    # (buildable / not_resolved / skipped) from a prior run's results.json; re-run
    # only 'error' (possibly transient) + anything never reached. --fresh ignores.
    done = {} if args.fresh else _load_terminal_rows(out_dir)
    if done:
        log.info("Resuming: %d instances already gated (terminal) — re-running the rest.",
                 len(done))

    log.info("Validating %d instances on the image runtime -> %s", len(problems), out_dir)

    rows: list[dict] = []
    for n, problem in enumerate(problems, 1):
        iid = problem.instance_id
        if iid in done:                       # resume: reuse the prior terminal verdict
            rows.append(done[iid])
            _write_outputs(rows, out_dir, args, total_requested=len(ids))
            continue
        # Pre-flight skips (recorded, not run).
        spec = specs.spec_for(problem.repo_slug, problem.version)
        if not problem.fail_to_pass:
            rows.append({"instance_id": iid, "repo": problem.repo_slug, "status": "skipped",
                         "reason": "no fail_to_pass (re-run `add` to backfill grading data)"})
        elif not (spec and spec.get("test_cmd")):
            rows.append({"instance_id": iid, "repo": problem.repo_slug, "status": "skipped",
                         "reason": f"no spec test_cmd for {problem.repo_slug}@{problem.version}"})
        elif iid not in gold or not gold[iid]:
            rows.append({"instance_id": iid, "repo": problem.repo_slug, "status": "skipped",
                         "reason": "no gold patch on HF"})
        else:
            log.info("[%d/%d] %s (%s@%s)", n, len(problems), iid,
                     problem.repo_slug, problem.version)
            try:
                rows.append(_gate_one(problem, gold_patch=gold[iid], root=root,
                                      timeout=args.timeout))
            except image_store.DiskFullError as exc:
                # Reuse-forever store is full: stop loudly, keep what's pulled.
                _write_outputs(rows, out_dir, args, total_requested=len(ids))
                log.error("STOPPED at [%d/%d] — out of disk: %s", n, len(problems), exc)
                log.error("Gated %d/%d so far (all images kept for reuse). Free up or "
                          "expand the docker disk, then re-run the same command to resume.",
                          len(rows), len(problems))
                raise SystemExit(2)
        _write_outputs(rows, out_dir, args, total_requested=len(ids))  # checkpoint each step

    _write_outputs(rows, out_dir, args, total_requested=len(ids))
    n_build = sum(r["status"] == "buildable" for r in rows)
    log.info("DONE: %d/%d buildable, shortfall %d. Report: %s",
             n_build, len(problems), len(problems) - n_build, out_dir / "summary.md")
    return 0


def _write_outputs(rows: list[dict], out_dir: Path, args, *, total_requested: int) -> None:
    from collections import Counter
    by_status = Counter(r["status"] for r in rows)
    buildable = sorted(r["instance_id"] for r in rows if r["status"] == "buildable")
    n_gated = sum(r["status"] in ("buildable", "not_resolved", "error") for r in rows)

    (out_dir / "results.json").write_text(json.dumps(
        {"generated_utc": dt.datetime.utcnow().isoformat() + "Z",
         "set": args.set, "total_requested": total_requested,
         "counts": dict(by_status), "rows": rows}, indent=2))

    # buildable id-list the spine reads via `run --filter @...`
    buildable_out = Path(args.buildable_out)
    buildable_out.parent.mkdir(parents=True, exist_ok=True)
    buildable_out.write_text(
        "# image-runtime gold-gate buildable set (#308). Generated by "
        "scripts/validate_verified_image.py.\n"
        f"# {len(buildable)} buildable of {total_requested} requested.\n"
        + "\n".join(buildable) + ("\n" if buildable else ""))

    repo_break = Counter(r.get("repo") for r in rows if r["status"] != "buildable" and r.get("repo"))
    lines = [
        "# Verified image-runtime gold-gate validation",
        "",
        f"- set: `{args.set}`",
        f"- requested: {total_requested}",
        f"- gated (pull+gate attempted): {n_gated}",
        f"- **buildable (RESOLVED_FULL): {by_status.get('buildable', 0)}**",
        f"- not_resolved (fidelity drift): {by_status.get('not_resolved', 0)}",
        f"- error: {by_status.get('error', 0)}",
        f"- skipped (pre-flight): {by_status.get('skipped', 0)}",
        f"- **shortfall (gated - buildable): {n_gated - by_status.get('buildable', 0)}**",
        "",
        "## Non-buildable by repo",
        "",
    ]
    lines += [f"- {repo}: {cnt}" for repo, cnt in sorted(repo_break.items())] or ["- (none)"]
    lines += ["", "## Non-buildable instances", "",
              "| instance | status | resolution | reason |", "|---|---|---|---|"]
    for r in rows:
        if r["status"] == "buildable":
            continue
        reason = (r.get("reason") or "").replace("|", r"\|")[:160]
        lines.append(f"| {r['instance_id']} | {r['status']} | {r.get('resolution') or ''} "
                     f"| {reason} |")
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", default="swe/swebench-verified",
                    help="problems subdir under problems/ (default: swe/swebench-verified)")
    ap.add_argument("--from-file", help="file of instance ids (one per line, # comments ok)")
    ap.add_argument("--ids", help="comma-separated instance ids")
    ap.add_argument("--limit", type=int, default=0,
                    help="gate only the first N (repo-grouped) instances — smoke runs")
    ap.add_argument("--buildable-out", default="sets/verified-buildable.txt",
                    help="committed buildable id-list (default: sets/verified-buildable.txt)")
    ap.add_argument("--out-dir", help="report dir (default: runs/validation/...<ts>)")
    ap.add_argument("--timeout", type=float, default=1800, help="per-instance eval timeout (s)")
    ap.add_argument("--fresh", action="store_true",
                    help="ignore a prior run's results.json in --out-dir (default: resume)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
