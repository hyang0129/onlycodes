"""Hidden grader for stateful_reasoning__event_ledger."""

# GRADER-SENTINEL: 836b3259-1763-4529-bdc3-e1dfcd8ac5ec
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
            wrong_balances.append(f"{acc}: got {agent_bal:.2f} expected {exp_bal:.2f}")
    if wrong_balances:
        return GradeResult(False, 0.0, f"wrong balances: {wrong_balances[:3]}")

    # Check rejected list (must be exact, order-insensitive for set comparison)
    agent_rejected = set(agent_out["rejected"])
    expected_rejected_set = set(expected_rejected)
    if agent_rejected != expected_rejected_set:
        extra = agent_rejected - expected_rejected_set
        missing_r = expected_rejected_set - agent_rejected
        return GradeResult(False, 0.0,
            f"rejected mismatch: {len(expected_rejected)} expected, {len(agent_out['rejected'])} got. "
            f"Extra: {sorted(extra)[:3]}, Missing: {sorted(missing_r)[:3]}")

    return GradeResult(True, 1.0,
        f"all {len(expected_balances)} balances correct, {len(expected_rejected)} rejected transactions identified")
