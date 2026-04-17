"""Shared pytest fixtures for the swebench test suite.

Two fixtures are provided here:

* :func:`reset_loguru` (autouse) — resets the loguru singleton before each
  test and re-installs the canonical configuration via
  :func:`swebench._log.configure_logging`. Without this, any test that
  attaches a sink leaks handlers across the suite, producing duplicate
  log lines and false-positive ``caplog`` assertions in later tests.

* :func:`propagate_handler` — explicit fixture that installs (or rather,
  re-confirms) the loguru → stdlib bridge. ``configure_logging`` already
  installs ``PropagateHandler`` unconditionally, so this fixture's main
  job is to set the stdlib root logger level low enough that ``caplog``
  captures DEBUG records too.
"""

from __future__ import annotations

import logging

import pytest
from loguru import logger

from swebench._log import PropagateHandler, configure_logging


@pytest.fixture(autouse=True)
def reset_loguru():
    """Tear down + re-install loguru sinks around every test.

    Marked ``autouse`` because loguru is a process-global singleton and
    stale sinks would cause cross-test pollution even for tests that
    never touch logging directly.
    """

    logger.remove()
    configure_logging(level="DEBUG")
    try:
        yield
    finally:
        logger.remove()


@pytest.fixture
def propagate_handler(caplog):
    """Ensure loguru records reach pytest's ``caplog`` fixture.

    ``configure_logging`` already installs a ``PropagateHandler`` for
    every test (via ``reset_loguru`` above). This fixture additionally
    lowers the stdlib root logger to DEBUG so ``caplog`` sees every
    propagated record, and yields the handler class for tests that want
    to assert on its behaviour directly.
    """

    caplog.set_level(logging.DEBUG)
    yield PropagateHandler
