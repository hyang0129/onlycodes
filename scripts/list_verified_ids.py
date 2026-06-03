#!/usr/bin/env python3
"""Freeze the SWE-bench Verified instance-id pool to a newline-delimited file.

This is the C2 step of WS-A.2 (#308): the *input* pool the modification-regime
spine (#299) and the model×scaffold deconfound subset (#301) both draw from.
Streaming the dataset and committing the resulting id list makes the pool
reproducible — the build/run grid is then pinned to a frozen set of ids rather
than whatever HuggingFace happens to return on a given day.

It uses the same HuggingFace streaming path as ``swebench/add.py`` (the canonical
fetch), but only reads ``instance_id`` — it does not materialize YAMLs. Run::

    python scripts/list_verified_ids.py --out sets/verified-spine.txt

then materialize with the existing harness::

    python -m swebench add --from-file sets/verified-spine.txt \
        --set swe/swebench-verified --concurrency 8

SWE-bench Verified is expected to contain exactly 500 instances; a different
count is surfaced loudly on stderr (never silently truncated) but still written,
because a count drift is itself a signal worth committing and diffing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Same dataset + split that swebench/add.py tries first (add.py:64-66). Kept in
# one place so the spine pool and `add` can never disagree about the source.
DATASET = "princeton-nlp/SWE-bench_Verified"
SPLIT = "test"
EXPECTED_COUNT = 500


def fetch_ids() -> list[str]:
    """Stream the Verified split and return instance_ids in dataset order."""
    try:
        from datasets import load_dataset
    except ImportError:
        print(
            "ERROR: the 'datasets' package is required.\n"
            "Install it with: pip install 'datasets>=2.18'",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Streaming {DATASET} (split={SPLIT})...", file=sys.stderr)
    ds = load_dataset(DATASET, split=SPLIT, streaming=True)
    ids: list[str] = []
    seen: set[str] = set()
    for row in ds:
        iid = row["instance_id"]
        if iid in seen:  # defensive — the dataset should not repeat ids
            continue
        seen.add(iid)
        ids.append(iid)
    return ids


def render(ids: list[str]) -> str:
    """Render the frozen list with a provenance header (``#`` lines are ignored
    by the harness id-file parsers in add.py and run.py, so the header is safe)."""
    lines = [
        f"# SWE-bench Verified instance-id pool (WS-A.2 / #308).",
        f"# Source: {DATASET} (split={SPLIT}), streamed via scripts/list_verified_ids.py.",
        f"# Count: {len(ids)} (expected {EXPECTED_COUNT}).",
        "# Frozen for reproducibility — the spine (#299) and deconfound subset (#301)",
        "# draw from this pool. Regenerate only if the upstream dataset changes.",
    ]
    lines.extend(ids)
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write the id list here (default: stdout). Use 'sets/verified-spine.txt'.",
    )
    args = parser.parse_args()

    ids = fetch_ids()

    if len(ids) != EXPECTED_COUNT:
        print(
            f"WARNING: got {len(ids)} ids, expected {EXPECTED_COUNT}. "
            "Writing anyway — a count drift is a real signal, not a reason to truncate.",
            file=sys.stderr,
        )

    out_text = render(ids)
    if args.out is None:
        sys.stdout.write(out_text)
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(out_text)
        print(f"Wrote {len(ids)} ids to {args.out}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
