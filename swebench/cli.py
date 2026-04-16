"""Click CLI dispatcher for swebench commands."""

import click

from swebench.add import add_command
from swebench.run import run_command
from swebench.analyze import analyze_command


@click.group()
def cli() -> None:
    """SWE-bench evaluation harness: add, run, and analyze instances."""


cli.add_command(add_command, "add")
cli.add_command(run_command, "run")
cli.add_command(analyze_command, "analyze")
