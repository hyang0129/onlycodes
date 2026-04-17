"""Foundation tests for ``swebench._log`` (issue #42, epic #37).

Covers the three guarantees the rest of the epic relies on:

1. ``configure_logging`` toggles the stderr level between DEBUG and INFO.
2. The propagate handler bridges loguru → ``caplog``.
3. ``add_buffer_sink`` / ``remove_sink`` round-trip through a buffer.
"""

from __future__ import annotations

import io
import logging

from loguru import logger

from swebench._log import (
    add_buffer_sink,
    configure_logging,
    remove_sink,
)


def test_configure_logging_info_suppresses_debug(capsys):
    configure_logging(level="INFO")
    logger.debug("hidden-debug-line")
    logger.info("visible-info-line")
    err = capsys.readouterr().err
    assert "visible-info-line" in err
    assert "hidden-debug-line" not in err


def test_configure_logging_debug_emits_debug(capsys):
    configure_logging(level="DEBUG")
    logger.debug("visible-debug-line")
    err = capsys.readouterr().err
    assert "visible-debug-line" in err
    # Verbose format includes file/function/line origin.
    assert "test_logging" in err


def test_propagate_handler_reaches_caplog(caplog, propagate_handler):
    caplog.set_level(logging.DEBUG)
    logger.info("bridged-message")
    messages = [r.getMessage() for r in caplog.records]
    assert any("bridged-message" in m for m in messages)


def test_add_and_remove_buffer_sink_round_trip():
    buf = io.StringIO()
    sink_id = add_buffer_sink(buf, level="DEBUG")
    try:
        logger.debug("captured-by-buffer")
    finally:
        remove_sink(sink_id)

    assert "captured-by-buffer" in buf.getvalue()

    # After removal, further records should NOT land in the buffer.
    before = buf.getvalue()
    logger.debug("post-removal-line")
    assert buf.getvalue() == before


def test_configure_logging_is_idempotent(capsys):
    configure_logging(level="INFO")
    configure_logging(level="INFO")
    logger.info("only-once-please")
    err = capsys.readouterr().err
    # Exactly one occurrence — no duplicate sinks stacked up.
    assert err.count("only-once-please") == 1
