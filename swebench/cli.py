"""Click CLI dispatcher for swebench commands."""

from __future__ import annotations

import sys

import click

from swebench._log import configure_logging, logger
from swebench.add import add_command
from swebench.run import run_command
from swebench.analyze import analyze_command
from swebench.cache_cli import cache_group


@click.group()
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    default=False,
    help="Enable DEBUG logging (overrides --log-level).",
)
@click.option(
    "--log-level",
    type=click.Choice(
        ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        case_sensitive=False,
    ),
    default="INFO",
    show_default=True,
    help="Loguru level for the stderr sink (ignored if --verbose is set).",
)
def cli(verbose: bool, log_level: str) -> None:
    """SWE-bench evaluation harness: add, run, analyze, and cache instances."""

    effective_level = "DEBUG" if verbose else log_level.upper()
    configure_logging(level=effective_level)
    logger.debug(f"swebench CLI started: {sys.argv[1:]}")


cli.add_command(add_command, "add")
cli.add_command(run_command, "run")
cli.add_command(analyze_command, "analyze")
cli.add_command(cache_group, "cache")
