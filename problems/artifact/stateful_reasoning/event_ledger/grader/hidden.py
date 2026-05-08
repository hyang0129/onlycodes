"""Hidden grader for stateful_reasoning__event_ledger."""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str

OUTPUT_REL = "output/result.json"
BALANCE_TOLERANCE = 0.02  # 2 cents absolute tolerance for float arithmetic

def _replay(scratch_dir: Path):
    with open(scratch_dir / "initial_balances.json") as f:
        balances = json.load(f)
    rejected = []
    with open(scratch_dir / "transactions.jsonl") as f:
        for line in f:
            txn = json.loads(line.strip())
            t = txn["type"]
            if t == "deposit":
                balances[txn["account"]] = round(balances[txn["account"]] + txn["amount"], 2)
            elif t == "withdrawal":
                if balances[txn["account"]] >= txn["amount"]:
                    balances[txn["account"]] = round(balances[txn["account"]] - txn["amount"], 2)
                else:
                    rejected.append(txn["txn_id"])
            elif t == "transfer":
                if balances[txn["from"]] >= txn["amount"]:
                    balances[txn["from"]] = round(balances[txn["from"]] - txn["amount"], 2)
                    balances[txn["to"]] = round(balances[txn["to"]] + txn["amount"], 2)
                else:
                    rejected.append(txn["txn_id"])
    return balances, rejected

def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()
    output_path = scratch_dir / OUTPUT_REL
    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")
    try:
        agent_out = json.loads(output_path.read_text())
    except Exception as exc:
        return GradeResult(False, 0.0, f"could not parse output: {exc}")

    if not isinstance(agent_out, dict):
        return GradeResult(False, 0.0, "output must be a JSON object")
    if "balances" not in agent_out or "rejected" not in agent_out:
        return GradeResult(False, 0.0, "output missing 'balances' or 'rejected' key")

    expected_balances, expected_rejected = _replay(scratch_dir)

    # Check balances
    agent_balances = agent_out["balances"]
    missing = set(expected_balances) - set(agent_balances)
    if missing:
        return GradeResult(False, 0.0, f"missing accounts in balances: {sorted(missing)[:5]}")

    wrong_balances = []
    for acc, exp_bal in expected_balances.items():
        agent_bal = float(agent_balances.get(acc, -999999))
        if abs(agent_bal - exp_bal) > BALANCE_TOLERANCE:
            wrong_balances.append(f"{acc}: got {agent_bal:.2f}")
    if wrong_balances:
        return GradeResult(False, 0.0, f"wrong balances: {wrong_balances[:3]}")

    # Check rejected: per the prompt, this MUST be a JSON array in chronological
    # order (the order rejections were encountered while replaying). Issue #166
    # tightened the grader from set-comparison to typed-list-and-order: a wrong
    # shape (dict, scalar, …) or a permuted list now both fail.
    agent_rejected = agent_out["rejected"]
    if not isinstance(agent_rejected, list):
        return GradeResult(False, 0.0,
            f"rejected must be a JSON list (chronological order), "
            f"got {type(agent_rejected).__name__}")

    # Set-equality first — gives a precise "missing/extra" message when the
    # agent has the wrong elements rather than just the wrong order.
    agent_rejected_set = set(agent_rejected)
    expected_rejected_set = set(expected_rejected)
    if agent_rejected_set != expected_rejected_set:
        extra = agent_rejected_set - expected_rejected_set
        missing_r = expected_rejected_set - agent_rejected_set
        return GradeResult(False, 0.0,
            f"rejected mismatch: got {len(agent_rejected)} entries, "
            f"{len(extra)} extra, {len(missing_r)} missing")

    # Same elements, possibly wrong order.
    if list(agent_rejected) != list(expected_rejected):
        return GradeResult(False, 0.0,
            "rejected list is not in chronological order")

    return GradeResult(True, 1.0,
        f"all {len(expected_balances)} balances correct, {len(expected_rejected)} rejected transactions identified in chronological order")
