"""Structural verifier for data_processing__multi_file_cohort.

Checks output/top_products.jsonl exists, has 5 lines, each line parses
as JSON with keys product_id (str) and total_revenue (positive number).
Does NOT check correctness.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main(scratch_dir: str | None = None) -> None:
    if scratch_dir is None:
        # When invoked standalone, use the directory of this script as the root.
        base = Path(__file__).parent
    else:
        base = Path(scratch_dir)

    output_path = base / "output" / "top_products.jsonl"

    errors: list[str] = []

    # 1. File must exist.
    if not output_path.is_file():
        print(f"FAIL: output artifact not found: {output_path}")
        sys.exit(1)

    # 2. Parse lines.
    raw_lines = [l for l in output_path.read_text().splitlines() if l.strip()]

    # 3. Exactly 5 lines.
    if len(raw_lines) != 5:
        errors.append(f"expected 5 lines, got {len(raw_lines)}")

    # 4. Each line must be valid JSON with required keys and correct types.
    for i, line in enumerate(raw_lines, start=1):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"line {i} is not valid JSON: {exc}")
            continue

        if not isinstance(obj.get("product_id"), str):
            errors.append(f"line {i}: 'product_id' must be a string, got {type(obj.get('product_id')).__name__}")

        rev = obj.get("total_revenue")
        if not isinstance(rev, (int, float)):
            errors.append(f"line {i}: 'total_revenue' must be a number, got {type(rev).__name__}")
        elif rev <= 0:
            errors.append(f"line {i}: 'total_revenue' must be positive, got {rev}")

    if errors:
        for err in errors:
            print(f"FAIL: {err}")
        sys.exit(1)

    print("OK: output/top_products.jsonl has 5 valid entries")
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
