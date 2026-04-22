"""Reference next_fire() for verification_heavy__cron_next_fire.

Implements a minute-by-minute cron schedule resolver by expanding each of the
five fields to an explicit set of legal values and walking the minute axis
forward from `after + 1 minute`. Worst-case lookahead is 4 years.

Vixie-cron DOM/DOW OR semantics:
  - If BOTH fields are restricted (not '*'), fire if either matches.
  - If ONE is '*' and the other is restricted, only the restricted one applies.
"""

from datetime import datetime, timedelta


_RANGES = {
    "minute":       (0, 59),
    "hour":         (0, 23),
    "day_of_month": (1, 31),
    "month":        (1, 12),
    "day_of_week":  (0, 6),
}


def _parse_field(field: str, lo: int, hi: int) -> tuple[set[int], bool]:
    """Return (values, is_star)."""
    if field == "*":
        return set(range(lo, hi + 1)), True

    values: set[int] = set()
    for chunk in field.split(","):
        step = 1
        if "/" in chunk:
            base, step_s = chunk.split("/", 1)
            step = int(step_s)
        else:
            base = chunk

        if base == "*":
            start, end = lo, hi
        elif "-" in base:
            a_s, b_s = base.split("-", 1)
            start, end = int(a_s), int(b_s)
        else:
            start = int(base)
            # With a step and a single base (e.g. "0/20"), treat it as
            # "start at base, step upward to field max".
            end = hi if step != 1 else start

        for v in range(start, end + 1, step):
            values.add(v)

    return values, False


def next_fire(expr: str, after: datetime) -> datetime:
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError(f"cron expression must have 5 fields, got {len(parts)}: {expr!r}")

    min_vals, _ = _parse_field(parts[0], *_RANGES["minute"])
    hr_vals, _  = _parse_field(parts[1], *_RANGES["hour"])
    dom_vals, dom_star = _parse_field(parts[2], *_RANGES["day_of_month"])
    mon_vals, _ = _parse_field(parts[3], *_RANGES["month"])
    dow_vals, dow_star = _parse_field(parts[4], *_RANGES["day_of_week"])

    # Walk minute by minute from the next minute after `after`.
    candidate = (after + timedelta(minutes=1)).replace(second=0, microsecond=0)
    # Cap lookahead: 4 years of minutes.
    horizon = candidate + timedelta(days=366 * 4)

    while candidate <= horizon:
        if candidate.month not in mon_vals:
            # Fast-forward to 1st of next legal month
            m = candidate.month + 1
            y = candidate.year
            while True:
                if m > 12:
                    m = 1
                    y += 1
                if m in mon_vals:
                    break
                m += 1
            candidate = datetime(y, m, 1, 0, 0)
            continue

        # Day match (Vixie-cron OR semantics)
        # Python weekday(): Monday=0..Sunday=6. Cron: Sunday=0..Saturday=6.
        cron_dow = (candidate.weekday() + 1) % 7
        dom_match = candidate.day in dom_vals
        dow_match = cron_dow in dow_vals

        if dom_star and dow_star:
            day_ok = True
        elif dom_star and not dow_star:
            day_ok = dow_match
        elif dow_star and not dom_star:
            day_ok = dom_match
        else:
            day_ok = dom_match or dow_match

        if not day_ok:
            # Advance to next day at 00:00
            next_day = candidate.replace(hour=0, minute=0) + timedelta(days=1)
            candidate = next_day
            continue

        if candidate.hour not in hr_vals:
            # Advance to next hour :00
            next_hr = candidate.replace(minute=0) + timedelta(hours=1)
            candidate = next_hr
            continue

        if candidate.minute not in min_vals:
            candidate = candidate + timedelta(minutes=1)
            continue

        return candidate

    raise ValueError(f"no cron match within 4 years for {expr!r} after {after!r}")
