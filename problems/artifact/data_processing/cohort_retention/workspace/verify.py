"""Public STRUCTURAL verifier for cohort_retention. Shape only."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

_TOP = {"cohorts"}
_COHORT = {"cohort_week", "cohort_size", "retention"}
_RET = {"week_offset", "active_users", "retention_rate"}


def verify(artifact_path: Path) -> None:
    artifact_path = Path(artifact_path)
    assert artifact_path.is_file(), f"artifact not found: {artifact_path}"

    raw = artifact_path.read_text().strip()
    assert raw, "artifact is empty"

    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"bad JSON: {exc.msg}") from None

    assert isinstance(doc, dict), "top-level must be object"
    keys = set(doc.keys())
    missing = _TOP - keys
    extra = keys - _TOP
    assert not missing, f"missing top-level {sorted(missing)}"
    assert not extra, f"extra top-level {sorted(extra)}"

    cohorts = doc["cohorts"]
    assert isinstance(cohorts, list), "cohorts must be list"
    assert cohorts, "cohorts must be non-empty"

    prev_week = ""
    for i, co in enumerate(cohorts):
        assert isinstance(co, dict), f"cohorts[{i}] not object"
        ks = set(co.keys())
        missing = _COHORT - ks
        extra = ks - _COHORT
        assert not missing, f"cohorts[{i}] missing {sorted(missing)}"
        assert not extra, f"cohorts[{i}] extra {sorted(extra)}"

        cw = co["cohort_week"]
        assert isinstance(cw, str), f"cohorts[{i}].cohort_week must be string"
        # Parse as ISO date to validate format.
        try:
            d = dt.date.fromisoformat(cw)
        except ValueError:
            raise AssertionError(f"cohorts[{i}].cohort_week {cw!r} not ISO date") from None
        assert d.weekday() == 0, (
            f"cohorts[{i}].cohort_week {cw} is not a Monday"
        )
        assert cw > prev_week, (
            f"cohorts must be sorted ascending by cohort_week "
            f"(got {prev_week!r} then {cw!r})"
        )
        prev_week = cw

        cs = co["cohort_size"]
        assert isinstance(cs, int) and not isinstance(cs, bool), (
            f"cohorts[{i}].cohort_size must be int"
        )
        assert cs > 0, f"cohorts[{i}].cohort_size must be > 0 (empty cohorts skipped)"

        rets = co["retention"]
        assert isinstance(rets, list) and rets, f"cohorts[{i}].retention must be non-empty list"
        prev_off = -1
        for j, rr in enumerate(rets):
            assert isinstance(rr, dict), f"cohorts[{i}].retention[{j}] not object"
            ks = set(rr.keys())
            miss = _RET - ks
            ex = ks - _RET
            assert not miss, f"cohorts[{i}].retention[{j}] missing {sorted(miss)}"
            assert not ex, f"cohorts[{i}].retention[{j}] extra {sorted(ex)}"
            off = rr["week_offset"]
            au = rr["active_users"]
            rate = rr["retention_rate"]
            assert isinstance(off, int) and not isinstance(off, bool), "week_offset must be int"
            assert off == prev_off + 1, (
                f"cohorts[{i}].retention[{j}].week_offset {off} not contiguous "
                f"(prev was {prev_off})"
            )
            prev_off = off
            assert isinstance(au, int) and not isinstance(au, bool), "active_users must be int"
            assert 0 <= au <= cs, f"active_users {au} out of [0, cohort_size={cs}]"
            assert isinstance(rate, (int, float)) and not isinstance(rate, bool), (
                "retention_rate must be number"
            )
            assert 0.0 <= float(rate) <= 1.0 + 1e-9, f"retention_rate {rate} outside [0,1]"

        assert rets[0]["week_offset"] == 0, (
            f"cohorts[{i}].retention must start at week_offset 0"
        )
