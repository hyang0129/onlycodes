"""Per-category instance counts for the Artifact suite (§4.1 inventory).

Reads paper/data/raw/all_results.csv, extracts the unique Artifact instance
IDs, splits each on the canonical `<category>__<slug>` delimiter, and writes
per-category n + a grand total. Used by §4.1 macros and as a reviewer receipt
that no single category dominates the corpus.
"""
from __future__ import annotations
import csv
import datetime
import subprocess
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
RAW = REPO / "paper" / "data" / "raw" / "all_results.csv"
OUT = REPO / "paper" / "data" / "artifact_categories.csv"
THIS_SCRIPT = Path(__file__).relative_to(REPO)


def main() -> None:
    instance_ids: set[str] = set()
    with RAW.open() as f:
        for r in csv.DictReader(f):
            if r["benchmark"] != "artifact":
                continue
            instance_ids.add(r["instance_id"])

    counts: Counter[str] = Counter()
    for iid in instance_ids:
        cat, _, _ = iid.partition("__")
        counts[cat] += 1

    rows = sorted(counts.items())
    total = sum(counts.values())
    rows.append(("total", total))

    sha = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "HEAD"],
        capture_output=True, text=True,
    ).stdout.strip() or "unknown"
    ts = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    with OUT.open("w", newline="") as f:
        f.write(f"# source_commit: {sha}\n")
        f.write(f"# generated: {ts}\n")
        f.write(f"# generator: {THIS_SCRIPT}\n")
        f.write("# key_schema: category\n")
        f.write("# default_precision: 0\n")
        f.write("# Per-category instance counts for the Artifact suite (§4.1).\n")
        f.write("# `total` row is the grand n across all categories.\n")
        w = csv.writer(f)
        w.writerow(["category", "n", "precision"])
        for category, n in rows:
            w.writerow([category, n, 0])

    print(f"Wrote {OUT} with {len(rows)} rows. Total artifact instances: {total}.")
    for cat, n in rows:
        if cat != "total":
            print(f"  {cat:25s} n={n}")


if __name__ == "__main__":
    main()
