"""Hidden grader for ``data_engineering__repair_transactions_export_hard``.

Recomputes the expected repaired transactions output from
``transactions_raw.csv`` and compares the agent's output row-for-row.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

EXPECTED_COLUMNS = [
    "tx_id", "account_id", "amount", "tx_type", "status",
    "is_disputed", "is_refunded", "channel", "notes",
]
OUTPUT_REL = "output/transactions_clean.csv"
INPUT_REL = "transactions_raw.csv"

_TYPE_LOOKUP = {
    s: canon
    for canon, variants in {
        "deposit": ["deposit", "dep", "depo", "d"],
        "withdrawal": ["withdrawal", "wd", "with", "w"],
        "transfer": ["transfer", "xfer", "trf", "x"],
        "fee": ["fee", "f"],
    }.items()
    for s in variants
}
_STATUS_LOOKUP = {
    s: canon
    for canon, variants in {
        "completed": ["completed", "complete", "done", "ok"],
        "pending": ["pending", "pend", "in progress", "wait"],
        "failed": ["failed", "fail", "err", "error"],
    }.items()
    for s in variants
}
_CHANNEL_LOOKUP = {
    s: canon
    for canon, variants in {
        "web": ["web", "www"],
        "mobile": ["mobile", "mob", "app", "ios", "android"],
        "branch": ["branch", "br", "in_person", "in-person"],
        "api": ["api"],
    }.items()
    for s in variants
}
_BOOL_TRUE = {"yes", "y", "true", "1"}
_BOOL_FALSE = {"no", "n", "false", "0", ""}
_NOTE_NULL_TOKENS = {"", "n/a", "na", "none", "null", "-", "—", "?"}


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


def _parse_amount(raw: str) -> float | None:
    """Return parsed float, or ``None`` if the row must be dropped."""
    s = raw.strip()
    if s == "":
        return None
    if s.lower() == "free":
        return 0.0

    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1]

    s = s.strip()
    if s.startswith("$"):
        s = s[1:]
    # Strip "USD" or " USD" suffix (case-insensitive).
    if s.lower().endswith("usd"):
        s = s[:-3]
    s = s.replace(",", "").strip()

    try:
        v = float(s)
    except ValueError:
        return None

    return -v if negative else v


def _normalise_bool(raw: str) -> str | None:
    s = raw.strip().lower()
    if s in _BOOL_TRUE:
        return "true"
    if s in _BOOL_FALSE:
        return "false"
    return None


def _normalise_notes(raw: str) -> str:
    s = raw.strip()
    if s.lower() in _NOTE_NULL_TOKENS:
        return ""
    return s


def _compute_expected(scratch_dir: Path) -> list[list[str]]:
    out_rows: list[list[str]] = []
    with open(scratch_dir / INPUT_REL, newline="") as fh:
        for row in csv.DictReader(fh):
            amount = _parse_amount(row["amount"])
            if amount is None:
                continue

            tx_type = _TYPE_LOOKUP.get(row["tx_type"].strip().lower())
            if tx_type is None:
                continue

            status = _STATUS_LOOKUP.get(row["status"].strip().lower())
            if status is None:
                continue

            is_disp = _normalise_bool(row["is_disputed"])
            if is_disp is None:
                continue

            is_ref = _normalise_bool(row["is_refunded"])
            if is_ref is None:
                continue

            channel = _CHANNEL_LOOKUP.get(row["channel"].strip().lower())
            if channel is None:
                continue

            notes = _normalise_notes(row["notes"])

            out_rows.append([
                row["tx_id"],
                row["account_id"],
                f"{amount:.2f}",
                tx_type,
                status,
                is_disp,
                is_ref,
                channel,
                notes,
            ])
    out_rows.sort(key=lambda r: r[0])
    return out_rows


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()
    output_path = scratch_dir / OUTPUT_REL

    if not output_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced")

    try:
        with open(output_path, newline="") as fh:
            reader = csv.reader(fh)
            try:
                header = next(reader)
            except StopIteration:
                return GradeResult(False, 0.0, "output artifact is empty")
            agent_rows = list(reader)
    except Exception as exc:
        return GradeResult(False, 0.0, f"could not parse output: {exc}")

    if header != EXPECTED_COLUMNS:
        return GradeResult(
            False,
            0.0,
            f"column header must be exactly {EXPECTED_COLUMNS} in that order; got {header}",
        )

    expected = _compute_expected(scratch_dir)

    if len(agent_rows) != len(expected):
        return GradeResult(
            False,
            0.0,
            f"row count mismatch: expected {len(expected)} rows, got {len(agent_rows)}",
        )

    for i, (row, exp) in enumerate(zip(agent_rows, expected), start=1):
        if len(row) != 9:
            return GradeResult(
                False, 0.0, f"row {i}: expected 9 fields, got {len(row)}"
            )

        # Compare every field except amount as exact strings.
        for j, name in enumerate(EXPECTED_COLUMNS):
            if name == "amount":
                continue
            if row[j] != exp[j]:
                return GradeResult(
                    False,
                    0.0,
                    f"row {i} ({row[0]}): field {name} agent={row[j]!r} expected={exp[j]!r}",
                )

        # Amount: parse + tolerance, plus 2-decimal format check.
        agent_amt_str = row[2]
        exp_amt_str = exp[2]
        if "." not in agent_amt_str or len(agent_amt_str.split(".")[-1]) != 2:
            return GradeResult(
                False,
                0.0,
                f"row {i}: amount {agent_amt_str!r} must have exactly 2 decimal places",
            )
        try:
            agent_amt = float(agent_amt_str)
        except ValueError:
            return GradeResult(
                False, 0.0, f"row {i}: amount {agent_amt_str!r} is not numeric"
            )
        exp_amt = float(exp_amt_str)
        if abs(agent_amt - exp_amt) > 0.005:
            return GradeResult(
                False,
                0.0,
                f"row {i} ({row[0]}): amount disagrees agent={agent_amt_str} expected={exp_amt_str}",
            )

    return GradeResult(
        True,
        1.0,
        f"all {len(expected)} repaired transaction rows match",
    )
