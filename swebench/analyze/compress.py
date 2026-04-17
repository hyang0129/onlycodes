"""Stage 2a log compressor.

This module takes a raw SWE-bench run JSONL transcript and produces a
compact, human-readable plaintext summary intended to be embedded in a
markdown prompt for the Stage 2b analysis subagent.

What it does
------------
- Strips ``rate_limit_event`` records entirely.
- Flattens nested ``tool_result`` payloads: the onlycode MCP tool returns
  a JSON string with ``{stdout, stderr, exit_code}`` wrapped in a
  ``{"type": "text", "text": "..."}`` content block. This module performs
  a two-level parse to expose those fields as readable text.
- Preserves ``thinking`` blocks verbatim, including the cryptographic
  ``signature`` (some downstream tooling may need to echo them back).
- Applies error-aware truncation to long tool outputs: keeps the head and
  tail of anything over ``TRUNCATE_THRESHOLD_LINES``, and always retains
  lines containing ``Traceback`` or ``Error:`` verbatim.
- Imports ``count_turns`` and ``TURN_DEFINITION`` from
  :mod:`swebench.analyze.extractor` per ADR Q1 — the turn definition has
  a single source of truth.

Primary entry point:
    compress(jsonl_path: Path) -> str
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from swebench.analyze.extractor import (  # ADR Q1 — single source of truth
    TURN_DEFINITION,
    count_turns,
    iter_records,
)

# ---------------------------------------------------------------------------
# Truncation tuning
# ---------------------------------------------------------------------------

#: Maximum number of lines in a tool_result output before truncation kicks in.
TRUNCATE_THRESHOLD_LINES = 60

#: Number of head lines kept when truncating a long output.
TRUNCATE_HEAD_LINES = 20

#: Number of tail lines kept when truncating a long output (error-aware).
TRUNCATE_TAIL_LINES = 20

#: Substrings that mark a line as "always keep" for error-aware truncation.
ERROR_MARKERS = ("Traceback", "Error:")


def _truncate_output(text: str) -> str:
    """Return ``text`` possibly truncated with head/tail ellipsis marker.

    Short outputs (<= ``TRUNCATE_THRESHOLD_LINES`` lines) are returned
    unchanged. For long outputs, keep the first ``TRUNCATE_HEAD_LINES``
    and last ``TRUNCATE_TAIL_LINES``. Any intermediate line matching an
    entry in :data:`ERROR_MARKERS` is also preserved (error-aware
    truncation) so that the most informative signal — a traceback buried
    in the middle of a long log — survives.
    """
    if not text:
        return text
    lines = text.splitlines()
    if len(lines) <= TRUNCATE_THRESHOLD_LINES:
        return text

    head = lines[:TRUNCATE_HEAD_LINES]
    tail = lines[-TRUNCATE_TAIL_LINES:]

    # Error-aware retention: keep any middle line that looks like an error.
    middle_start = TRUNCATE_HEAD_LINES
    middle_end = len(lines) - TRUNCATE_TAIL_LINES
    kept_errors: list[tuple[int, str]] = []
    for idx in range(middle_start, middle_end):
        line = lines[idx]
        if any(marker in line for marker in ERROR_MARKERS):
            kept_errors.append((idx, line))

    omitted = (middle_end - middle_start) - len(kept_errors)
    parts: list[str] = []
    parts.extend(head)
    if kept_errors:
        parts.append(f"... [{omitted} lines omitted, error lines preserved] ...")
        parts.extend(line for _, line in kept_errors)
        parts.append("... [truncated middle continues] ...")
    else:
        parts.append(
            f"... [{middle_end - middle_start} lines omitted] ..."
        )
    parts.extend(tail)
    return "\n".join(parts)


def _flatten_tool_result_content(content: Any) -> str:
    """Flatten the ``content`` field of a ``user.tool_result`` block.

    The canonical shape for onlycode runs is::

        [{"type": "text", "text": "<json-string with stdout/stderr/exit_code>"}]

    but the upstream SDK is permissive, so this function also handles:
    a bare string, a list of strings, and text blocks whose ``text`` is
    not parseable JSON. Returns a plain string suitable for embedding in
    the compressed transcript.
    """
    # Flatten to a single textual representation first.
    raw: str
    if isinstance(content, str):
        raw = content
    elif isinstance(content, list):
        pieces: list[str] = []
        for sub in content:
            if isinstance(sub, str):
                pieces.append(sub)
            elif isinstance(sub, dict):
                if sub.get("type") == "text":
                    pieces.append(str(sub.get("text", "")))
                else:
                    # Unknown block shape — dump verbatim as JSON.
                    try:
                        pieces.append(json.dumps(sub, ensure_ascii=False))
                    except (TypeError, ValueError):
                        pieces.append(str(sub))
            else:
                pieces.append(str(sub))
        raw = "\n".join(pieces)
    elif content is None:
        return ""
    else:
        raw = str(content)

    # Two-level parse: if the flattened text is itself a JSON object with
    # codebox-shaped keys, unwrap it to a readable format.
    stripped = raw.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            parsed = json.loads(stripped)
        except (json.JSONDecodeError, ValueError):
            parsed = None
        if isinstance(parsed, dict) and (
            "stdout" in parsed or "stderr" in parsed or "exit_code" in parsed
        ):
            stdout = str(parsed.get("stdout", "") or "")
            stderr = str(parsed.get("stderr", "") or "")
            exit_code = parsed.get("exit_code")
            blocks: list[str] = []
            if exit_code is not None:
                blocks.append(f"exit_code: {exit_code}")
            if stdout:
                blocks.append("stdout:\n" + _truncate_output(stdout))
            else:
                blocks.append("stdout: <empty>")
            if stderr:
                blocks.append("stderr:\n" + _truncate_output(stderr))
            else:
                blocks.append("stderr: <empty>")
            return "\n".join(blocks)

    # Not codebox JSON — truncate the raw text and return.
    return _truncate_output(raw)


def _format_thinking(block: dict) -> str:
    """Format a ``thinking`` block verbatim, preserving ``signature``."""
    thinking_text = str(block.get("thinking", ""))
    sig = block.get("signature")
    lines = ["=== thinking ==="]
    if sig is not None:
        lines.append(f"signature: {sig}")
    lines.append(thinking_text)
    lines.append("=== /thinking ===")
    return "\n".join(lines)


def _format_text_block(block: dict) -> str:
    text = str(block.get("text", ""))
    return f"[assistant text]\n{text}"


def _format_tool_use(block: dict) -> str:
    name = block.get("name", "<unknown>")
    tool_id = block.get("id", "")
    inp = block.get("input") or {}
    lines = [f"[tool_use name={name} id={tool_id}]"]
    if isinstance(inp, dict):
        # Pretty special-case codebox — emit ``code`` as a fenced block.
        if "code" in inp:
            language = inp.get("language", "")
            lines.append(f"language: {language}")
            lines.append("code:")
            lines.append(str(inp.get("code", "")))
            # Emit any other input keys verbatim.
            extras = {k: v for k, v in inp.items() if k not in ("code", "language")}
            if extras:
                try:
                    lines.append("other_input: " + json.dumps(extras, ensure_ascii=False))
                except (TypeError, ValueError):
                    lines.append(f"other_input: {extras!r}")
        else:
            try:
                lines.append("input: " + json.dumps(inp, ensure_ascii=False))
            except (TypeError, ValueError):
                lines.append(f"input: {inp!r}")
    else:
        lines.append(f"input: {inp!r}")
    return "\n".join(lines)


def _format_tool_result(block: dict) -> str:
    tid = block.get("tool_use_id", "")
    body = _flatten_tool_result_content(block.get("content"))
    return f"[tool_result for={tid}]\n{body}"


def _format_assistant_record(rec: dict) -> list[str]:
    out: list[str] = []
    content = rec.get("message", {}).get("content", []) or []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "thinking":
            out.append(_format_thinking(block))
        elif btype == "text":
            out.append(_format_text_block(block))
        elif btype == "tool_use":
            out.append(_format_tool_use(block))
        else:
            # Unknown assistant block type — dump as JSON.
            try:
                out.append(f"[assistant {btype}] " + json.dumps(block, ensure_ascii=False))
            except (TypeError, ValueError):
                out.append(f"[assistant {btype}] {block!r}")
    return out


def _format_user_record(rec: dict) -> list[str]:
    out: list[str] = []
    msg = rec.get("message") or {}
    content = msg.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                out.append(_format_tool_result(block))
            elif isinstance(block, dict):
                # Unknown user block; format best-effort.
                try:
                    out.append("[user block] " + json.dumps(block, ensure_ascii=False))
                except (TypeError, ValueError):
                    out.append(f"[user block] {block!r}")
            else:
                out.append(f"[user text]\n{block}")
    elif isinstance(content, str) and content:
        out.append(f"[user text]\n{content}")
    # Bare user records (no message.content) are skipped — they carry no
    # information beyond the uuid.
    return out


def _format_system_record(rec: dict) -> str:
    subtype = rec.get("subtype", "")
    cwd = rec.get("cwd", "")
    session = rec.get("session_id", "")
    return f"[system subtype={subtype} cwd={cwd} session_id={session}]"


def _format_result_record(rec: dict) -> str:
    subtype = rec.get("subtype", "")
    is_error = rec.get("is_error")
    num_turns = rec.get("num_turns")
    cost = rec.get("total_cost_usd")
    duration = rec.get("duration_ms")
    return (
        f"[result subtype={subtype} is_error={is_error} "
        f"num_turns={num_turns} total_cost_usd={cost} duration_ms={duration}]"
    )


def compress(jsonl_path: str | Path) -> str:
    """Return a compact plaintext rendering of a single run's JSONL transcript.

    The output is a human-readable, line-oriented string (NOT JSON). It
    is designed to be embedded directly into a markdown prompt for the
    Stage 2b analysis subagent.

    Behavior:

    - Reads ``jsonl_path`` with :func:`swebench.analyze.extractor.iter_records`
      (the only I/O side effect).
    - Drops all ``rate_limit_event`` records.
    - Emits a short header with the turn count (per ADR Q1).
    - For each remaining record, emits a formatted section: system init,
      assistant blocks (thinking preserved verbatim with signature, text,
      tool_use with code body), user tool_result blocks (two-level-parsed
      and truncated), and the final result marker.

    The function is otherwise pure: no network, no writes.
    """
    records = list(iter_records(jsonl_path))
    turns = count_turns(records)

    sections: list[str] = []
    sections.append(
        f"# Compressed run transcript\n"
        f"source: {Path(jsonl_path).name}\n"
        f"turns ({TURN_DEFINITION}): {turns}\n"
    )

    for rec in records:
        rtype = rec.get("type")
        if rtype == "rate_limit_event":
            continue
        if rtype == "system":
            sections.append(_format_system_record(rec))
        elif rtype == "assistant":
            sections.extend(_format_assistant_record(rec))
        elif rtype == "user":
            sections.extend(_format_user_record(rec))
        elif rtype == "result":
            sections.append(_format_result_record(rec))
        else:
            # Unknown record type — include it verbatim so downstream
            # inspection notices it rather than silently dropping signal.
            try:
                sections.append(f"[{rtype}] " + json.dumps(rec, ensure_ascii=False))
            except (TypeError, ValueError):
                sections.append(f"[{rtype}] {rec!r}")

    return "\n\n".join(sections) + "\n"


__all__ = [
    "TRUNCATE_THRESHOLD_LINES",
    "TRUNCATE_HEAD_LINES",
    "TRUNCATE_TAIL_LINES",
    "ERROR_MARKERS",
    "compress",
]
