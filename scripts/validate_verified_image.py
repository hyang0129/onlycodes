#!/usr/bin/env python3
"""Verbatim gold-patch fidelity gate over a Verified pool (Phase 4, #354).

The image-native "buildable" gate, collapsed onto **verbatim** SWE-bench grading
(``docs/VERBATIM_GRADING_PLAN.md``, Concern B). For each instance we load the
**gold** patch, build a one-line prediction ``{instance_id, model_patch: gold}``,
and grade the whole set through the official ``run_evaluation`` via
:func:`swebench.grading_official.grade_predictions`. An instance is **buildable**
iff its official report says ``resolved is True``. No strip, no reinstall, no
custom in-container gold gate — the official harness runs on the
**unmodified** prebuilt image, so any fidelity question is answered byte-for-byte
by SWE-bench itself.

    # smoke: first 5 of the spine
    python scripts/validate_verified_image.py --limit 5
    # full pool -> committed buildable set
    python scripts/validate_verified_image.py \
        --from-file sets/verified-spine.txt \
        --buildable-out sets/verified-buildable.txt --parallel 4

``grade_predictions`` reuses already-pulled images automatically
(``--namespace swebench --cache_level instance``) and manages its own pulls — no
``image_store`` prep here. Network + an ``HF_TOKEN`` in the environment and a
reachable Docker daemon are required at grade time (source ``.env`` first if you
keep a token there). Continue-on-error: a grading subprocess that produces no
report for some instance marks those ``error`` (never aborts the deliverable).
Resumable: already-``buildable`` instances in ``--out-dir/results.json`` are
carried over; only unknown / not-yet-resolved ids are re-graded on resume.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from swebench import grading_official  # noqa: E402

log = logging.getLogger("validate_verified_image")

HF_DATASETS = [("princeton-nlp/SWE-bench_Verified", "test"),
               ("princeton-nlp/SWE-bench", "test")]


# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------

def _read_ids(args: argparse.Namespace) -> list[str]:
    """Explicit ids from --ids / --from-file, de-duplicated in order."""
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


def _load_gold_patches(ids: set[str]) -> dict[str, str]:
    """Stream the HF Verified split once and collect the gold ``patch`` per id.

    Kept under this name/signature because other tooling imports it. We fetch only
    the ids we need (the split is small, ~500 rows) and fall back to SWE-bench full
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
# Resume
# --------------------------------------------------------------------------

def _load_buildable_rows(out_dir: Path) -> dict[str, dict]:
    """Prior rows that already resolved (``buildable``), keyed by instance_id.

    Only *buildable* rows are terminal on resume: ``not_resolved`` and ``error``
    are re-graded, since a flaky eval or a transient subprocess failure must not
    freeze an instance out of the buildable set forever.
    """
    p = out_dir / "results.json"
    if not p.is_file():
        return {}
    try:
        rows = json.loads(p.read_text()).get("rows", [])
    except (OSError, json.JSONDecodeError):
        return {}
    return {r["instance_id"]: r for r in rows
            if r.get("status") == "buildable" and r.get("instance_id")}


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------

def _row_from_report(iid: str, report: dict) -> dict:
    """Map an official per-instance report to a results.json row.

    ``resolved is True`` -> ``buildable``. A report carrying an ``error`` key
    (no report.json produced — subprocess/grading failure) -> ``error``.
    Anything else (ran, did not resolve) -> ``not_resolved``.
    """
    resolved = bool(report.get("resolved"))
    if resolved:
        status = "buildable"
    elif report.get("error"):
        status = "error"
    else:
        status = "not_resolved"
    return {
        "instance_id": iid,
        "status": status,
        "resolved": resolved,
        "tests_status": report.get("tests_status", {}),
        "reason": report.get("error"),
    }


def _grade_chunk(ids: list[str], gold: dict[str, str], *, run_id: str,
                 max_workers: int, dataset_name: str) -> dict[str, dict]:
    """Grade ``ids`` verbatim. Ids with no gold patch are marked ``skipped``.

    Returns ``{iid: row}``. The actual grading is a single
    :func:`grading_official.grade_predictions` call over all gradeable ids
    (parallel across instances via ``max_workers``).
    """
    rows: dict[str, dict] = {}
    preds, grade_ids = [], []
    for iid in ids:
        patch = gold.get(iid)
        if not patch:
            rows[iid] = {"instance_id": iid, "status": "skipped", "resolved": False,
                         "tests_status": {}, "reason": "no gold patch on HF"}
            continue
        preds.append({"instance_id": iid, "model_patch": patch})
        grade_ids.append(iid)

    if not preds:
        return rows

    try:
        reports = grading_official.grade_predictions(
            preds, run_id=run_id, model_name="gold",
            max_workers=max_workers, instance_ids=grade_ids,
            dataset_name=dataset_name,
        )
    except grading_official.GradingError as exc:
        # Catastrophic: no per-instance reports at all. Mark the whole chunk error
        # (continue-on-error — the report is the deliverable) rather than abort.
        log.error("grade_predictions failed for this chunk: %s", exc)
        for iid in grade_ids:
            rows[iid] = {"instance_id": iid, "status": "error", "resolved": False,
                         "tests_status": {}, "reason": f"GradingError: {exc}"}
        return rows

    for iid in grade_ids:
        rows[iid] = _row_from_report(iid, reports.get(iid, {"error": "no report"}))
    return rows


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

def run(args: argparse.Namespace) -> int:
    root = Path(__file__).resolve().parent.parent
    problems_dir = root / "problems" / args.set

    ids = _read_ids(args)
    if not ids:
        ids = sorted(p.stem for p in problems_dir.glob("*.yaml"))
    if not ids:
        log.error("no instance ids (give --ids/--from-file or materialize problems/%s)", args.set)
        return 1
    if args.limit:
        ids = ids[:args.limit]

    out_dir = Path(args.out_dir or (root / "runs" / "validation" /
                   f"swebench-verified-image_{dt.datetime.utcnow():%Y%m%dT%H%M%SZ}"))
    out_dir.mkdir(parents=True, exist_ok=True)

    # Resume: carry over instances already recorded buildable; re-grade the rest.
    done = {} if args.fresh else _load_buildable_rows(out_dir)
    if done:
        log.info("Resuming: %d instances already buildable — re-grading the rest.", len(done))

    todo = [i for i in ids if i not in done]
    log.info("Validating %d instances verbatim (%d carried over) -> %s",
             len(todo), len(done), out_dir)

    rows: list[dict] = [done[i] for i in ids if i in done]
    _write_outputs(rows, out_dir, args, total_requested=len(ids))

    if todo:
        gold = _load_gold_patches(set(todo))
        run_id = args.run_id or f"validate_{dt.datetime.utcnow():%Y%m%dT%H%M%SZ}"
        graded = _grade_chunk(todo, gold, run_id=run_id,
                              max_workers=max(1, args.parallel),
                              dataset_name=args.dataset_name)
        rows.extend(graded[i] for i in todo if i in graded)
        _write_outputs(rows, out_dir, args, total_requested=len(ids))

    n_build = sum(r["status"] == "buildable" for r in rows)
    log.info("DONE: %d/%d buildable, shortfall %d. Report: %s",
             n_build, len(ids), len(ids) - n_build, out_dir / "summary.md")
    return 0


def _write_outputs(rows: list[dict], out_dir: Path, args, *, total_requested: int) -> None:
    from collections import Counter
    by_status = Counter(r["status"] for r in rows)
    buildable = sorted(r["instance_id"] for r in rows if r["status"] == "buildable")
    n_graded = sum(r["status"] in ("buildable", "not_resolved", "error") for r in rows)

    (out_dir / "results.json").write_text(json.dumps(
        {"generated_utc": dt.datetime.utcnow().isoformat() + "Z",
         "set": args.set, "total_requested": total_requested,
         "counts": dict(by_status), "rows": rows}, indent=2))

    # buildable id-list the spine reads via `run --filter @...`
    buildable_out = Path(args.buildable_out)
    buildable_out.parent.mkdir(parents=True, exist_ok=True)
    buildable_out.write_text(
        "# verbatim gold-gate buildable set (#354). Generated by "
        "scripts/validate_verified_image.py.\n"
        f"# {len(buildable)} buildable of {total_requested} requested.\n"
        + "\n".join(buildable) + ("\n" if buildable else ""))

    lines = [
        "# Verified verbatim gold-gate validation",
        "",
        f"- set: `{args.set}`",
        f"- requested: {total_requested}",
        f"- graded (verbatim run_evaluation): {n_graded}",
        f"- **buildable (resolved=True): {by_status.get('buildable', 0)}**",
        f"- not_resolved (gold did not resolve officially): {by_status.get('not_resolved', 0)}",
        f"- error: {by_status.get('error', 0)}",
        f"- skipped (no gold patch): {by_status.get('skipped', 0)}",
        f"- **shortfall (graded - buildable): {n_graded - by_status.get('buildable', 0)}**",
        "",
        "## Non-buildable instances",
        "",
        "| instance | status | reason |", "|---|---|---|",
    ]
    for r in rows:
        if r["status"] == "buildable":
            continue
        reason = (r.get("reason") or "").replace("|", r"\|")[:160]
        lines.append(f"| {r['instance_id']} | {r['status']} | {reason} |")
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", default="swe/swebench-verified",
                    help="problems subdir under problems/ (default: swe/swebench-verified)")
    ap.add_argument("--from-file", help="file of instance ids (one per line, # comments ok)")
    ap.add_argument("--ids", help="comma-separated instance ids")
    ap.add_argument("--limit", type=int, default=0,
                    help="grade only the first N instances — smoke runs")
    ap.add_argument("--buildable-out", default="sets/verified-buildable.txt",
                    help="committed buildable id-list (default: sets/verified-buildable.txt)")
    ap.add_argument("--out-dir", help="report dir (default: runs/validation/...<ts>)")
    ap.add_argument("--dataset-name", default=grading_official.DEFAULT_DATASET,
                    help="HF dataset passed to run_evaluation (test_patch/F2P/P2P source)")
    ap.add_argument("--run-id", help="run_evaluation run_id (default: validate_<ts>)")
    ap.add_argument("--parallel", type=int, default=1,
                    help="grade_predictions max_workers (instances graded concurrently). "
                         "On a SHARED host keep small (~2-4): evals are CPU/RAM-heavy.")
    ap.add_argument("--fresh", action="store_true",
                    help="ignore a prior run's results.json in --out-dir (default: resume)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
