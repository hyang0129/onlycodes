#!/usr/bin/env python3
"""Workspace generator for verification_heavy__iban_validator. Stdlib-only.

Writes ``examples.json``: a seeded mix of canonical valid IBANs (per ISO 13616),
deliberately broken IBANs, and a few format-violation samples. The agent uses
these for development; the hidden grader runs its own larger property set.
"""

from __future__ import annotations
import argparse, json, random
from pathlib import Path

# Well-known valid IBANs (from public ISO 13616 documentation / banking sites).
_KNOWN_VALID = [
    "DE89370400440532013000",
    "GB82WEST12345698765432",
    "FR1420041010050500013M02606",
    "ES9121000418450200051332",
    "IT60X0542811101000000123456",
    "NL91ABNA0417164300",
    "CH9300762011623852957",
    "BE68539007547034",
]


def _mutate_digit(s: str, rng: random.Random) -> str:
    # Flip one digit in the IBAN body (positions >= 4) to break the checksum.
    for _ in range(10):
        i = rng.randint(4, len(s) - 1)
        if s[i].isdigit():
            new = str((int(s[i]) + rng.randint(1, 9)) % 10)
            return s[:i] + new + s[i + 1:]
    return s + "0"  # fallback: changes length (also invalid)


def _truncate(s: str) -> str:
    return s[:-1]


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    examples = []
    for _ in range(4):
        examples.append({"iban": rng.choice(_KNOWN_VALID), "expected": True})
    for _ in range(3):
        examples.append({"iban": _mutate_digit(rng.choice(_KNOWN_VALID), rng),
                         "expected": False})
    examples.append({"iban": _truncate(rng.choice(_KNOWN_VALID)), "expected": False})
    examples.append({"iban": "XX89370400440532013000", "expected": False})
    payload = {
        "description": (
            "Seeded sample IBAN strings for development. The hidden grader runs "
            "its own larger property set."
        ),
        "examples": examples,
    }
    (output_dir / "examples.json").write_text(json.dumps(payload, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--instance-id", type=str, required=False, default="")
    args = ap.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    generate(args.output_dir, args.seed)


if __name__ == "__main__":
    main()
