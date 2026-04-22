"""Public STRUCTURAL verifier for funnel_conversion. Shape only."""

from __future__ import annotations

import json
from pathlib import Path

_STEPS = ["signup", "verify_email", "onboarding_complete", "first_action", "subscribe"]
_STEP_KEYS = {"step", "reached", "rate_from_prev"}
_TOP_KEYS = {"total_signups", "steps"}


def verify(artifact_path: Path) -> None:
    artifact_path = Path(artifact_path)
    assert artifact_path.is_file(), f"artifact not found: {artifact_path}"

    raw = artifact_path.read_text().strip()
    assert raw, "artifact is empty"

    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"artifact is not valid JSON ({exc.msg})") from None

    assert isinstance(doc, dict), "top-level must be an object"
    keys = set(doc.keys())
    missing = _TOP_KEYS - keys
    extra = keys - _TOP_KEYS
    assert not missing, f"missing top-level key(s): {sorted(missing)}"
    assert not extra, f"unexpected top-level key(s): {sorted(extra)}"

    total = doc["total_signups"]
    assert isinstance(total, int) and not isinstance(total, bool), (
        "total_signups must be int"
    )
    assert total >= 0, "total_signups must be >= 0"

    steps = doc["steps"]
    assert isinstance(steps, list), "steps must be a list"
    assert len(steps) == 5, f"steps must have exactly 5 entries, got {len(steps)}"

    prev_reached = None
    for idx, entry in enumerate(steps):
        assert isinstance(entry, dict), f"steps[{idx}] must be an object"
        ks = set(entry.keys())
        miss = _STEP_KEYS - ks
        ex = ks - _STEP_KEYS
        assert not miss, f"steps[{idx}] missing {sorted(miss)}"
        assert not ex, f"steps[{idx}] unexpected {sorted(ex)}"

        assert entry["step"] == _STEPS[idx], (
            f"steps[{idx}].step must be {_STEPS[idx]!r}, got {entry['step']!r}"
        )
        reached = entry["reached"]
        assert isinstance(reached, int) and not isinstance(reached, bool), (
            f"steps[{idx}].reached must be int"
        )
        assert reached >= 0, f"steps[{idx}].reached must be >= 0"

        rate = entry["rate_from_prev"]
        assert isinstance(rate, (int, float)) and not isinstance(rate, bool), (
            f"steps[{idx}].rate_from_prev must be a number"
        )
        assert 0.0 <= float(rate) <= 1.0 + 1e-9, (
            f"steps[{idx}].rate_from_prev {rate} outside [0, 1]"
        )

        if prev_reached is not None:
            assert reached <= prev_reached, (
                f"steps[{idx}].reached ({reached}) exceeds prev step's "
                f"reached ({prev_reached}) — funnel must be monotone non-increasing"
            )
        prev_reached = reached

    assert steps[0]["reached"] == total, (
        "steps[0] (signup).reached must equal total_signups"
    )
