"""Per-run leak auditor for artifact-graded benchmark tasks.

Issue #108. The ABSOLUTE no-leak invariant (SCHEMA §Invariants) forbids the
agent from seeing ``grader/hidden.py`` or ``grader/reference_output.*`` for
the task it is being graded on. The materialiser (``artifact_materialize``)
makes sure those files never land in the agent's scratch dir, but the agent's
Python kernel can still walk the filesystem and read them if the scratch dir
lives inside the repo tree (see #108 root-cause analysis).

Defense in depth: this module scans the agent's transcript (``agent.jsonl``)
after every run for two fingerprints derived from the task's own grader files:

1. **Sentinel UUID** — a ``# GRADER-SENTINEL: <uuid>`` comment committed into
   each task's ``hidden.py``. If the agent ``open()``s the grader and dumps
   its contents anywhere the harness captures (stdout, tool results, chat
   messages), the UUID will appear in ``agent.jsonl``.

2. **Reference-output fingerprint** — the first 3 non-trivial lines of the
   task's ``reference_output.*`` file, verbatim. Each line that is at least
   8 characters long and contains alphanumerics counts as a "line check"; a
   line that appears in ``agent.jsonl`` is considered a hit. The combined
   length of the three lines must reach ``MIN_COMBINED_LEN`` (80 chars) for
   any one line to count as a fingerprint (prevents trivial-prefix false
   positives on e.g. two-row files).

``audit_leak(task, agent_jsonl_path) -> bool`` returns ``True`` iff *any*
fingerprint matches. False by default — unreadable grader files (missing
sentinel, missing reference, unreadable transcript) never cause a false
positive; they just mean we have nothing to match against.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from swebench.artifact_models import Task


MIN_LINE_LEN = 8
MIN_COMBINED_LEN = 80
MAX_LINES = 3

_SENTINEL_RE = re.compile(r"#\s*GRADER-SENTINEL:\s*([A-Za-z0-9][A-Za-z0-9\-]{7,})")


@dataclass(frozen=True)
class Fingerprints:
    """Tokens extracted from a task's grader that must not appear in the agent transcript."""

    sentinel: str | None
    reference_lines: tuple[str, ...]


def _read_text_safely(path: Path) -> str | None:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return None


def _extract_reference_lines(text: str) -> tuple[str, ...]:
    """Return up to ``MAX_LINES`` non-trivial lines, or () if the pool is too small.

    A line is "non-trivial" if it is >= ``MIN_LINE_LEN`` chars after stripping
    and contains at least one alphanumeric character. We return the fingerprint
    tuple only if the combined length of the kept lines is >= ``MIN_COMBINED_LEN``
    (makes accidental matches on an agent echoing "hello" impossible).
    """
    kept: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if len(line) < MIN_LINE_LEN:
            continue
        if not any(ch.isalnum() for ch in line):
            continue
        kept.append(line)
        if len(kept) >= MAX_LINES:
            break
    if sum(len(s) for s in kept) < MIN_COMBINED_LEN:
        return ()
    return tuple(kept)


def extract_fingerprints(task: Task) -> Fingerprints:
    """Read ``task``'s grader files and extract the sentinel + reference-line fingerprints.

    Returns ``Fingerprints(None, ())`` if the task is not on disk, the grader
    files are missing, or no fingerprint could be extracted. The caller should
    treat the empty case as "nothing to audit" rather than an error — the
    materialiser already guarantees the grader files are not visible to the
    agent, so an absent fingerprint just means we lose one layer of defense
    in depth, not that the run is unsafe.
    """
    if task.task_dir is None:
        return Fingerprints(None, ())

    sentinel: str | None = None
    hidden_path = task.task_dir / task.hidden_grader
    text = _read_text_safely(hidden_path)
    if text is not None:
        m = _SENTINEL_RE.search(text)
        if m:
            sentinel = m.group(1)

    reference_lines: tuple[str, ...] = ()
    ref_path = task.task_dir / task.reference_output
    ref_text = _read_text_safely(ref_path)
    if ref_text is not None:
        reference_lines = _extract_reference_lines(ref_text)

    return Fingerprints(sentinel=sentinel, reference_lines=reference_lines)


def _normalise(text: str) -> str:
    """Collapse JSON-string escaping so reference lines match inside stream-json.

    ``agent.jsonl`` is a stream of JSON records; any reference line with double
    quotes (common for ``reference_output.jsonl``) will appear with the quotes
    escaped as ``\\"``. We strip those backslashes so a needle like
    ``{"endpoint": ...}`` matches both raw and JSON-embedded occurrences.
    """
    return text.replace('\\"', '"').replace("\\n", "\n")


def scan_text_for_fingerprints(text: str, fp: Fingerprints) -> bool:
    """Return True iff ``text`` contains the sentinel or any reference line."""
    haystack = _normalise(text)
    if fp.sentinel and fp.sentinel in haystack:
        return True
    for line in fp.reference_lines:
        if line and line in haystack:
            return True
    return False


def audit_leak(task: Task, agent_jsonl_path: Path) -> bool:
    """Scan ``agent.jsonl`` for any fingerprint derived from ``task``'s grader.

    Returns ``True`` iff a leak is detected. Never raises — a missing or
    unreadable transcript is treated as "nothing to scan" and returns ``False``.
    """
    fp = extract_fingerprints(task)
    if fp.sentinel is None and not fp.reference_lines:
        return False

    path = Path(agent_jsonl_path)
    text = _read_text_safely(path)
    if text is None:
        return False

    return scan_text_for_fingerprints(text, fp)
