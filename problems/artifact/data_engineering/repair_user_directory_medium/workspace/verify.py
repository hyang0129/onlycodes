"""Structural verifier for ``data_engineering__repair_user_directory_medium``.

Checks ``output/users_clean.csv`` exists, has the required header, and that
every row is structurally valid (column count, type discipline, allowed
values for normalised categorical columns).  Does NOT compare against the
reference output.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

EXPECTED_COLUMNS = ["user_id", "email", "country", "age", "is_active"]
VALID_COUNTRIES = {"US", "GB", "FR", "DE", "JP", "CA"}
VALID_BOOLS = {"true", "false"}


def main(scratch_dir: str | None = None) -> None:
    base = Path(scratch_dir) if scratch_dir else Path(__file__).parent
    output_path = base / "output" / "users_clean.csv"

    if not output_path.is_file():
        print(f"FAIL: output artifact not found: {output_path}")
        sys.exit(1)

    errors: list[str] = []

    with open(output_path, newline="") as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration:
            print("FAIL: output artifact is empty")
            sys.exit(1)
        rows = list(reader)

    if header != EXPECTED_COLUMNS:
        errors.append(
            f"header must be {EXPECTED_COLUMNS} (in order); got {header}"
        )

    if not rows:
        errors.append("output has a header but zero data rows")

    seen_ids: set[str] = set()
    for i, row in enumerate(rows, start=1):
        if len(row) != 5:
            errors.append(f"row {i}: expected 5 fields, got {len(row)}")
            continue
        user_id, email, country, age, is_active = row

        if not user_id.startswith("U-") or len(user_id) != 8:
            errors.append(f"row {i}: user_id {user_id!r} has unexpected shape")
        if user_id in seen_ids:
            errors.append(f"row {i}: duplicate user_id {user_id!r}")
        seen_ids.add(user_id)

        if not email:
            errors.append(f"row {i}: email is empty (should have been dropped)")
        elif email != email.lower():
            errors.append(f"row {i}: email {email!r} is not lowercase")

        if country not in VALID_COUNTRIES:
            errors.append(
                f"row {i}: country {country!r} must be one of {sorted(VALID_COUNTRIES)}"
            )

        if age != "":
            try:
                age_int = int(age)
                if not (13 <= age_int <= 120):
                    errors.append(
                        f"row {i}: age {age!r} outside [13, 120] (should be empty)"
                    )
                if age != str(age_int):
                    errors.append(
                        f"row {i}: age {age!r} is not in plain integer form"
                    )
            except ValueError:
                errors.append(f"row {i}: age {age!r} is not an integer or empty")

        if is_active not in VALID_BOOLS:
            errors.append(
                f"row {i}: is_active {is_active!r} must be 'true' or 'false'"
            )

    # Sorting check
    ids = [r[0] for r in rows if len(r) == 5]
    if ids != sorted(ids):
        errors.append("rows are not sorted by user_id ascending")

    if errors:
        for err in errors[:20]:
            print(f"FAIL: {err}")
        if len(errors) > 20:
            print(f"FAIL: ... and {len(errors) - 20} more")
        sys.exit(1)

    print(f"OK: output/users_clean.csv has {len(rows)} structurally valid rows")
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
