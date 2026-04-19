"""Stable file-ops helpers for execute_code agents.

Goal: make repeated identical file reads return byte-identical output so
the prompt cache reuses prior tool-result bytes. The agent uses these
helpers as a high-level API and the server gets deterministic output as
a side effect.

Every function returns a string ready for `print()` — no hidden newlines,
no debug prefixes, no PIDs/timestamps. The agent is expected to do:

    import codebox
    src = codebox.read('/abs/path.py')
    print(src)

…not call these as side effects. Functions raise on error rather than
printing to stderr (so the failure mode is a normal Python exception,
which is also stably formatted).
"""
from __future__ import annotations

import os
import re as _re


def read(path: str) -> str:
    """Return the entire file as a string. UTF-8 with replacement on bad bytes."""
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def read_lines(path: str, start: int = 1, end: int | None = None) -> str:
    """Return inclusive line range [start, end] (1-indexed). end=None reads to EOF.

    Lines retain their trailing newlines. Empty result if start > end.
    """
    if start < 1:
        start = 1
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    sliced = lines[start - 1 : end]
    return "".join(sliced)


def files(root: str, pattern: str | None = None) -> str:
    """List files under ``root`` (recursive), one path per line, sorted.

    If ``pattern`` is given, filter file basenames by that regex (re.search).
    Sort gives deterministic output across calls.
    """
    rgx = _re.compile(pattern) if pattern else None
    out: list[str] = []
    for r, _, fs in os.walk(root):
        for f in fs:
            if rgx is None or rgx.search(f):
                out.append(os.path.join(r, f))
    out.sort()
    return "\n".join(out)


def grep(pattern: str, path: str, case: bool = False) -> str:
    """Grep ``pattern`` in ``path`` (file or directory).

    Output: ``path:lineno:line`` (line stripped of trailing whitespace),
    one match per line, sorted by (path, lineno). Recursive over .py files
    if ``path`` is a directory.
    """
    flags = _re.IGNORECASE if case else 0
    rgx = _re.compile(pattern, flags)
    targets: list[str] = []
    if os.path.isdir(path):
        for r, _, fs in os.walk(path):
            for f in fs:
                if f.endswith(".py"):
                    targets.append(os.path.join(r, f))
    else:
        targets = [path]
    targets.sort()
    out: list[str] = []
    for p in targets:
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f, 1):
                    if rgx.search(line):
                        out.append(f"{p}:{i}:{line.rstrip()}")
        except OSError:
            continue
    return "\n".join(out)


def edit_replace(path: str, old: str, new: str) -> None:
    """Replace exactly one occurrence of ``old`` with ``new`` in ``path``.

    Raises ValueError if ``old`` is missing or matches more than once,
    so the caller cannot silently corrupt the file. No return value —
    success is the absence of an exception.
    """
    with open(path, encoding="utf-8") as f:
        src = f.read()
    count = src.count(old)
    if count == 0:
        raise ValueError(f"edit_replace: pattern not found in {path}")
    if count > 1:
        raise ValueError(f"edit_replace: pattern matched {count}x in {path}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(src.replace(old, new, 1))


def write(path: str, content: str) -> None:
    """Write ``content`` to ``path`` (overwrites). Creates parent dirs."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
