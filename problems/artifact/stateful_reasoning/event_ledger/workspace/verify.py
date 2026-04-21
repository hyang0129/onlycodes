"""Structural verifier for stateful_reasoning__event_ledger.

Checks that the output artifact exists and has the correct structure.
Does NOT check correctness of values.
"""
import json
import sys
from pathlib import Path


def verify(scratch_dir: str) -> tuple[bool, str]:
    output_path = Path(scratch_dir) / "output" / "result.json"

    if not output_path.exists():
        return False, f"output artifact not found: {output_path}"

    try:
        data = json.loads(output_path.read_text())
    except Exception as exc:
        return False, f"output artifact is not valid JSON: {exc}"

    if not isinstance(data, dict):
        return False, f"output must be a JSON object, got {type(data).__name__}"

    if "balances" not in data:
        return False, "output missing required key 'balances'"

    if "rejected" not in data:
        return False, "output missing required key 'rejected'"

    balances = data["balances"]
    if not isinstance(balances, dict):
        return False, f"'balances' must be an object, got {type(balances).__name__}"

    if len(balances) != 30:
        return False, f"'balances' must have 30 entries, got {len(balances)}"

    for acc, val in balances.items():
        if not isinstance(val, (int, float)):
            return False, f"balance for {acc!r} is not a number: {val!r}"

    rejected = data["rejected"]
    if not isinstance(rejected, list):
        return False, f"'rejected' must be an array, got {type(rejected).__name__}"

    return True, f"structural check passed: 30 accounts in balances, {len(rejected)} rejected transactions listed"


if __name__ == "__main__":
    scratch = sys.argv[1] if len(sys.argv) > 1 else "."
    ok, msg = verify(scratch)
    print(msg)
    sys.exit(0 if ok else 1)
