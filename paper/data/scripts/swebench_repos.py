"""Per-repo instance counts for the SWE-bench Mini suite (§4.1 inventory).

Reads paper/data/raw/all_results.csv, extracts the unique SWE-bench instance
IDs and their (dataset, repo) tuples. Instance IDs follow `<org>__<repo>-N`;
we keep the repo segment because the friendly-name list in §4.1 (sklearn,
matplotlib, xarray, sympy, seaborn, astropy) uses repo names, not org names.

Writes per-(corpus, repo) n + per-corpus subtotals + grand total. The corpus
label strips the leading `swebench-` prefix so macro keys are short
(e.g. `verified-mini:django:n`).
"""
from __future__ import annotations
import csv
import datetime
import re
import subprocess
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
RAW = REPO / "paper" / "data" / "raw" / "all_results.csv"
OUT = REPO / "paper" / "data" / "swebench_repos.csv"
THIS_SCRIPT = Path(__file__).relative_to(REPO)

# `<org>__<repo>-<N>` — the repo segment is the canonical short name
# (e.g. xarray, seaborn, scikit-learn) used in §4.1 prose.
_INSTANCE_PATTERN = re.compile(r"^[^_]+(?:[-_][^_]+)*__([^-]+(?:-[^-]+)*?)-\d+$")


def _parse_repo(instance_id: str) -> str:
    m = _INSTANCE_PATTERN.match(instance_id)
    if not m:
        # Fall back to the org segment if the pattern doesn't match.
        return instance_id.split("__")[0]
    return m.group(1)


def _strip_swebench(dataset: str) -> str:
    return dataset[len("swebench-"):] if dataset.startswith("swebench-") else dataset


def main() -> None:
    pairs: set[tuple[str, str, str]] = set()  # (corpus, repo, instance_id)
    with RAW.open() as f:
        for r in csv.DictReader(f):
            if r["benchmark"] != "swebench":
                continue
            corpus = _strip_swebench(r["dataset"])
            repo = _parse_repo(r["instance_id"])
            pairs.add((corpus, repo, r["instance_id"]))

    counts: Counter[tuple[str, str]] = Counter()
    corpus_totals: Counter[str] = Counter()
    for corpus, repo, _iid in pairs:
        counts[(corpus, repo)] += 1
        corpus_totals[corpus] += 1

    rows: list[tuple[str, str, int]] = []
    for (corpus, repo), n in sorted(counts.items()):
        rows.append((corpus, repo, n))
    for corpus, n in sorted(corpus_totals.items()):
        rows.append((corpus, "total", n))
    rows.append(("total", "total", sum(corpus_totals.values())))

    sha = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "HEAD"],
        capture_output=True, text=True,
    ).stdout.strip() or "unknown"
    ts = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    with OUT.open("w", newline="") as f:
        f.write(f"# source_commit: {sha}\n")
        f.write(f"# generated: {ts}\n")
        f.write(f"# generator: {THIS_SCRIPT}\n")
        f.write("# key_schema: corpus:repo\n")
        f.write("# default_precision: 0\n")
        f.write("# Per-(corpus, repo) instance counts for SWE-bench Mini (§4.1).\n")
        f.write("# corpus is `verified-mini` or `datasci-mini` (swebench- prefix stripped).\n")
        f.write("# Rows with repo=`total` are per-corpus subtotals; ('total','total') is the grand n.\n")
        w = csv.writer(f)
        w.writerow(["corpus", "repo", "n", "precision"])
        for corpus, repo, n in rows:
            w.writerow([corpus, repo, n, 0])

    print(f"Wrote {OUT} with {len(rows)} rows.")
    for corpus, repo, n in rows:
        print(f"  {corpus:15s} {repo:15s} n={n}")


if __name__ == "__main__":
    main()
