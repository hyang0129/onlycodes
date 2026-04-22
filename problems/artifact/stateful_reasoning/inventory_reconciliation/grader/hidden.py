"""Hidden grader for stateful_reasoning__inventory_reconciliation.

Contract: ``grade(scratch_dir: Path) -> GradeResult``. See docs/SCHEMA_ARTIFACT.md §3.

Replay the transactions independently and compare stock, rejected list,
and totals to the agent's reconciliation.json. Deterministic, stdlib-only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


OUTPUT_REL = "output/reconciliation.json"
TXN_REL = "transactions.jsonl"


def _replay(txn_path: Path) -> dict[str, Any]:
    stock: dict[str, dict[str, int]] = {}
    rejected: list[dict] = []
    accepted = 0
    total = 0

    def _ensure(wh: str, sku: str) -> None:
        stock.setdefault(wh, {}).setdefault(sku, 0)

    with open(txn_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            total += 1
            e = json.loads(line)
            t = e["type"]
            tid = e["id"]

            if t == "receive":
                wh = e["warehouse"]
                sku = e["sku"]
                _ensure(wh, sku)
                stock[wh][sku] += int(e["qty"])
                accepted += 1
            elif t == "ship":
                wh = e["warehouse"]
                sku = e["sku"]
                _ensure(wh, sku)
                if stock[wh][sku] - int(e["qty"]) < 0:
                    rejected.append({"id": tid, "reason": "insufficient_stock"})
                else:
                    stock[wh][sku] -= int(e["qty"])
                    accepted += 1
            elif t == "transfer":
                src = e["from"]
                dst = e["to"]
                sku = e["sku"]
                _ensure(src, sku)
                _ensure(dst, sku)
                if stock[src][sku] - int(e["qty"]) < 0:
                    rejected.append({"id": tid, "reason": "insufficient_stock"})
                else:
                    stock[src][sku] -= int(e["qty"])
                    stock[dst][sku] += int(e["qty"])
                    accepted += 1
            elif t == "adjust":
                wh = e["warehouse"]
                sku = e["sku"]
                _ensure(wh, sku)
                if stock[wh][sku] + int(e["delta"]) < 0:
                    rejected.append({"id": tid, "reason": "insufficient_stock"})
                else:
                    stock[wh][sku] += int(e["delta"])
                    accepted += 1
            else:
                raise ValueError(f"unknown type: {t}")

    return {
        "stock": stock,
        "rejected": rejected,
        "totals": {"accepted": accepted, "rejected": len(rejected)},
        "_total_events": total,
    }


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()
    output_path = scratch_dir / OUTPUT_REL
    txn_path = scratch_dir / TXN_REL

    if not txn_path.is_file():
        return GradeResult(False, 0.0, "transactions.jsonl not found")
    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    try:
        agent = json.loads(output_path.read_text())
    except json.JSONDecodeError as exc:
        return GradeResult(False, 0.0, f"output is not valid JSON: {exc}")

    if not isinstance(agent, dict):
        return GradeResult(False, 0.0, "output must be a JSON object")

    for k in ("stock", "rejected", "totals"):
        if k not in agent:
            return GradeResult(False, 0.0, f"output missing required key: {k}")

    try:
        ref = _replay(txn_path)
    except Exception as exc:
        return GradeResult(False, 0.0, f"grader replay failed: {exc}")

    issues: list[str] = []

    # Totals
    if not isinstance(agent["totals"], dict):
        return GradeResult(False, 0.0, "'totals' must be an object")
    for k in ("accepted", "rejected"):
        v = agent["totals"].get(k)
        if not isinstance(v, int) or isinstance(v, bool):
            return GradeResult(False, 0.0, f"totals.{k} must be int")
    if agent["totals"]["accepted"] != ref["totals"]["accepted"]:
        issues.append(f"totals.accepted {agent['totals']['accepted']} vs ref {ref['totals']['accepted']}")
    if agent["totals"]["rejected"] != ref["totals"]["rejected"]:
        issues.append(f"totals.rejected {agent['totals']['rejected']} vs ref {ref['totals']['rejected']}")
    if agent["totals"]["accepted"] + agent["totals"]["rejected"] != ref["_total_events"]:
        issues.append(f"totals do not sum to total events ({ref['_total_events']})")

    # Rejected list (ordered)
    ra = agent["rejected"]
    rr = ref["rejected"]
    if not isinstance(ra, list):
        return GradeResult(False, 0.0, "'rejected' must be a list")
    if len(ra) != len(rr):
        issues.append(f"rejected length {len(ra)} vs ref {len(rr)}")
    else:
        mismatches = 0
        for i, (a, b) in enumerate(zip(ra, rr)):
            if not isinstance(a, dict) or a.get("id") != b["id"] or a.get("reason") != b["reason"]:
                mismatches += 1
        if mismatches:
            issues.append(f"{mismatches} rejected-list entries differ from ref (order-sensitive)")

    # Stock
    sa = agent["stock"]
    sr = ref["stock"]
    if not isinstance(sa, dict):
        return GradeResult(False, 0.0, "'stock' must be an object")

    wh_missing = set(sr) - set(sa)
    wh_extra = set(sa) - set(sr)
    wrong_cells = 0
    total_cells = 0
    for wh, sku_map in sr.items():
        total_cells += len(sku_map)
        agent_sku_map = sa.get(wh, {})
        if not isinstance(agent_sku_map, dict):
            wrong_cells += len(sku_map)
            continue
        for sku, ref_qty in sku_map.items():
            av = agent_sku_map.get(sku)
            if av != ref_qty:
                wrong_cells += 1
    if wh_missing:
        issues.append(f"stock missing {len(wh_missing)} warehouse(s): {sorted(wh_missing)}")
    if wh_extra:
        issues.append(f"stock has {len(wh_extra)} extra warehouse(s): {sorted(wh_extra)}")
    if wrong_cells:
        issues.append(f"{wrong_cells}/{total_cells} stock cells wrong")

    if issues:
        # Partial score: fraction of (stock cells correct + rejected entries correct +
        # totals correct) over the same total.
        denom = total_cells + len(rr) + 2
        correct = (total_cells - wrong_cells)
        # Rejected order-sensitive correctness
        if len(ra) == len(rr):
            correct += sum(1 for a, b in zip(ra, rr)
                           if isinstance(a, dict) and a.get("id") == b["id"] and a.get("reason") == b["reason"])
        correct += (agent["totals"].get("accepted") == ref["totals"]["accepted"])
        correct += (agent["totals"].get("rejected") == ref["totals"]["rejected"])
        score = round(correct / max(denom, 1), 4)
        return GradeResult(False, score, "; ".join(issues))

    return GradeResult(True, 1.0,
                       f"reconciliation matches: {total_cells} stock cells, {len(rr)} rejected, totals aligned")
