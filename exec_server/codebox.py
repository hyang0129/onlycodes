"""Stable file-ops helpers for execute_code agents.

Goal: make repeated identical reads return byte-identical output so the
prompt cache reuses prior tool-result bytes. The agent uses these helpers
as a high-level API and the server gets deterministic output as a side
effect.

Every read-style function returns a string ready for ``print()`` — no
hidden newlines, no debug prefixes, no PIDs/timestamps. The agent is
expected to do::

    import codebox
    print(codebox.outline('/abs/path.py'))

…not call these as side effects. Functions raise on error rather than
printing to stderr (so the failure mode is a normal Python exception,
which is also stably formatted).

API (read):
  outline(path)              top-level def/class with line numbers
  read_lines(path, s, e)     inclusive 1-indexed line slice
  peek(path, line, around)   line ± N (numbered)
  grep(pattern, path)        path:line:text matches, sorted
  files(root, pattern)       recursive listing
  source_of(symbol, root)    locate def/class and return its body

API (write):
  edit_replace(path, old, new)  exact-once literal swap; prints diff
  write(path, content)          overwrite whole file, mkdir -p

API (shell):
  run(cmd, *, tail, timeout, cwd)
                                run a shell command; returns trimmed stdout.
                                On non-zero exit from a test command, appends
                                the source of failing tests detected in output.
"""
from __future__ import annotations

import ast
import os
import re as _re
import shlex
import subprocess
from typing import Iterable


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

_DEF_OR_CLASS_RE = _re.compile(r"^(?P<indent>\s*)(?P<kind>def|class|async def)\s+(?P<name>\w+)")


def outline(path: str) -> str:
    """Return a structural outline: line count + top-level def/class lines.

    Includes module-level (depth 0) and one level of nesting (depth 1, i.e.
    methods of top-level classes). Deeper nestings are omitted; they are
    rare and inflate output for little navigation value.

    Output format::

        path/to/file.py (483 lines)

           12  class FooManager:
           29      def get(self, ...):
           56      def list(self, ...):
           82  class Bar:
           92      def parse(self, ...):

    Falls back to a regex scan if the file is not valid Python; ``ast`` is
    preferred because it gives precise line numbers and ignores defs that
    appear inside docstrings or comments.
    """
    with open(path, encoding="utf-8", errors="replace") as f:
        src = f.read()
    total_lines = src.count("\n") + (0 if src.endswith("\n") or not src else 1)
    header = f"{path} ({total_lines} lines)\n"
    items: list[tuple[int, int, str, str]] = []  # (lineno, depth, kind, signature)
    try:
        tree = ast.parse(src)
    except SyntaxError:
        for i, line in enumerate(src.splitlines(), 1):
            m = _DEF_OR_CLASS_RE.match(line)
            if not m:
                continue
            depth = 0 if not m.group("indent") else 1
            if depth > 1:
                continue
            items.append((i, depth, m.group("kind"), line.rstrip()))
    else:
        def _signature(node: ast.AST) -> str:
            if isinstance(node, ast.AsyncFunctionDef):
                return f"async def {node.name}(...)"
            if isinstance(node, ast.FunctionDef):
                return f"def {node.name}(...)"
            if isinstance(node, ast.ClassDef):
                bases = ", ".join(_unparse(b) for b in node.bases)
                return f"class {node.name}({bases}):" if bases else f"class {node.name}:"
            return ""

        def _unparse(node: ast.AST) -> str:
            try:
                return ast.unparse(node)
            except Exception:
                return "?"

        for top in tree.body:
            if isinstance(top, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                items.append((top.lineno, 0, type(top).__name__, _signature(top)))
                if isinstance(top, ast.ClassDef):
                    for inner in top.body:
                        if isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            items.append((inner.lineno, 1, type(inner).__name__, _signature(inner)))
    if not items:
        return header + "(no top-level def/class found)"
    out = [header]
    for lineno, depth, _kind, sig in items:
        out.append(f"  {lineno:>5}  {'    ' * depth}{sig}")
    return "\n".join(out)


def read_lines(path: str, start: int = 1, end: int | None = None) -> str:
    """Return inclusive line range [start, end] (1-indexed). end=None reads to EOF.

    Lines retain their trailing newlines. Empty result if start > end.
    """
    if start < 1:
        start = 1
    if end is not None and end < start:
        raise ValueError(f"read_lines: end ({end}) must be >= start ({start})")
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    sliced = lines[start - 1 : end]
    return "".join(sliced)


def peek(path: str, line: int, around: int = 10) -> str:
    """Return ``[line - around, line + around]`` with each line prefixed by its number.

    Pairs naturally with ``grep`` output (``path:line:text``): take the line
    number, peek around it. Output stays compact and includes context
    enough to make most edits.
    """
    if line < 1:
        line = 1
    if around < 0:
        around = 0
    start = max(1, line - around)
    end = line + around
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    sliced = lines[start - 1 : end]
    width = len(str(start + len(sliced) - 1))
    return "".join(f"{start + i:>{width}}  {ln}" for i, ln in enumerate(sliced))


def files(root: str, pattern: str | None = None) -> str:
    """List files under ``root`` (recursive), one path per line, sorted.

    If ``pattern`` is given, filter file basenames by that regex (re.search).
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


def source_of(symbol: str, root: str) -> str:
    """Locate a function/class named ``symbol`` and return its source body.

    ``root`` may be a file path or a directory. For directories, walks
    ``.py`` files recursively. Top-level defs and class methods are both
    matched; if multiple matches are found, returns all of them separated
    by a header line so the agent can disambiguate.

    Output format per match::

        --- path/to/file.py:LINE-END ---
        def symbol(...):
            ...

    Raises ``ValueError`` if no matching symbol is found anywhere in
    ``root``.
    """
    targets: list[str] = []
    if os.path.isdir(root):
        for r, _, fs in os.walk(root):
            for f in fs:
                if f.endswith(".py"):
                    targets.append(os.path.join(r, f))
    elif os.path.isfile(root):
        targets = [root]
    else:
        raise ValueError(f"source_of: {root} is neither file nor directory")
    targets.sort()

    matches: list[tuple[str, int, int, str]] = []  # (path, start, end, src)
    for p in targets:
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                src = f.read()
        except OSError:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name == symbol:
                    end = getattr(node, "end_lineno", node.lineno)
                    body = "\n".join(src.splitlines()[node.lineno - 1 : end])
                    matches.append((p, node.lineno, end, body))
    if not matches:
        raise ValueError(f"source_of: symbol {symbol!r} not found in {root}")
    out: list[str] = []
    for path, start, end, body in matches:
        out.append(f"--- {path}:{start}-{end} ---\n{body}")
    return "\n\n".join(out)


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------


def edit_replace(path: str, old: str, new: str) -> str:
    """Replace exactly one occurrence of ``old`` with ``new`` in ``path``.

    Raises ValueError if ``old`` is missing or matches more than once,
    so the caller cannot silently corrupt the file. On success, returns
    a small diff-style context preview (3 lines on each side of the
    change) so the caller does not need a follow-up read to verify.
    """
    with open(path, encoding="utf-8") as f:
        src = f.read()
    count = src.count(old)
    if count == 0:
        raise ValueError(f"edit_replace: pattern not found in {path}")
    if count > 1:
        raise ValueError(f"edit_replace: pattern matched {count}x in {path}")
    new_src = src.replace(old, new, 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_src)

    # Build a compact context preview around the edited region.
    new_lines = new_src.splitlines(keepends=True)
    # Locate the start of `new` in new_src by char index, convert to line number.
    char_idx = new_src.find(new)
    if char_idx < 0:
        return f"edited {path}"
    line_start = new_src.count("\n", 0, char_idx) + 1
    line_end = line_start + max(0, new.count("\n") - (1 if new.endswith("\n") else 0))
    around = 3
    s = max(1, line_start - around)
    e = min(len(new_lines), line_end + around)
    width = len(str(e))
    body = "".join(f"{s + i:>{width}}  {new_lines[s - 1 + i]}" for i in range(e - s + 1))
    return f"edited {path}: lines {line_start}-{line_end}\n{body}"


def write(path: str, content: str) -> None:
    """Write ``content`` to ``path`` (overwrites). Creates parent dirs."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


# ---------------------------------------------------------------------------
# Shell helper
# ---------------------------------------------------------------------------


_TEST_CMD_HINTS = ("runtests.py", "pytest", "py.test", "unittest")
_UNITTEST_FAIL_RE = _re.compile(
    r"^(?:FAIL|ERROR):\s+(?P<test>\w+)\s+\((?P<module>[\w.]+)\)\s*$",
    _re.MULTILINE,
)
_PYTEST_FAIL_RE = _re.compile(
    r"^FAILED\s+(?P<file>[\w./_-]+\.py)::(?:(?P<cls>\w+)::)?(?P<test>\w+)",
    _re.MULTILINE,
)


def _is_test_cmd(cmd: str) -> bool:
    low = cmd.lower()
    return any(h in low for h in _TEST_CMD_HINTS)


def _detect_test_failures(output: str, search_root: str, *, limit: int = 3) -> str:
    """Find failing tests in unittest/pytest output and return their source.

    Returns an empty string if nothing parseable is found. Capped at
    ``limit`` failures and roughly 200 lines per failure to keep output
    bounded.
    """
    seen: set[tuple[str, str]] = set()
    pairs: list[tuple[str, str]] = []  # (test_name, hint)

    for m in _UNITTEST_FAIL_RE.finditer(output):
        key = (m.group("test"), m.group("module"))
        if key in seen:
            continue
        seen.add(key)
        pairs.append(key)
        if len(pairs) >= limit:
            break

    if len(pairs) < limit:
        for m in _PYTEST_FAIL_RE.finditer(output):
            key = (m.group("test"), m.group("file"))
            if key in seen:
                continue
            seen.add(key)
            pairs.append(key)
            if len(pairs) >= limit:
                break

    if not pairs:
        return ""

    chunks: list[str] = []
    for test_name, hint in pairs:
        body = _locate_test_body(test_name, hint, search_root)
        if body:
            chunks.append(body)
    return "\n\n".join(chunks)


def _locate_test_body(test_name: str, hint: str, search_root: str) -> str:
    """Locate ``def test_name`` in a file derived from ``hint`` and return its source."""
    candidates: list[str] = []

    if hint.endswith(".py") or "/" in hint:
        # pytest-style file path
        if os.path.isabs(hint):
            candidates.append(hint)
        else:
            candidates.append(os.path.join(search_root, hint))
            # Also try search_root as parent of "tests/"
            candidates.append(os.path.join(search_root, "tests", hint))
    else:
        # unittest module path (drop trailing class segment if present).
        parts = hint.split(".")
        if parts and parts[-1][:1].isupper():
            parts = parts[:-1]
        rel = os.path.join(*parts) + ".py" if parts else ""
        if rel:
            candidates.append(os.path.join(search_root, rel))
            candidates.append(os.path.join(search_root, "tests", rel))

    for cand in candidates:
        if os.path.isfile(cand):
            body = _extract_def(cand, test_name)
            if body:
                return body

    # Fallback: walk the tree looking for a matching def in any test_*.py
    # file whose basename matches the last segment of the hint.
    last = hint.rsplit("/", 1)[-1].rsplit(".", 1)[-1] if hint else ""
    last_basename = f"{last}.py" if last else None
    for r, _, fs in os.walk(search_root):
        for f in fs:
            if not f.endswith(".py"):
                continue
            if last_basename and f != last_basename:
                continue
            body = _extract_def(os.path.join(r, f), test_name)
            if body:
                return body
    return ""


def _extract_def(path: str, name: str, max_lines: int = 200) -> str:
    """Return ``path:start-end`` header + truncated source of a def named ``name``."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            src = f.read()
    except OSError:
        return ""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return ""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            end = getattr(node, "end_lineno", node.lineno)
            body_lines = src.splitlines()[node.lineno - 1 : end]
            truncated = body_lines[:max_lines]
            note = "" if len(body_lines) <= max_lines else f"\n... ({len(body_lines) - max_lines} more lines)"
            return f"--- {path}:{node.lineno}-{end} ---\n" + "\n".join(truncated) + note
    return ""


def run(cmd: str, *, tail: int = 20, timeout: int = 120, cwd: str | None = None) -> str:
    """Run a shell command and return its (clipped) output as a single string.

    Replaces the verbose ``subprocess.run([...], capture_output=True, ...)``
    boilerplate. Output is the trimmed stdout on success; on non-zero
    exit it includes a short header, the last ``tail`` lines of stdout,
    and stderr (also tail-clipped).

    For test-runner commands (``pytest``, ``runtests.py``, ``unittest``)
    that exit non-zero, the source of the failing tests detected in the
    output is appended (up to 3 tests). This is the single biggest cause
    of wasted retry loops in onlycode runs (agent forgot the test mocks
    ``utcnow`` etc.) — surface the test source the first time around so
    the next iteration has the context it needs.
    """
    if not isinstance(cmd, str):
        raise TypeError("run: cmd must be a string (use shell-style invocation)")
    proc = subprocess.run(
        cmd,
        shell=True,
        cwd=cwd,
        timeout=timeout,
        capture_output=True,
        text=True,
    )
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    ec = proc.returncode

    if ec == 0:
        return _tail(stdout, tail)

    parts: list[str] = [f"$ {cmd}", f"exit {ec}"]
    if stdout:
        parts.append("--- stdout (tail) ---")
        parts.append(_tail(stdout, tail))
    if stderr:
        parts.append("--- stderr (tail) ---")
        parts.append(_tail(stderr, tail))
    if _is_test_cmd(cmd):
        search_root = cwd or os.getcwd()
        # Look in stdout AND stderr; pytest writes failures to stdout, unittest
        # often interleaves traceback details across both streams.
        failures = _detect_test_failures(stdout + "\n" + stderr, search_root)
        if failures:
            parts.append("--- failing test source ---")
            parts.append(failures)
    return "\n".join(parts)


def _tail(text: str, n: int) -> str:
    if n <= 0:
        return text
    lines = text.splitlines()
    if len(lines) <= n:
        return text.rstrip("\n")
    head_note = f"... ({len(lines) - n} earlier lines elided)"
    return "\n".join([head_note, *lines[-n:]])
