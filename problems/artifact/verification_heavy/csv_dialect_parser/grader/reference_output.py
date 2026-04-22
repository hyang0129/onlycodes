"""Reference implementation of parse_csv_line for verification_heavy__csv_dialect_parser."""

import csv
import io


def parse_csv_line(line: str) -> list[str]:
    """Parse one CSV record into its fields (RFC 4180 subset).

    Uses csv.reader so quote handling ('""' escaping, embedded commas) is
    covered by stdlib. csv.reader on an empty string returns no rows; we
    normalise to [""] to match the documented contract.
    """
    if line == "":
        return [""]
    reader = csv.reader(io.StringIO(line))
    for row in reader:
        return row
    return [""]
