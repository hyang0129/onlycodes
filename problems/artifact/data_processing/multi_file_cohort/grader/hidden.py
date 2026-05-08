"""Hidden grader for data_processing__multi_file_cohort."""
from __future__ import annotations
import csv, json
from dataclasses import dataclass
from pathlib import Path
from collections import defaultdict

@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str

OUTPUT_REL = "output/top_products.jsonl"
TOLERANCE = 0.02  # 2% tolerance on revenue values

def _compute_expected(scratch_dir: Path):
    totals = defaultdict(float)
    for f in sorted(scratch_dir.glob("sales_region_*.csv")):
        with open(f) as fh:
            for row in csv.DictReader(fh):
                totals[row["product_id"]] += int(row["quantity"]) * float(row["unit_price"])
    return sorted(totals.items(), key=lambda x: -x[1])[:5]

def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()
    output_path = scratch_dir / OUTPUT_REL
    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")
    try:
        lines = [l.strip() for l in output_path.read_text().splitlines() if l.strip()]
        agent_top5 = [json.loads(l) for l in lines]
    except Exception as exc:
        return GradeResult(False, 0.0, f"could not parse output: {exc}")

    if len(agent_top5) != 5:
        return GradeResult(False, 0.0, f"output must have 5 entries (got {len(agent_top5)})")

    for entry in agent_top5:
        if "product_id" not in entry or "total_revenue" not in entry:
            return GradeResult(False, 0.0, f"entry missing required keys: {entry}")

    expected = _compute_expected(scratch_dir)
    expected_pids = [pid for pid, _ in expected]
    agent_pids = [e["product_id"] for e in agent_top5]

    if set(agent_pids) != set(expected_pids):
        return GradeResult(False, 0.0, f"wrong top-5 products: got {agent_pids}")

    # Check revenues within tolerance
    expected_dict = dict(expected)
    for entry in agent_top5:
        pid = entry["product_id"]
        expected_rev = expected_dict[pid]
        agent_rev = float(entry["total_revenue"])
        if abs(agent_rev - expected_rev) / expected_rev > TOLERANCE:
            return GradeResult(False, 0.0, f"revenue for {pid}: got {agent_rev:.2f}, out of tolerance")

    # Issue #166: prompt requires rows in descending order by total_revenue.
    # Verify agent's row order matches this requirement. We check monotonic
    # non-increasing because two products could in principle tie on revenue
    # (though that's vanishingly rare with float arithmetic on this data).
    agent_revs = [float(e["total_revenue"]) for e in agent_top5]
    if agent_revs != sorted(agent_revs, reverse=True):
        return GradeResult(False, 0.0,
            "rows not in descending order by total_revenue")

    return GradeResult(True, 1.0, f"correct top-5 products identified with revenues within {TOLERANCE*100:.0f}% tolerance, in descending order")
