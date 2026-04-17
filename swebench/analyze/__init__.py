"""`analyze` command group — log analysis pipeline subcommands."""

from __future__ import annotations

import click

from swebench.analyze.run import register_pathology_command
from swebench.analyze.summary import _register


@click.group("analyze")
def analyze_command() -> None:
    """Analyze SWE-bench results (summary table, etc.)."""


_register(analyze_command)
register_pathology_command(analyze_command)

__all__ = ["analyze_command"]
