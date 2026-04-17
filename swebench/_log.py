"""Loguru configuration seam for the swebench package.

All loguru configuration lives here. No other module calls
``logger.add()`` or ``logger.remove()`` directly. Modules that need
to attach a temporary sink (for example, ``run.py``'s per-arm
``StringIO`` buffer in parallel mode) MUST go through
:func:`add_buffer_sink` / :func:`remove_sink`.

Output contract
---------------
* Loguru writes diagnostic output to **stderr only**.
* **stdout** is reserved for user-facing data (currently only
  ``analyze.py``'s ``tabulate`` table). Reviewers must reject any
  change that routes machine-readable user data through the logger.

caplog interop
--------------
:func:`configure_logging` always installs a ``PropagateHandler`` that
forwards loguru records into the stdlib ``logging`` tree at the
configured level. This means pytest's standard ``caplog`` fixture
works against loguru calls without per-test sink hackery and without
sniffing ``PYTEST_CURRENT_TEST``.

Verbose semantics
-----------------
* ``--log-level INFO`` (default): concise format, INFO and above.
* ``--verbose`` / ``--log-level DEBUG``: enables DEBUG and adds
  ``{name}:{function}:{line}`` to every record.
"""

from __future__ import annotations

import logging
import sys
from typing import IO

from loguru import logger

__all__ = [
    "logger",
    "configure_logging",
    "add_buffer_sink",
    "remove_sink",
    "PropagateHandler",
]


# Format strings — DEBUG includes file/line origin, INFO+ stays concise.
_VERBOSE_FORMAT = (
    "<level>{level: <8}</level> | {name}:{function}:{line} - {message}"
)
_DEFAULT_FORMAT = "<level>{level: <8}</level> | {message}"

# Format used by buffer sinks (run.py parallel mode). Always includes
# file/line so the captured per-arm transcript is self-describing
# regardless of the global level.
_BUFFER_FORMAT = (
    "<level>{level: <8}</level> | {name}:{function}:{line} - {message}"
)


class PropagateHandler(logging.Handler):
    """Forward loguru records into the stdlib ``logging`` tree.

    Installed unconditionally by :func:`configure_logging` so that
    pytest's ``caplog`` fixture captures loguru output without any
    per-test plumbing.
    """

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - trivial
        logging.getLogger(record.name).handle(record)


def configure_logging(level: str = "INFO") -> None:
    """Install the canonical stderr sink and the caplog propagation bridge.

    Always idempotent: removes any previously-registered sinks first so
    repeated calls (e.g. the ``autouse`` test fixture) do not stack
    handlers.

    Parameters
    ----------
    level:
        Loguru level name (``"DEBUG"``, ``"INFO"``, ``"WARNING"``,
        ``"ERROR"``, ``"CRITICAL"``). The format string includes
        ``{name}:{function}:{line}`` whenever ``level`` is ``"DEBUG"``;
        otherwise the concise format is used.
    """

    normalized = (level or "INFO").upper()
    fmt = _VERBOSE_FORMAT if normalized == "DEBUG" else _DEFAULT_FORMAT

    logger.remove()
    logger.add(
        sys.stderr,
        format=fmt,
        level=normalized,
    )

    # caplog interop — always install. The cost is one stdlib handler;
    # the benefit is that pytest's caplog fixture captures loguru output
    # in any environment (CI, local, integration) with no conditional
    # logic.
    logger.add(
        PropagateHandler(),
        format="{message}",
        level=normalized,
    )


def add_buffer_sink(buf: IO[str], level: str = "DEBUG") -> int:
    """Attach a loguru sink that writes to ``buf``.

    Used by ``run.py`` parallel mode to capture each arm's transcript
    into a per-arm ``StringIO`` buffer for atomic flush after the arm
    completes. ``enqueue=False`` is deliberate — the caller wants
    synchronous writes so ``_flush_buffer`` sees a complete transcript.

    Parameters
    ----------
    buf:
        Any file-like object supporting ``.write(str)``.
    level:
        Minimum loguru level to capture into the buffer. Defaults to
        ``DEBUG`` so per-arm transcripts retain full detail regardless
        of the global stderr level.

    Returns
    -------
    int
        The loguru sink id, to be passed back to :func:`remove_sink`.
    """

    return logger.add(
        buf,
        format=_BUFFER_FORMAT,
        level=(level or "DEBUG").upper(),
        enqueue=False,
    )


def remove_sink(sink_id: int) -> None:
    """Remove a previously-added sink.

    The only sanctioned wrapper around ``logger.remove()`` for callers
    outside this module. Keeps the "no module configures loguru except
    ``_log.py``" invariant intact.
    """

    logger.remove(sink_id)
