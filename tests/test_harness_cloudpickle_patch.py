"""Tests for _patch_vendored_cloudpickle (issue #208)."""

from __future__ import annotations

from pathlib import Path

from swebench.harness import (
    _VENDORED_CLOUDPICKLE_REL,
    _patch_vendored_cloudpickle,
)


_PRE_38_SNIPPET = """\
    if not PY3:
        return types.CodeType(
            co.co_argcount,
            co.co_nlocals,
        )
    else:
        return types.CodeType(
            co.co_argcount,
            co.co_kwonlyargcount,
            co.co_nlocals,
        )
"""


def _write_vendored(repo_dir: Path, text: str) -> Path:
    path = repo_dir / _VENDORED_CLOUDPICKLE_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_patch_inserts_posonlyargcount(tmp_path: Path) -> None:
    path = _write_vendored(tmp_path, _PRE_38_SNIPPET)
    assert _patch_vendored_cloudpickle(str(tmp_path)) is True
    patched = path.read_text()
    assert "co.co_posonlyargcount" in patched
    # PY2 branch (no co_kwonlyargcount) must be left alone.
    assert patched.count("co.co_posonlyargcount") == 1
    # The new arg sits between argcount and kwonlyargcount.
    idx_arg = patched.index("co.co_argcount")
    idx_pos = patched.index("co.co_posonlyargcount")
    idx_kw = patched.index("co.co_kwonlyargcount")
    assert idx_arg < idx_pos < idx_kw


def test_patch_is_idempotent(tmp_path: Path) -> None:
    _write_vendored(tmp_path, _PRE_38_SNIPPET)
    assert _patch_vendored_cloudpickle(str(tmp_path)) is True
    assert _patch_vendored_cloudpickle(str(tmp_path)) is False


def test_noop_when_file_missing(tmp_path: Path) -> None:
    assert _patch_vendored_cloudpickle(str(tmp_path)) is False


def test_noop_when_pattern_absent(tmp_path: Path) -> None:
    _write_vendored(tmp_path, "# unrelated cloudpickle content\n")
    assert _patch_vendored_cloudpickle(str(tmp_path)) is False
