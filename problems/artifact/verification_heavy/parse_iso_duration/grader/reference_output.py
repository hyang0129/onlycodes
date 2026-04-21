"""Reference implementation of parse_iso_duration for algorithmic__parse_iso_duration.

This file is copied verbatim to output/solution.py by verify_graders.py and
by the hidden grader when seeding the reference check.
"""

import re
from datetime import timedelta


def parse_iso_duration(s: str) -> timedelta:
    """Parse an ISO 8601 duration string into a datetime.timedelta.

    Supports the date and time components P[n]W[n]DT[n]H[n]M[n]S.
    Year (Y) and month (M in date part) are not supported — use weeks/days.
    Components may be integers or decimals (e.g. PT1.5H).

    Raises ValueError on invalid input.
    """
    # Require the leading "P"
    if not s.startswith("P"):
        raise ValueError(f"ISO 8601 duration must start with 'P': {s!r}")

    # Split on T to separate date and time parts
    if "T" in s:
        date_part, time_part = s[1:].split("T", 1)
    else:
        date_part, time_part = s[1:], ""

    _NUM = r"(\d+(?:\.\d+)?)"

    def _extract(part: str, designator: str) -> float:
        m = re.search(_NUM + designator, part)
        return float(m.group(1)) if m else 0.0

    weeks = _extract(date_part, "W")
    days = _extract(date_part, "D")
    hours = _extract(time_part, "H")
    minutes = _extract(time_part, "M")
    seconds = _extract(time_part, "S")

    # Validate: after stripping known components, nothing unexpected remains
    clean_date = re.sub(_NUM + "[WD]", "", date_part)
    clean_time = re.sub(_NUM + "[HMS]", "", time_part)
    if clean_date.strip() or clean_time.strip():
        raise ValueError(f"Unrecognised components in duration: {s!r}")

    return timedelta(
        weeks=weeks,
        days=days,
        hours=hours,
        minutes=minutes,
        seconds=seconds,
    )
