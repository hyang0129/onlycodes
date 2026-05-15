#!/usr/bin/env python3
"""Workspace generator for ``ml_engineering__aggregate_predictions_*``.

Creates a ``predictions/`` directory containing multiple prediction files in
various formats.  The agent must aggregate all valid predictions into a single
``output/predictions.csv``.

Difficulty tiers (controlled by ``--instance-id``):

  * ``aggregate_predictions_easy``   — 5 standard CSV files, identical schema
  * ``aggregate_predictions_medium`` — 5 CSV + 2 JSONL + 1 truncated CSV
  * ``aggregate_predictions_hard``   — 12 files: 9 format/schema variants
                                       + 1 dup-id CSV + 2 binary-corrupt files

Row counts per file:  easy=200,  medium=500,  hard=1 000.

Pred-prob formula (deterministic, seed-based):

    pred_prob(seed, n) = round(Random((seed * 2_654_435_761) ^ n).random(), 6)

The same sample ID always produces the same pred_prob regardless of difficulty,
so the reference output can be regenerated without re-parsing files.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import os
import random
from pathlib import Path
from typing import List, Tuple

# ---------------------------------------------------------------------------
# Difficulty parameters
# ---------------------------------------------------------------------------

_ROWS_PER_FILE = {"easy": 200, "medium": 500, "hard": 1_000}

_DIFFICULTY = {
    "aggregate_predictions_easy":   "easy",
    "aggregate_predictions_medium": "medium",
    "aggregate_predictions_hard":   "hard",
}


def _slug_from_instance_id(instance_id: str) -> str:
    parts = instance_id.split("__", 1)
    return parts[1] if len(parts) == 2 else instance_id


def _pred_prob(seed: int, n: int) -> float:
    """Deterministic pred_prob for sample number n with given seed."""
    return round(random.Random((seed * 2_654_435_761) ^ n).random(), 6)


# ---------------------------------------------------------------------------
# Low-level file writers
# ---------------------------------------------------------------------------

Rows = List[Tuple[str, float]]


def _write_csv_standard(path: Path, rows: Rows) -> None:
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "pred_prob"])
        w.writerows(rows)


def _write_csv_bom(path: Path, rows: Rows) -> None:
    buf = io.StringIO(newline="")
    w = csv.writer(buf)
    w.writerow(["id", "pred_prob"])
    w.writerows(rows)
    path.write_bytes(b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8"))


def _write_csv_noheader(path: Path, rows: Rows) -> None:
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerows(rows)  # no header


def _write_csv_quoted_mixed_endings(path: Path, rows: Rows) -> None:
    """Quoted CSV with alternating LF / CRLF line endings."""
    lines: List[str] = ['"id","pred_prob"']
    for sid, prob in rows:
        lines.append(f'"{sid}","{prob}"')
    parts: List[bytes] = []
    for i, line in enumerate(lines):
        ending = b"\r\n" if i % 2 == 0 else b"\n"
        parts.append(line.encode("utf-8") + ending)
    path.write_bytes(b"".join(parts))


def _write_jsonl_canonical(path: Path, rows: Rows) -> None:
    with open(path, "w") as fh:
        for sid, prob in rows:
            fh.write(json.dumps({"id": sid, "pred_prob": prob}) + "\n")


def _write_jsonl_noncanonical_schema(path: Path, rows: Rows) -> None:
    """Uses sample_id / probability instead of id / pred_prob."""
    with open(path, "w") as fh:
        for sid, prob in rows:
            fh.write(json.dumps({"sample_id": sid, "probability": prob}) + "\n")


def _write_jsonl_with_comments(path: Path, rows: Rows) -> None:
    """Canonical JSONL with '# comment' lines interspersed every 100 rows."""
    with open(path, "w") as fh:
        for i, (sid, prob) in enumerate(rows):
            if i > 0 and i % 100 == 0:
                fh.write(f"# batch {i // 100} checkpoint\n")
            fh.write(json.dumps({"id": sid, "pred_prob": prob}) + "\n")


def _write_json_array_string_probs(path: Path, rows: Rows) -> None:
    """JSON array with non-canonical field names and string-typed pred_prob."""
    data = [{"identifier": sid, "pred_prob": str(prob)} for sid, prob in rows]
    path.write_text(json.dumps(data, indent=None))


def _write_csv_gz(path: Path, rows: Rows) -> None:
    with gzip.open(path, "wt", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "pred_prob"])
        w.writerows(rows)


def _write_csv_reversed_schema(path: Path, rows: Rows) -> None:
    """Header probability,sample_id — reversed order and renamed fields."""
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["probability", "sample_id"])
        for sid, prob in rows:
            w.writerow([prob, sid])


def _write_csv_dupid(path: Path, rows: Rows, seed: int) -> None:
    """Each ID appears twice. Second row has pred_prob offset by +0.1 (clamped)."""
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "pred_prob"])
        w.writerows(rows)  # first occurrence: canonical values
        for sid, prob in rows:  # second occurrence: offset values
            w.writerow([sid, min(1.0, round(prob + 0.1, 6))])


def _write_binary_corrupt(path: Path) -> None:
    path.write_bytes(os.urandom(1024))


def _write_csv_truncated(path: Path, rows: Rows) -> None:
    """All rows except last written cleanly; last line cut mid-value."""
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "pred_prob"])
        w.writerows(rows[:-1])  # all but the last row
    # Append a cut-off last line (no newline, no closing digit)
    with open(path, "a") as fh:
        last_sid, _ = rows[-1]
        fh.write(f"{last_sid},0.")  # intentionally incomplete


# ---------------------------------------------------------------------------
# Per-difficulty generators
# ---------------------------------------------------------------------------

def _id_block(start: int, count: int) -> List[Tuple[int, str]]:
    """Return [(n, sample_id), ...] for n in [start, start+count)."""
    return [(n, f"sample_{n:05d}") for n in range(start, start + count)]


def _rows(seed: int, id_block: List[Tuple[int, str]]) -> Rows:
    return [(sid, _pred_prob(seed, n)) for n, sid in id_block]


def _write_easy(pred_dir: Path, seed: int, rpf: int) -> None:
    for i in range(5):
        start = i * rpf + 1
        r = _rows(seed, _id_block(start, rpf))
        _write_csv_standard(pred_dir / f"predictions_0{i + 1}.csv", r)


def _write_medium(pred_dir: Path, seed: int, rpf: int) -> None:
    # Files 01-05: standard CSV
    for i in range(5):
        start = i * rpf + 1
        r = _rows(seed, _id_block(start, rpf))
        _write_csv_standard(pred_dir / f"predictions_0{i + 1}.csv", r)

    # File 06: JSONL canonical (IDs 5*rpf+1 to 6*rpf)
    r6 = _rows(seed, _id_block(5 * rpf + 1, rpf))
    _write_jsonl_canonical(pred_dir / "predictions_06.jsonl", r6)

    # File 07: JSONL canonical (IDs 6*rpf+1 to 7*rpf)
    r7 = _rows(seed, _id_block(6 * rpf + 1, rpf))
    _write_jsonl_canonical(pred_dir / "predictions_07.jsonl", r7)

    # File 08: truncated CSV (IDs 7*rpf+1 to 8*rpf; last row cut)
    r8 = _rows(seed, _id_block(7 * rpf + 1, rpf))
    _write_csv_truncated(pred_dir / "predictions_08.csv", r8)


def _write_hard(pred_dir: Path, seed: int, rpf: int) -> None:
    # File 01: standard CSV
    _write_csv_standard(pred_dir / "predictions_01.csv",
                        _rows(seed, _id_block(1, rpf)))

    # File 02: BOM CSV
    _write_csv_bom(pred_dir / "predictions_02_bom.csv",
                   _rows(seed, _id_block(rpf + 1, rpf)))

    # File 03: no-header CSV
    _write_csv_noheader(pred_dir / "predictions_03_noheader.csv",
                        _rows(seed, _id_block(2 * rpf + 1, rpf)))

    # File 04: quoted CSV with mixed CRLF+LF
    _write_csv_quoted_mixed_endings(pred_dir / "predictions_04_quoted.csv",
                                    _rows(seed, _id_block(3 * rpf + 1, rpf)))

    # File 05: JSONL with non-canonical schema (sample_id / probability)
    _write_jsonl_noncanonical_schema(pred_dir / "predictions_05.jsonl",
                                     _rows(seed, _id_block(4 * rpf + 1, rpf)))

    # File 06: JSONL with # comment lines
    _write_jsonl_with_comments(pred_dir / "predictions_06.jsonl",
                                _rows(seed, _id_block(5 * rpf + 1, rpf)))

    # File 07: JSON array, string-typed pred_prob, non-canonical field name
    _write_json_array_string_probs(pred_dir / "predictions_07.json",
                                   _rows(seed, _id_block(6 * rpf + 1, rpf)))

    # File 08: gzipped standard CSV
    _write_csv_gz(pred_dir / "predictions_08.csv.gz",
                  _rows(seed, _id_block(7 * rpf + 1, rpf)))

    # File 09: reversed-schema CSV (probability, sample_id)
    _write_csv_reversed_schema(pred_dir / "predictions_09_schema.csv",
                                _rows(seed, _id_block(8 * rpf + 1, rpf)))

    # File 10: dup-id CSV (each ID appears twice; first occurrence canonical)
    _write_csv_dupid(pred_dir / "predictions_10_dupid.csv",
                     _rows(seed, _id_block(9 * rpf + 1, rpf)),
                     seed)

    # Files 11-12: binary corrupt
    _write_binary_corrupt(pred_dir / "predictions_11.bin")
    _write_binary_corrupt(pred_dir / "predictions_12.bin")


# ---------------------------------------------------------------------------
# Reference output helper (used to generate grader/reference_output.csv)
# ---------------------------------------------------------------------------

def generate_reference(output_path: Path, seed: int, difficulty: str) -> None:
    """Generate the grader reference CSV directly from the pred_prob formula.

    Does not parse generated files; recomputes pred_probs deterministically.
    """
    rpf = _ROWS_PER_FILE[difficulty]
    if difficulty == "easy":
        total_ids = 5 * rpf           # 1 000
        excluded: set[int] = set()
    elif difficulty == "medium":
        # 5 CSV + 2 JSONL = 7 full files = 7*rpf IDs
        # truncated file adds rpf-1 valid rows (last ID excluded)
        total_ids = 7 * rpf + rpf - 1  # 3 499
        excluded = set()  # IDs 1 to 7*rpf+(rpf-1) = 8*rpf-1 are all valid
        # Note: we iterate range(1, 8*rpf) which equals 1..3999 for rpf=500
    else:  # hard
        total_ids = 10 * rpf           # 10 000 (corrupt files contribute 0)
        excluded = set()

    with open(output_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "pred_prob"])
        if difficulty == "medium":
            # IDs from files 1-7 (full) + file 8 (rpf-1 rows)
            full_end = 7 * rpf + 1            # first ID of truncated file block
            trunc_end = 8 * rpf               # last intended ID (excluded)
            for n in range(1, full_end):
                w.writerow([f"sample_{n:05d}", _pred_prob(seed, n)])
            for n in range(full_end, trunc_end):  # excludes trunc_end itself
                w.writerow([f"sample_{n:05d}", _pred_prob(seed, n)])
        else:
            for n in range(1, total_ids + 1):
                if n not in excluded:
                    w.writerow([f"sample_{n:05d}", _pred_prob(seed, n)])


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def generate(output_dir: Path, seed: int, instance_id: str) -> None:
    slug = _slug_from_instance_id(instance_id)
    difficulty = _DIFFICULTY.get(slug)
    if difficulty is None:
        raise ValueError(f"Unknown slug: {slug!r}")
    rpf = _ROWS_PER_FILE[difficulty]
    pred_dir = output_dir / "predictions"
    pred_dir.mkdir(parents=True, exist_ok=True)
    {"easy": _write_easy, "medium": _write_medium, "hard": _write_hard}[difficulty](
        pred_dir, seed, rpf
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--instance-id", type=str, required=True)
    ap.add_argument("--reference-output", type=Path, default=None,
                    help="If given, also write grader reference CSV to this path.")
    args = ap.parse_args()
    generate(args.output_dir, args.seed, args.instance_id)
    if args.reference_output:
        slug = _slug_from_instance_id(args.instance_id)
        difficulty = _DIFFICULTY[slug]
        args.reference_output.parent.mkdir(parents=True, exist_ok=True)
        generate_reference(args.reference_output, args.seed, difficulty)


if __name__ == "__main__":
    main()
