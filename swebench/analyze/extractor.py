"""Stage 1 mechanical extractor for SWE-bench run JSONL logs.

This module performs the cheap, deterministic, side-effect-free pass over a
single run's JSONL transcript: counting turns, extracting total cost,
hashing codebox-execute code blocks per turn, and computing Jaccard
similarity across turns.

Turn contract (ADR Q1) — PINNED
-------------------------------
A "turn" is defined as one unique ``tool_use.id`` value observed across all
records whose ``type == "assistant"``. That is: the number of distinct tool
invocations the model issued during the run. Text-only and thinking-only
assistant blocks do not contribute turns. Records whose ``type`` is anything
other than ``"assistant"`` (``system``, ``user``, ``rate_limit_event``,
``result``) are skipped when counting.

This definition is deliberately independent of the ``num_turns`` field that
appears on the run's final ``result`` record, which counts
request/response pairs rather than tool invocations. Stage 1 uses the
``tool_use.id`` definition so that onlycode and baseline arms are compared
on the same mechanical axis: how many tool calls the agent made.

The module is stdlib-only; it does not import Click, pytest, or any
third-party package. It is safe to import from a CLI without pulling in
heavy dependencies.

Primary entry point:
    extract(path) -> dict
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable, Iterator

# ---------------------------------------------------------------------------
# Pinned constants (ADR)
# ---------------------------------------------------------------------------

#: Human-readable description of the turn definition, per ADR Q1.
TURN_DEFINITION = "unique tool_use.id across all assistant records"

#: Fraction of runs that fall into the "top" triage bucket. Used by
#: :func:`triage_rank` to compute the percentile cutoff on turn count.
TRIAGE_TOP_PERCENTILE = 0.20

#: Name of the onlycode-arm MCP tool whose ``input.code`` field is hashed.
CODEBOX_TOOL_NAME = "mcp__codebox__execute_code"

#: Mechanical flag raised when a task is present for one arm but not the
#: other, or when the JSONL contains no assistant records at all.
FLAG_ARM_CRASH_NO_OUTPUT = "ARM_CRASH_NO_OUTPUT"


# ---------------------------------------------------------------------------
# JSONL iteration
# ---------------------------------------------------------------------------


def iter_records(path: str | Path) -> Iterator[dict]:
    """Yield decoded JSON records from a JSONL file.

    Skips blank lines and lines that fail to parse (the latter are silently
    dropped; log files that partially stream are common).
    """
    p = Path(path)
    with p.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


# ---------------------------------------------------------------------------
# Turn counting (ADR Q1)
# ---------------------------------------------------------------------------


def count_turns(records: Iterable[dict]) -> int:
    """Count unique ``tool_use.id`` values across all assistant records.

    See module docstring for the definition. Returns 0 for transcripts with
    no tool invocations.
    """
    ids: set[str] = set()
    for rec in records:
        if rec.get("type") != "assistant":
            continue
        for block in rec.get("message", {}).get("content", []) or []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                tid = block.get("id")
                if tid is not None:
                    ids.add(tid)
    return len(ids)


# ---------------------------------------------------------------------------
# Cost
# ---------------------------------------------------------------------------


def extract_total_cost(records: Iterable[dict]) -> float | None:
    """Return the ``total_cost_usd`` from the last ``result`` record, if any."""
    cost: float | None = None
    for rec in records:
        if rec.get("type") == "result" and "total_cost_usd" in rec:
            try:
                cost = float(rec["total_cost_usd"])
            except (TypeError, ValueError):
                continue
    return cost


# ---------------------------------------------------------------------------
# Codebox code hashing
# ---------------------------------------------------------------------------


def md5_hex(text: str) -> str:
    """Return the hex MD5 digest of ``text`` (UTF-8 encoded)."""
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def codebox_code_hashes(records: Iterable[dict]) -> list[str]:
    """Return the MD5 of every codebox ``execute_code`` invocation, in order.

    For each assistant ``tool_use`` block with ``name == CODEBOX_TOOL_NAME``,
    hash the ``input.code`` string. Empty/missing code is hashed as the empty
    string (useful signal — the model still spent a turn). Tool calls from
    other tools (Edit, Read, Bash, etc.) are ignored.
    """
    hashes: list[str] = []
    for rec in records:
        if rec.get("type") != "assistant":
            continue
        for block in rec.get("message", {}).get("content", []) or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "tool_use":
                continue
            if block.get("name") != CODEBOX_TOOL_NAME:
                continue
            inp = block.get("input", {}) or {}
            code = ""
            if isinstance(inp, dict):
                code = inp.get("code", "") or ""
            hashes.append(md5_hex(code))
    return hashes


# ---------------------------------------------------------------------------
# Jaccard similarity
# ---------------------------------------------------------------------------


def _shingles(text: str, k: int = 5) -> set[str]:
    """Return the set of word-level k-shingles of ``text``.

    Used by :func:`jaccard_similarity` as a tokenizer-lite representation of
    code bodies for cross-turn similarity. For very short texts (< k words),
    the full word tuple is used as a single shingle.
    """
    words = text.split()
    if len(words) <= k:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i : i + k]) for i in range(len(words) - k + 1)}


def jaccard_similarity(a: str, b: str) -> float:
    """Return the Jaccard similarity of two code bodies in [0.0, 1.0].

    Uses word-level 5-shingles. Identical inputs yield 1.0; two empty
    inputs yield 0.0 (no signal).
    """
    sa = _shingles(a)
    sb = _shingles(b)
    if not sa and not sb:
        return 0.0
    inter = sa & sb
    union = sa | sb
    if not union:
        return 0.0
    return len(inter) / len(union)


def codebox_pairwise_jaccard(records: Iterable[dict]) -> list[float]:
    """Return Jaccard similarity between consecutive codebox turns.

    Result length is ``max(0, N - 1)`` where ``N`` is the number of codebox
    invocations. Each element ``i`` is ``jaccard(code[i], code[i+1])``.
    High values indicate the model is re-running near-identical code
    (possibly stuck).
    """
    bodies: list[str] = []
    for rec in records:
        if rec.get("type") != "assistant":
            continue
        for block in rec.get("message", {}).get("content", []) or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "tool_use":
                continue
            if block.get("name") != CODEBOX_TOOL_NAME:
                continue
            inp = block.get("input", {}) or {}
            bodies.append(inp.get("code", "") if isinstance(inp, dict) else "")
    if len(bodies) < 2:
        return []
    return [jaccard_similarity(bodies[i], bodies[i + 1]) for i in range(len(bodies) - 1)]


# ---------------------------------------------------------------------------
# Extract (primary entry point)
# ---------------------------------------------------------------------------


def extract(path: str | Path) -> dict:
    """Run the full mechanical extraction pass on a single JSONL file.

    Returns a dict with keys:

    - ``path``: absolute path (str) of the input file
    - ``turns``: int — unique ``tool_use.id`` count (ADR Q1)
    - ``total_cost_usd``: float | None
    - ``codebox_turns``: int — number of ``mcp__codebox__execute_code`` calls
    - ``codebox_code_md5``: list[str] — per-turn MD5 of ``input.code``
    - ``codebox_pairwise_jaccard``: list[float]
    - ``mechanical_flags``: list[str] — e.g. ``["ARM_CRASH_NO_OUTPUT"]`` if
      the transcript has no assistant records

    This function never raises on malformed records; it returns a filled-in
    dict with whatever could be salvaged.
    """
    p = Path(path)
    # Materialize once — we do multiple passes, and files are small.
    records = list(iter_records(p))

    assistant_count = sum(1 for r in records if r.get("type") == "assistant")

    turns = count_turns(records)
    total_cost = extract_total_cost(records)
    code_hashes = codebox_code_hashes(records)
    jaccard = codebox_pairwise_jaccard(records)

    flags: list[str] = []
    if assistant_count == 0:
        flags.append(FLAG_ARM_CRASH_NO_OUTPUT)

    return {
        "path": str(p.resolve()),
        "turns": turns,
        "total_cost_usd": total_cost,
        "codebox_turns": len(code_hashes),
        "codebox_code_md5": code_hashes,
        "codebox_pairwise_jaccard": jaccard,
        "mechanical_flags": flags,
    }


# ---------------------------------------------------------------------------
# Triage ranking
# ---------------------------------------------------------------------------


def _mark_orphans(metrics: list[dict]) -> None:
    """Add ``ARM_CRASH_NO_OUTPUT`` to metrics whose ``(task_id, run)`` pair
    appears for only one arm.

    Expects each metric dict to optionally carry ``task_id``, ``arm``, and
    ``run`` keys. Metrics lacking those keys are left untouched.
    """
    pairs: dict[tuple, set[str]] = {}
    for m in metrics:
        task = m.get("task_id")
        run = m.get("run")
        arm = m.get("arm")
        if task is None or arm is None:
            continue
        pairs.setdefault((task, run), set()).add(arm)
    for m in metrics:
        task = m.get("task_id")
        run = m.get("run")
        arm = m.get("arm")
        if task is None or arm is None:
            continue
        arms = pairs.get((task, run), set())
        if len(arms) < 2:
            flags = m.setdefault("mechanical_flags", [])
            if FLAG_ARM_CRASH_NO_OUTPUT not in flags:
                flags.append(FLAG_ARM_CRASH_NO_OUTPUT)


def triage_rank(metrics: list[dict]) -> list[dict]:
    """Order a list of per-run metric dicts by triage priority.

    Priority, highest first:

    1. Runs flagged with ``ARM_CRASH_NO_OUTPUT`` (orphans or no-assistant runs).
    2. Runs in the top ``TRIAGE_TOP_PERCENTILE`` of turn count.
    3. Remaining runs, sorted by turn count descending, then cost descending.

    This function does not raise on missing keys: it treats missing
    ``turns`` as 0 and missing ``total_cost_usd`` as 0.0. It mutates each
    dict's ``mechanical_flags`` list in place to mark orphans, but returns a
    new list — the input ordering is preserved for non-ranked callers.
    """
    if not metrics:
        return []

    _mark_orphans(metrics)

    def turns_of(m: dict) -> int:
        try:
            return int(m.get("turns") or 0)
        except (TypeError, ValueError):
            return 0

    def cost_of(m: dict) -> float:
        try:
            return float(m.get("total_cost_usd") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    # Compute the turn-count cutoff for the top percentile.
    turn_counts = sorted((turns_of(m) for m in metrics), reverse=True)
    cutoff_idx = max(0, int(len(turn_counts) * TRIAGE_TOP_PERCENTILE) - 1)
    top_cutoff = turn_counts[cutoff_idx] if turn_counts else 0

    def priority(m: dict) -> tuple:
        flags = m.get("mechanical_flags") or []
        is_flagged = FLAG_ARM_CRASH_NO_OUTPUT in flags
        t = turns_of(m)
        is_top = t >= top_cutoff and top_cutoff > 0
        # Lower tuple sorts first; negate for descending.
        return (
            0 if is_flagged else 1,
            0 if is_top else 1,
            -t,
            -cost_of(m),
        )

    return sorted(metrics, key=priority)


__all__ = [
    "TURN_DEFINITION",
    "TRIAGE_TOP_PERCENTILE",
    "CODEBOX_TOOL_NAME",
    "FLAG_ARM_CRASH_NO_OUTPUT",
    "iter_records",
    "count_turns",
    "extract_total_cost",
    "md5_hex",
    "codebox_code_hashes",
    "jaccard_similarity",
    "codebox_pairwise_jaccard",
    "extract",
    "triage_rank",
]
