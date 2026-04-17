"""Enforces the loguru migration invariants from epic #37.

These tests run as part of the normal `pytest tests/` suite and act as
CI guards against regressions in the loguru migration. Each test
encodes a single invariant and points at the file or pattern that may
NOT appear in the swebench package.
"""
from __future__ import annotations

import re
from pathlib import Path

SWEBENCH_DIR = Path(__file__).parent.parent / "swebench"


def _source_files() -> list[Path]:
    """Return every top-level python module in the swebench package."""
    return list(SWEBENCH_DIR.glob("*.py"))


def test_no_print_lock() -> None:
    """``_print_lock`` must not appear outside ``run.py`` (dual-emit preservation)."""
    violations: list[str] = []
    for path in _source_files():
        if path.name == "run.py":
            continue  # run.py keeps _print_lock for _flush_buffer atomicity
        text = path.read_text()
        if "_print_lock" in text:
            violations.append(str(path))
    assert not violations, f"_print_lock found in: {violations}"


def test_no_echo_wrapper() -> None:
    """``_echo()`` wrapper must not appear outside ``run.py``."""
    violations: list[str] = []
    for path in _source_files():
        if path.name == "run.py":
            continue  # run.py keeps _echo for buffered parallel output
        text = path.read_text()
        if re.search(r"def _echo\b", text):
            violations.append(str(path))
    assert not violations, f"_echo() wrapper found in: {violations}"


def test_no_stdlib_logging_import() -> None:
    """No swebench module should import stdlib ``logging`` (use loguru instead).

    ``_log.py`` is exempted because it owns the loguru → stdlib
    ``logging`` propagation bridge (``PropagateHandler``) used by pytest
    ``caplog``.
    """
    violations: list[str] = []
    for path in _source_files():
        if path.name == "_log.py":
            continue  # _log.py owns the PropagateHandler bridge
        text = path.read_text()
        if re.search(r"^import logging\b|^from logging\b", text, re.MULTILINE):
            violations.append(str(path))
    assert not violations, f"stdlib logging import found in: {violations}"


def test_logger_add_only_in_log_module() -> None:
    """Only ``swebench/_log.py`` may call ``logger.add()`` or ``logger.remove()``."""
    violations: list[str] = []
    for path in _source_files():
        if path.name == "_log.py":
            continue
        text = path.read_text()
        if re.search(r"logger\.(add|remove)\s*\(", text):
            violations.append(str(path))
    assert not violations, f"logger.add/remove outside _log.py: {violations}"


def test_no_bare_except_pass() -> None:
    """No bare ``except: pass`` (or equivalent) without a logger call.

    Heuristic: find ``except`` lines whose immediate next non-blank line
    is just ``pass``. The migration requires at least a DEBUG log before
    swallowing the exception so silenced failures remain diagnosable.
    """
    violations: list[str] = []
    for path in _source_files():
        text = path.read_text()
        lines = text.splitlines()
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("except") and stripped.endswith(":"):
                for j in range(i + 1, min(i + 4, len(lines))):
                    next_stripped = lines[j].strip()
                    if next_stripped:
                        if next_stripped == "pass":
                            violations.append(
                                f"{path.name}:{i + 1}: bare except+pass without logger"
                            )
                        break
    assert not violations, (
        "Bare except+pass found (should have logger before pass):\n"
        + "\n".join(violations)
    )
