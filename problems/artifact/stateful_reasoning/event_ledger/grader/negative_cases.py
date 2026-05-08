"""Per-task negative cases for ``stateful_reasoning__event_ledger``.

The prompt requires ``rejected`` to be a JSON **array** in **chronological
order** (the order the rejected transactions were encountered while
replaying the ledger). The grader, however, compares ``rejected`` as a
*set*, so any permutation slips through. That's the bug issue #171 calls
out as ``event_ledger rejected order``.

The ``reversed_rejected`` case below is annotated ``currently_caught=False``
— the grader incorrectly accepts a reversed rejected list today. Flip to
``True`` once the grader enforces chronological order (and / or list-vs-set
semantics) per the prompt.
"""

from __future__ import annotations

import json

from swebench.artifact_negative import (
    NegativeCase,
    _mutate_empty,
    _mutate_truncate_half,
    _mutate_wrap_in_list,
)


def _mutate_reverse_rejected(text: str) -> str:
    """Reverse the order of the rejected[] list while leaving balances alone.

    The prompt requires chronological order; reversing it should make a
    well-aligned grader fail. The current grader compares as a set and
    accepts.
    """
    payload = json.loads(text)
    rejected = list(payload.get("rejected", []))
    if len(rejected) <= 1:
        # Reversing a 0/1-element list is a no-op; nudge it to be
        # detectably different.
        rejected = rejected + ["__INSERTED__"]
    else:
        rejected.reverse()
    payload["rejected"] = rejected
    return json.dumps(payload, indent=2) + "\n"


def _mutate_rejected_as_set(text: str) -> str:
    """Convert rejected list to a JSON object (dict) — wrong shape.

    A grader that doesn't check shape will silently coerce dict-keys to a
    set, masking the type bug. The well-aligned grader should reject
    non-list values for ``rejected``.
    """
    payload = json.loads(text)
    rejected = payload.get("rejected", [])
    payload["rejected"] = {tid: True for tid in rejected}
    return json.dumps(payload, indent=2) + "\n"


def _mutate_drop_balances(text: str) -> str:
    """Remove the ``balances`` key entirely — should be a structural reject."""
    payload = json.loads(text)
    payload.pop("balances", None)
    return json.dumps(payload, indent=2) + "\n"


def _mutate_off_by_one_balance(text: str) -> str:
    """Shift one account balance by 100.00 so it's outside tolerance."""
    payload = json.loads(text)
    if not payload.get("balances"):
        return text + "_"
    first = next(iter(payload["balances"]))
    payload["balances"][first] = round(float(payload["balances"][first]) + 100.0, 2)
    return json.dumps(payload, indent=2) + "\n"


def _mutate_drop_rejected_entry(text: str) -> str:
    """Drop one transaction id from rejected — sets diverge → grader fails."""
    payload = json.loads(text)
    rejected = list(payload.get("rejected", []))
    if not rejected:
        return text + "_"
    payload["rejected"] = rejected[1:]
    return json.dumps(payload, indent=2) + "\n"


NEGATIVE_CASES = [
    NegativeCase(
        name="empty",
        mutate=_mutate_empty,
        # Empty file is produced (just empty content) → JSON parse error.
        expected_substring="could not parse",
    ),
    NegativeCase(
        name="truncated_half",
        mutate=_mutate_truncate_half,
        # Truncating mid-JSON triggers a parse error.
        expected_substring="parse",
    ),
    NegativeCase(
        name="missing_balances_key",
        mutate=_mutate_drop_balances,
        expected_substring="missing 'balances'",
    ),
    NegativeCase(
        name="off_by_one_balance",
        mutate=_mutate_off_by_one_balance,
        expected_substring="wrong balances",
    ),
    NegativeCase(
        name="dropped_rejected_entry",
        mutate=_mutate_drop_rejected_entry,
        expected_substring="rejected mismatch",
    ),
    NegativeCase(
        name="reversed_rejected",
        mutate=_mutate_reverse_rejected,
        # PROMPT-VS-GRADER ALIGNMENT BUG: prompt requires chronological order,
        # grader uses set-equality. Reversing slips through today.
        expected_substring="order",
        currently_caught=False,
        notes="issue #171 — event_ledger rejected list-vs-set bug",
    ),
    NegativeCase(
        name="rejected_as_dict",
        mutate=_mutate_rejected_as_set,
        # PROMPT-VS-GRADER ALIGNMENT BUG: ``rejected`` is required to be a
        # list. The grader's ``set(...)`` coerces a dict to its key-set so
        # this slips through.
        expected_substring="list",
        currently_caught=False,
        notes="issue #171 — event_ledger list-vs-set bug (dict coercion)",
    ),
    NegativeCase(
        name="wrap_in_list",
        mutate=_mutate_wrap_in_list,
        expected_substring="",  # JSON object expected; list parses but isinstance fails
    ),
]
