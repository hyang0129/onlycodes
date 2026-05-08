"""Per-task negative cases for ``stateful_reasoning__counter_replay``.

Issue #166 tightened the grader to enforce alphabetical key order on the
agent's JSON object (the prompt says "sorted by name (alphabetical) so
diffs are stable"). This module locks that behaviour in: a shuffled-key
mutation MUST be rejected; a wrong-value mutation MUST also be rejected.
"""

from __future__ import annotations

import json

from swebench.artifact_negative import (
    NegativeCase,
    _mutate_empty,
    _mutate_truncate_half,
    _mutate_wrap_in_list,
)


def _mutate_reverse_key_order(text: str) -> str:
    """Reverse the alphabetical key order so the keys appear largest-first.

    The values stay correct; only the key insertion order changes. A grader
    that ignores key order would accept this artifact; the issue #166
    tightening rejects it.
    """
    payload = json.loads(text)
    if not isinstance(payload, dict) or len(payload) <= 1:
        return text + "_"
    reversed_payload = {k: payload[k] for k in reversed(list(payload.keys()))}
    return json.dumps(reversed_payload, indent=2) + "\n"


def _mutate_off_by_one_value(text: str) -> str:
    """Bump one counter value by 1 — caught by the value comparison."""
    payload = json.loads(text)
    if not isinstance(payload, dict) or not payload:
        return text + "_"
    first = next(iter(payload))
    payload[first] = int(payload[first]) + 1
    return json.dumps(payload, indent=2) + "\n"


def _mutate_drop_one_counter(text: str) -> str:
    """Remove one counter — caught by the missing-key check."""
    payload = json.loads(text)
    if not isinstance(payload, dict) or not payload:
        return text + "_"
    payload.pop(next(iter(payload)))
    return json.dumps(payload, indent=2) + "\n"


def _mutate_extra_counter(text: str) -> str:
    """Add a phantom counter not present in the events stream."""
    payload = json.loads(text)
    if not isinstance(payload, dict):
        return text + "_"
    payload["phantom.counter"] = 999
    return json.dumps(payload, indent=2) + "\n"


NEGATIVE_CASES = [
    NegativeCase(
        name="empty",
        mutate=_mutate_empty,
        # Empty file → JSON parse error short-circuits.
        expected_substring="not valid JSON",
    ),
    NegativeCase(
        name="truncated_half",
        mutate=_mutate_truncate_half,
        expected_substring="not valid JSON",
    ),
    NegativeCase(
        name="reversed_key_order",
        mutate=_mutate_reverse_key_order,
        # Locked in by issue #166: alphabetical key order is now enforced.
        expected_substring="alphabetical",
        notes="issue #166 — locks alphabetical key order",
    ),
    NegativeCase(
        name="off_by_one_value",
        mutate=_mutate_off_by_one_value,
        expected_substring="wrong values",
    ),
    NegativeCase(
        name="dropped_counter",
        mutate=_mutate_drop_one_counter,
        expected_substring="missing",
    ),
    NegativeCase(
        name="extra_counter",
        mutate=_mutate_extra_counter,
        expected_substring="extra",
    ),
    NegativeCase(
        name="wrap_in_list",
        mutate=_mutate_wrap_in_list,
        # Wrapping a JSON object in [...] makes it a list, not a dict.
        expected_substring="JSON object",
    ),
]
