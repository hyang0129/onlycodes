"""Semi-mechanical extractor for ``amnesiac_retry`` / ``solution_thrashing``.

Detects the pathology where an agent repeatedly re-runs structurally
similar code via the codebox execute_code tool without the stdout/stderr
meaningfully improving — i.e. the agent is stalling on an error instead
of diagnosing or changing approach.

Mechanical signal
-----------------

Two or more "consecutive" ``mcp__codebox__execute_code`` turns where:

1. The ``input.code`` field hashes equal (or is near-identical — we use
   a normalised-whitespace hash for a slightly coarser match than the
   Stage-1 Jaccard check).
2. The tool_result output contains an error/traceback indicator
   (``Error``, ``Traceback``, ``Exception``, ``raise``) on at least one
   of the consecutive turns.

"Consecutive" here means **consecutive within the sequence of codebox
turns** — i.e. non-codebox assistant blocks (e.g., a ``Read`` tool call
between two codebox calls) are invisible to this check. This is
deliberate: an agent that reruns the exact same failing code before and
after an intermediate inspection is still stalling, even if the inspection
broke strict adjacency in the raw transcript. Callers that need strict
adjacency should tighten ``_iter_codebox_turns``.

This primarily targets the artifact benchmark (which exposes the codebox
tool) but is benchmark-agnostic at the filter level. SWE-bench baseline
runs won't have codebox turns and the filter returns an empty list.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from swebench.analyze.extractor import CODEBOX_TOOL_NAME, iter_records
from swebench.analyze.semi_mechanical import register


#: Regex matching common Python error signals in stdout/stderr.
_ERROR_RE = re.compile(
    r"\b(Traceback|Exception|Error|assertionerror|raise\s+\w+)\b",
    re.IGNORECASE,
)

#: Max characters of code body to include per excerpt.
_CODE_TRUNCATE_CHARS = 600

#: Max characters of output body to include per excerpt.
_OUTPUT_TRUNCATE_CHARS = 600

#: Min run of similar-code turns required to flag. 2 = back-to-back repeat.
_MIN_RUN_LENGTH = 2


_SYSTEM_PROMPT = """\
You are reviewing excerpts from a Claude Code transcript. You will see
consecutive codebox `execute_code` turns where the agent ran structurally
similar code more than once in a row, at least one of which produced an
error or traceback.

Your task: determine whether the agent was **stalling** — repeatedly
retrying the same approach without incorporating the error feedback, or
thrashing between near-duplicate solutions — rather than diagnosing and
changing approach.

Relevant pathology IDs: `amnesiac_retry` (agent forgot what it already
tried) or `solution_thrashing` (agent flips between two non-working
variants). If unclear which applies, prefer `amnesiac_retry`.

Respond with a single JSON object and nothing else:

{
  "flagged": true | false,
  "confidence": "high" | "medium" | "low",
  "reasoning": "<one or two sentences explaining your verdict>",
  "key_evidence": ["<excerpt 1>", "<excerpt 2>"]   // up to 4 excerpts, empty list if not flagged
}
"""


def _normalised_hash(code: str) -> str:
    """Return a hash stable under whitespace-only edits."""
    collapsed = re.sub(r"\s+", " ", code).strip()
    return hashlib.sha1(collapsed.encode("utf-8"), usedforsecurity=False).hexdigest()


def _iter_codebox_turns(path: Path):
    """Yield ``(turn_index, tool_use_id, code, output)`` for each codebox call."""
    records = list(iter_records(path))

    result_map: dict[str, str] = {}
    for rec in records:
        if rec.get("type") != "user":
            continue
        for block in (rec.get("message") or {}).get("content", []) or []:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            tid = block.get("tool_use_id") or ""
            raw = block.get("content", "")
            if isinstance(raw, list):
                raw = "\n".join(
                    c.get("text", "") if isinstance(c, dict) else str(c)
                    for c in raw
                )
            result_map[tid] = str(raw) if raw else ""

    turn_index = 0
    for rec in records:
        if rec.get("type") != "assistant":
            continue
        for block in (rec.get("message") or {}).get("content", []) or []:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = block.get("name", "")
            if name != CODEBOX_TOOL_NAME:
                turn_index += 1
                continue
            tid = block.get("id", "")
            inp = block.get("input") or {}
            code = inp.get("code", "") if isinstance(inp, dict) else ""
            output = result_map.get(tid, "")
            yield turn_index, tid, code, output
            turn_index += 1


def _filter(path: Path) -> list[str]:
    """Return excerpts for runs of near-duplicate codebox turns with errors."""
    turns = list(_iter_codebox_turns(path))
    if len(turns) < _MIN_RUN_LENGTH:
        return []

    excerpts: list[str] = []
    run_start = 0
    while run_start < len(turns):
        run_hash = _normalised_hash(turns[run_start][2])
        run_end = run_start + 1
        while run_end < len(turns) and _normalised_hash(turns[run_end][2]) == run_hash:
            run_end += 1
        run_len = run_end - run_start
        if run_len >= _MIN_RUN_LENGTH:
            # Require at least one error signal across the run's outputs.
            any_error = any(
                _ERROR_RE.search(turns[i][3] or "") for i in range(run_start, run_end)
            )
            if any_error:
                # Emit one excerpt covering the whole run (first + last turns).
                first_turn_idx, _, code, first_output = turns[run_start]
                _, _, _, last_output = turns[run_end - 1]
                code_preview = code[:_CODE_TRUNCATE_CHARS]
                first_out = (first_output or "")[:_OUTPUT_TRUNCATE_CHARS]
                last_out = (last_output or "")[:_OUTPUT_TRUNCATE_CHARS]
                last_turn_idx = turns[run_end - 1][0]
                excerpt = (
                    f"Codebox run: {run_len} consecutive near-duplicate turns "
                    f"starting at turn {first_turn_idx}\n"
                    f"code (truncated {_CODE_TRUNCATE_CHARS} chars):\n{code_preview}\n\n"
                    f"output of turn {first_turn_idx}:\n{first_out}\n\n"
                    f"output of turn {last_turn_idx}:\n{last_out}"
                )
                excerpts.append(excerpt)
        run_start = run_end

    return excerpts


register(
    "iteration_stall",
    target_pattern_id="amnesiac_retry",
    filter_fn=_filter,
    system_prompt=_SYSTEM_PROMPT,
)
