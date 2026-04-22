"""Hidden grader for data_processing__cohort_retention.

Recomputes the 12-week Monday-cohort retention matrix from signups.csv +
activity.csv and compares exactly (with float tolerance on retention_rate).
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import math
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


SIGNUPS_REL = "signups.csv"
ACTIVITY_REL = "activity.csv"
OUTPUT_REL = "output/retention.json"

RATE_ABS_TOL = 1e-4

TOP_KEYS = frozenset({"cohorts"})
COHORT_KEYS = frozenset({"cohort_week", "cohort_size", "retention"})
RET_KEYS = frozenset({"week_offset", "active_users", "retention_rate"})


def _monday(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())


def _truth(scratch_dir: Path) -> dict:
    signups: dict[str, dt.date] = {}
    with open(scratch_dir / SIGNUPS_REL, newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            signups[row["user_id"]] = dt.date.fromisoformat(row["signup_date"])

    # Activity filtered to users present in signups.
    activity_by_user: dict[str, set[dt.date]] = {}
    with open(scratch_dir / ACTIVITY_REL, newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            uid = row["user_id"]
            if uid not in signups:
                continue
            d = dt.date.fromisoformat(row["activity_date"])
            activity_by_user.setdefault(uid, set()).add(d)

    if not signups:
        return {"cohorts": []}

    max_signup = max(signups.values())
    max_monday = _monday(max_signup)

    allowed_cohorts = {max_monday - dt.timedelta(days=7 * k) for k in range(12)}

    # Group users by their cohort Monday, filter to allowed.
    cohort_users: dict[dt.date, list[str]] = {}
    for uid, sdate in signups.items():
        cw = _monday(sdate)
        if cw in allowed_cohorts:
            cohort_users.setdefault(cw, []).append(uid)

    cohorts_out = []
    for cw in sorted(cohort_users.keys()):
        users = cohort_users[cw]
        n = len(users)
        max_offset = (max_monday - cw).days // 7
        retention = []
        for offset in range(max_offset + 1):
            wk_start = cw + dt.timedelta(days=7 * offset)
            wk_end = wk_start + dt.timedelta(days=6)
            count = 0
            for uid in users:
                acts = activity_by_user.get(uid)
                if not acts:
                    continue
                # Any activity date in [wk_start, wk_end]?
                for d in acts:
                    if wk_start <= d <= wk_end:
                        count += 1
                        break
            rate = 0.0 if n == 0 else count / n
            retention.append({
                "week_offset": offset,
                "active_users": count,
                "retention_rate": round(rate, 4),
            })
        cohorts_out.append({
            "cohort_week": cw.isoformat(),
            "cohort_size": n,
            "retention": retention,
        })

    return {"cohorts": cohorts_out}


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()
    if not (scratch_dir / SIGNUPS_REL).is_file():
        return GradeResult(False, 0.0, f"{SIGNUPS_REL} not found")
    if not (scratch_dir / ACTIVITY_REL).is_file():
        return GradeResult(False, 0.0, f"{ACTIVITY_REL} not found")
    outp = scratch_dir / OUTPUT_REL
    if not outp.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    try:
        doc = json.loads(outp.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return GradeResult(False, 0.0, f"bad output JSON: {exc}")

    if not isinstance(doc, dict):
        return GradeResult(False, 0.0, "output not an object")
    keys = set(doc.keys())
    if keys != TOP_KEYS:
        missing = TOP_KEYS - keys
        extra = keys - TOP_KEYS
        bits = []
        if missing:
            bits.append(f"missing {sorted(missing)}")
        if extra:
            bits.append(f"extra {sorted(extra)}")
        return GradeResult(False, 0.0, f"top-level: {'; '.join(bits)}")

    truth = _truth(scratch_dir)

    got_cohorts = doc["cohorts"]
    if not isinstance(got_cohorts, list):
        return GradeResult(False, 0.0, "cohorts not a list")

    if len(got_cohorts) != len(truth["cohorts"]):
        return GradeResult(
            False, 0.0,
            f"cohort count mismatch: got {len(got_cohorts)}, expected {len(truth['cohorts'])}",
        )

    for i, (got, want) in enumerate(zip(got_cohorts, truth["cohorts"])):
        if not isinstance(got, dict):
            return GradeResult(False, 0.0, f"cohorts[{i}] not object")
        ks = set(got.keys())
        if ks != COHORT_KEYS:
            missing = COHORT_KEYS - ks
            extra = ks - COHORT_KEYS
            bits = []
            if missing:
                bits.append(f"missing {sorted(missing)}")
            if extra:
                bits.append(f"extra {sorted(extra)}")
            return GradeResult(False, 0.0, f"cohorts[{i}]: {'; '.join(bits)}")

        if got["cohort_week"] != want["cohort_week"]:
            return GradeResult(
                False, 0.0,
                f"cohorts[{i}].cohort_week {got['cohort_week']!r} != expected "
                f"{want['cohort_week']!r}",
            )
        cs = got["cohort_size"]
        if isinstance(cs, bool) or not isinstance(cs, int):
            return GradeResult(False, 0.0, f"cohorts[{i}].cohort_size not int")
        if cs != want["cohort_size"]:
            return GradeResult(
                False, 0.0,
                f"cohort {want['cohort_week']}: size {cs} != expected {want['cohort_size']}",
            )

        got_ret = got["retention"]
        want_ret = want["retention"]
        if not isinstance(got_ret, list) or len(got_ret) != len(want_ret):
            return GradeResult(
                False, 0.0,
                f"cohort {want['cohort_week']}: retention length mismatch "
                f"(got {len(got_ret) if isinstance(got_ret, list) else 'non-list'}, "
                f"expected {len(want_ret)})",
            )
        for j, (gr, wr) in enumerate(zip(got_ret, want_ret)):
            if not isinstance(gr, dict):
                return GradeResult(False, 0.0, f"cohort {want['cohort_week']} ret[{j}] not object")
            ks = set(gr.keys())
            if ks != RET_KEYS:
                missing = RET_KEYS - ks
                extra = ks - RET_KEYS
                bits = []
                if missing:
                    bits.append(f"missing {sorted(missing)}")
                if extra:
                    bits.append(f"extra {sorted(extra)}")
                return GradeResult(
                    False, 0.0,
                    f"cohort {want['cohort_week']} ret[{j}]: {'; '.join(bits)}",
                )
            for f_ in ("week_offset", "active_users"):
                gv = gr[f_]
                if isinstance(gv, bool) or not isinstance(gv, int):
                    return GradeResult(
                        False, 0.0,
                        f"cohort {want['cohort_week']} ret[{j}].{f_} not int",
                    )
                if gv != wr[f_]:
                    return GradeResult(
                        False, 0.0,
                        f"cohort {want['cohort_week']} ret[{j}].{f_}: "
                        f"got {gv}, expected {wr[f_]}",
                    )
            rate = gr["retention_rate"]
            if isinstance(rate, bool) or not isinstance(rate, (int, float)):
                return GradeResult(
                    False, 0.0,
                    f"cohort {want['cohort_week']} ret[{j}].retention_rate not number",
                )
            if not math.isfinite(float(rate)):
                return GradeResult(False, 0.0, "retention_rate not finite")
            if abs(float(rate) - wr["retention_rate"]) > RATE_ABS_TOL:
                return GradeResult(
                    False, 0.0,
                    f"cohort {want['cohort_week']} ret[{j}].retention_rate "
                    f"{rate} != expected ~{wr['retention_rate']}",
                )

    return GradeResult(
        True, 1.0,
        f"matched {len(truth['cohorts'])} cohorts "
        f"({sum(len(c['retention']) for c in truth['cohorts'])} cells)",
    )
