"""Tests for _needs_jinja2_pin and _pin_jinja2."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from swebench.harness import _needs_jinja2_pin, _pin_jinja2


# ---------------------------------------------------------------------------
# _needs_jinja2_pin
# ---------------------------------------------------------------------------


def test_needs_pin_when_environmentfilter_present(tmp_path: Path) -> None:
    rst = tmp_path / "sphinx" / "util" / "rst.py"
    rst.parent.mkdir(parents=True)
    rst.write_text("from jinja2 import environmentfilter\n")
    assert _needs_jinja2_pin(str(tmp_path)) is True


def test_no_pin_when_environmentfilter_absent(tmp_path: Path) -> None:
    rst = tmp_path / "sphinx" / "util" / "rst.py"
    rst.parent.mkdir(parents=True)
    rst.write_text("from jinja2 import pass_environment\n")
    assert _needs_jinja2_pin(str(tmp_path)) is False


def test_no_pin_when_file_missing(tmp_path: Path) -> None:
    assert _needs_jinja2_pin(str(tmp_path)) is False


def test_no_pin_on_oserror(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rst = tmp_path / "sphinx" / "util" / "rst.py"
    rst.parent.mkdir(parents=True)
    rst.write_text("environmentfilter")

    def raise_oserror(*_a, **_kw):
        raise OSError("permission denied")

    monkeypatch.setattr("builtins.open", raise_oserror)
    assert _needs_jinja2_pin(str(tmp_path)) is False


# ---------------------------------------------------------------------------
# _pin_jinja2
# ---------------------------------------------------------------------------


def test_pin_jinja2_calls_correct_constraint() -> None:
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        _pin_jinja2("/venv/bin/pip")
    args = mock_run.call_args[0][0]
    assert args == ["/venv/bin/pip", "install", "--quiet", "jinja2<3.0,>=2.11"]


def test_pin_jinja2_raises_on_failure() -> None:
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1,
            args=["/venv/bin/pip", "install", "--quiet", "jinja2<3.0,>=2.11"],
            stdout="",
            stderr="Could not find a version",
        )
        with pytest.raises(subprocess.CalledProcessError):
            _pin_jinja2("/venv/bin/pip")
