#!/usr/bin/env python3
"""Audit SWE-bench run dirs for rate-limited / errored / degraded agent runs (#305).

The spine (#299) is a multi-day, ~8,900-run sweep on two subscription-billed
agents. A rate-limited or API-errored run is written as a ``FAIL`` and then
treated as *done* by ``--resume`` — silently corrupting the pass-rate and cost
numbers. This tool classifies each transcript (see ``swebench.run_audit``) and,
with ``--quarantine``, moves the infra-failed triples aside so a subsequent

    python -m swebench run --filter @sets/verified-buildable.txt --resume ...

re-runs *only* those triples (resume re-runs any triple whose files are gone).

Examples
--------
    # Report only (no changes)
    python scripts/audit_runs.py runs/swebench/spine_claude_seed_1

    # Report + quarantine hard failures so --resume re-runs them
    python scripts/audit_runs.py runs/swebench/spine_claude_seed_1 --quarantine

    # Machine-readable
    python scripts/audit_runs.py runs/swebench/spine_* --json /tmp/audit.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from swebench.run_audit import (  # noqa: E402
    HARD_STATUSES,
    OK,
    SOFT_STATUSES,
    RunAudit,
    audit_dir,
)


def _quarantine(audit: RunAudit, run_dir: Path) -> list[str]:
    """Move a flagged triple's files into ``<run_dir>/_quarantine/`` (reversible).
    Returns the basenames moved. The JSONL + its sibling ``_test.txt`` go together
    so ``--resume`` sees the triple as absent and re-runs it."""
    qdir = run_dir / "_quarantine"
    qdir.mkdir(exist_ok=True)
    moved: list[str] = []
    jsonl = audit.path
    txt = jsonl.with_name(jsonl.stem + "_test.txt")
    for f in (jsonl, txt):
        if f.is_file():
            dest = qdir / f.name
            f.rename(dest)
            moved.append(f.name)
    return moved


def _print_table(audits: list[RunAudit]) -> None:
    flagged = [a for a in audits if a.status != OK]
    if not flagged:
        print("  (no flagged runs)")
        return
    width = max(len(a.instance_id or "?") for a in flagged)
    for a in sorted(flagged, key=lambda a: (a.status, str(a.instance_id), a.arm or "")):
        tag = "RERUN" if a.needs_rerun else "soft "
        iid = (a.instance_id or "?").ljust(width)
        arm = (a.arm or "?").ljust(10)
        reason = a.reasons[0] if a.reasons else ""
        print(f"  [{tag}] {a.status:<13} {iid}  {arm}  {reason}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dirs", nargs="+", type=Path, help="Run dir(s) to audit (recursive).")
    ap.add_argument("--quarantine", action="store_true",
                    help="Move hard-failed triples to <dir>/_quarantine/ so --resume re-runs them.")
    ap.add_argument("--include-soft", action="store_true",
                    help="Also quarantine soft failures (max_turns). Off by default.")
    ap.add_argument("--json", type=Path, default=None, dest="json_out",
                    help="Write per-run audit records to this JSON file.")
    args = ap.parse_args()

    all_audits: list[RunAudit] = []
    grand = Counter()
    rerun_total = 0

    quarantine_set = set(HARD_STATUSES)
    if args.include_soft:
        quarantine_set |= set(SOFT_STATUSES)

    for run_dir in args.run_dirs:
        if not run_dir.is_dir():
            print(f"ERROR: not a directory: {run_dir}", file=sys.stderr)
            return 2
        audits = audit_dir(run_dir)
        all_audits.extend(audits)
        counts = Counter(a.status for a in audits)
        grand.update(counts)

        print(f"\n=== {run_dir}  ({len(audits)} runs) ===")
        for status in sorted(counts):
            print(f"  {status:<13} {counts[status]}")
        _print_table(audits)

        if args.quarantine:
            to_move = [a for a in audits if a.status in quarantine_set]
            for a in to_move:
                moved = _quarantine(a, run_dir)
                if moved:
                    rerun_total += 1
            if to_move:
                print(f"  → quarantined {len(to_move)} triple(s) to {run_dir/'_quarantine'} "
                      f"(re-run with `swebench run ... --resume`)")

    print("\n=== TOTAL ===")
    for status in sorted(grand):
        print(f"  {status:<13} {grand[status]}")
    n_rerun = sum(grand[s] for s in HARD_STATUSES)
    n_soft = sum(grand[s] for s in SOFT_STATUSES)
    print(f"  ---\n  needs re-run (hard): {n_rerun}   soft: {n_soft}   ok: {grand[OK]}")
    if args.quarantine:
        print(f"  quarantined this run: {rerun_total}")

    if args.json_out:
        args.json_out.write_text(json.dumps([a.to_dict() for a in all_audits], indent=2))
        print(f"  wrote {args.json_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
