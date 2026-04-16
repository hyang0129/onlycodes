"""SWE-bench evaluation CLI — add, run, analyze."""

from pathlib import Path


def repo_root() -> Path:
    """Return the repository root (parent of swebench/)."""
    return Path(__file__).resolve().parent.parent
