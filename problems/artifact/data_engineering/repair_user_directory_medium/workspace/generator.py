#!/usr/bin/env python3
"""Workspace generator for ``data_engineering__repair_user_directory_medium``.

Produces ``user_directory_raw.csv``: a single CSV with five columns whose
values exhibit the schema problems described in the task prompt.

Run with ``--seed 42`` (the canonical seed) to reproduce the committed
fixture, or omit ``--out`` to write into the same directory as this script
during local authoring.

Realistic messiness injected:

* ``email`` — ~30% of values are mixed-case; ~5% are the empty string.
* ``country`` — uniform draw from a pool of mapped variants and a small
  pool of unmapped variants (~8%) which must be dropped.
* ``age`` — ~10% empty / ``N/A`` / ``unknown`` / ``null`` / ``-``,
  ~3% word form (``twenty``), ~5% out-of-range integers, rest valid ints.
* ``is_active`` — uniform draw over the eight accepted boolean variants.
"""

from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

_N_ROWS = 250

_MAPPED_COUNTRY_VARIANTS = {
    "US": ["us", "USA", "U.S.", "U.S.A.", "United States", "America", "USA"],
    "GB": ["gb", "UK", "U.K.", "United Kingdom", "Britain", "Great Britain"],
    "FR": ["fr", "France", "FR"],
    "DE": ["de", "Germany", "Deutschland", "DE"],
    "JP": ["jp", "Japan", "JP"],
    "CA": ["ca", "Canada", "CA"],
}
_UNMAPPED_COUNTRY_VARIANTS = ["Mars", "Atlantis", "?", "XX", "Wakanda"]

_AGE_NULL_TOKENS = ["", "N/A", "unknown", "null", "-", "n/a", "None"]
_AGE_WORD_FORMS = ["twenty", "thirty", "forty-two"]

_BOOLEAN_TRUE_VARIANTS = ["yes", "Y", "true", "TRUE", "1"]
_BOOLEAN_FALSE_VARIANTS = ["no", "N", "false", "FALSE", "0", ""]

_FIRST_NAMES = [
    "jane", "john", "alex", "sam", "taylor", "morgan", "casey", "jordan",
    "riley", "avery", "rowan", "quinn", "blake", "drew", "kai", "max",
    "noa", "remy", "sage", "robin",
]
_DOMAINS = ["example.com", "mail.test", "corp.example", "users.io"]


def _maybe_mixed_case(s: str, rng: random.Random) -> str:
    """Return ``s`` with random capitalization on ~30% of calls."""
    if rng.random() < 0.30:
        return "".join(c.upper() if rng.random() < 0.5 else c.lower() for c in s)
    return s


def _gen_email(rng: random.Random, idx: int) -> str:
    if rng.random() < 0.05:
        return ""
    name = rng.choice(_FIRST_NAMES)
    domain = rng.choice(_DOMAINS)
    raw = f"{name}{idx:04d}@{domain}"
    return _maybe_mixed_case(raw, rng)


def _gen_country(rng: random.Random) -> str:
    if rng.random() < 0.08:
        return rng.choice(_UNMAPPED_COUNTRY_VARIANTS)
    code = rng.choice(list(_MAPPED_COUNTRY_VARIANTS.keys()))
    return rng.choice(_MAPPED_COUNTRY_VARIANTS[code])


def _gen_age(rng: random.Random) -> str:
    r = rng.random()
    if r < 0.10:
        return rng.choice(_AGE_NULL_TOKENS)
    if r < 0.13:
        return rng.choice(_AGE_WORD_FORMS)
    if r < 0.18:
        # out of range
        candidates = [-1, 0, 5, 12, 121, 200, 999]
        return str(rng.choice(candidates))
    return str(rng.randint(13, 120))


def _gen_is_active(rng: random.Random) -> str:
    if rng.random() < 0.5:
        return rng.choice(_BOOLEAN_TRUE_VARIANTS)
    return rng.choice(_BOOLEAN_FALSE_VARIANTS)


def generate(out_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    rows = []
    for i in range(1, _N_ROWS + 1):
        rows.append(
            {
                "user_id": f"U-{i:06d}",
                "email": _gen_email(rng, i),
                "country": _gen_country(rng),
                "age": _gen_age(rng),
                "is_active": _gen_is_active(rng),
            }
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    cols = ["user_id", "email", "country", "age", "is_active"]
    with open(out_dir / "user_directory_raw.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=False,
        default=Path(__file__).parent,
        help="Directory to write generated files (default: alongside generator.py)",
    )
    parser.add_argument("--instance-id", type=str, required=False, default="")
    args = parser.parse_args()
    generate(args.output_dir, args.seed)


if __name__ == "__main__":
    main()
