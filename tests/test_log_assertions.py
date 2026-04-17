"""Tests that key loguru log lines appear at expected levels.

These exercise the contract from epic #37: specific operations MUST
emit observable INFO/WARNING records so operators can audit what the
harness did at runtime. Each test pairs a small, network-free invocation
with a ``caplog`` assertion on the expected substring.
"""
from __future__ import annotations

import io
import logging
from unittest.mock import patch

from loguru import logger

from swebench._log import add_buffer_sink, remove_sink


def test_detect_overlay_backend_logs_decision(propagate_handler, caplog):
    """``detect_overlay_backend()`` must log INFO with the chosen backend."""
    from swebench import cache

    caplog.set_level(logging.INFO, logger="swebench.cache")
    with patch.object(cache, "_can_kernel_mount", return_value=False), patch.object(
        cache, "_can_fuse_mount", return_value=False
    ):
        result = cache.detect_overlay_backend()

    assert result == "none"
    assert any("chosen" in r.getMessage() for r in caplog.records), (
        "Expected INFO with 'chosen' in cache.py logs. Got: "
        f"{[r.getMessage() for r in caplog.records]}"
    )


def test_verify_lockfile_warns_on_mismatch(
    propagate_handler, caplog, tmp_path
):
    """``verify_lockfile()`` must log WARNING when the venv drifts."""
    from swebench import cache

    venv_dir = tmp_path / "venv"
    venv_dir.mkdir()
    lockfile = tmp_path / "lockfile.txt"
    lockfile.write_text("package-a==1.0\n")

    caplog.set_level(logging.WARNING, logger="swebench.cache")
    with patch.object(cache, "_pip_freeze", return_value="package-a==2.0\n"):
        result = cache.verify_lockfile(str(venv_dir), str(lockfile))

    assert result is False
    assert any("mismatch" in r.getMessage().lower() for r in caplog.records), (
        "Expected WARNING with 'mismatch'. Got: "
        f"{[r.getMessage() for r in caplog.records]}"
    )


def test_add_buffer_sink_captures_logs():
    """``add_buffer_sink()`` must capture logger output into the buffer."""
    buf = io.StringIO()
    sink_id = add_buffer_sink(buf, level="DEBUG")
    try:
        logger.debug("test-buffer-message-12345")
        output = buf.getvalue()
        assert "test-buffer-message-12345" in output
    finally:
        remove_sink(sink_id)
