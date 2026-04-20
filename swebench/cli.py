"""Click CLI dispatcher for swebench commands."""

import click

from swebench.add import add_command
from swebench.run import run_command
from swebench.analyze import analyze_command
from swebench.cache_cli import cache_group
from swebench.artifact_cli import artifact_group


@click.group()
def cli() -> None:
    """SWE-bench evaluation harness: add, run, analyze, and cache instances."""


cli.add_command(add_command, "add")
cli.add_command(run_command, "run")
cli.add_command(analyze_command, "analyze")
cli.add_command(cache_group, "cache")
cli.add_command(artifact_group, "artifact")
