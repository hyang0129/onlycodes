"""Bundled semi-mechanical extractors.

Each module in this subpackage calls
:func:`swebench.analyze.semi_mechanical.register` at import time to
register itself. Importing this package is the trigger.

Adding a new extractor is a one-file change: create
``swebench/analyze/extractors/<name>.py``, call ``register(...)`` at the
module top level, then add an ``import`` line below so the bundled loader
picks it up. No changes to ``run.py`` or ``semi_mechanical.py`` are needed.
"""

from __future__ import annotations

# Import for side-effects — each module registers itself.
from swebench.analyze.extractors import git_archaeology  # noqa: F401
from swebench.analyze.extractors import iteration_stall  # noqa: F401
