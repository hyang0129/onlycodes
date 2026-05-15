"""MCP server config generation CLI.

Exposes one subcommand under ``python -m swebench mcp-config``:

- ``generate``: resolve the exec-server bundle path and write (or merge into)
  ``mcp-config.json`` with correct absolute paths for the current environment.
  Re-run after any container rebuild or workspace move.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import click

import swebench


@click.group(name="mcp-config")
def mcp_group() -> None:
    """Generate and validate the MCP server config for the exec-server."""


@mcp_group.command("generate")
@click.option(
    "--out",
    "out_path",
    default=None,
    help=(
        "Path to write the MCP config JSON "
        "(default: mcp-config.json at the repo root)."
    ),
)
def generate(out_path: str | None) -> None:
    """Write mcp-config.json with correct absolute paths for this environment.

    Resolves ``node``, the exec-server bundle, and the repo root automatically.
    Safe to re-run; existing non-codebox MCP servers are preserved.
    """
    pkg_root: Path = swebench.repo_root()

    # Resolve output path.
    out: Path = Path(out_path) if out_path is not None else pkg_root / "mcp-config.json"

    # 1. Resolve node — warn and fall back rather than exit.
    node_path = shutil.which("node")
    node_missing = node_path is None
    if node_missing:
        click.echo(
            "WARNING: node not found on PATH; config written with fallback /usr/bin/node",
            err=True,
        )
        node_path = "/usr/bin/node"

    # 2. Resolve exec-server bundle — exit non-zero if absent.
    bundle: Path = pkg_root / "exec_server" / "dist" / "exec-server.bundle.mjs"
    if not bundle.exists():
        click.echo(
            f"ERROR: exec-server bundle not found: {bundle}\n"
            "Build it first with `npm run build` inside exec_server/.",
            err=True,
        )
        sys.exit(1)

    # 3. Package root as cwd string.
    cwd = str(pkg_root)

    # 4. New codebox server dict.
    codebox_entry: dict = {
        "type": "stdio",
        "command": node_path,
        "args": [str(bundle)],
        "cwd": cwd,
        "env": {"ONLYCODES_PERSISTENT_KERNEL": "1"},
    }

    # 5. Merge with existing config (if the file exists).
    mcp_servers: dict = {}
    if out.exists():
        try:
            existing = json.loads(out.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            click.echo(
                f"ERROR: {out} contains invalid JSON and cannot be merged: {exc}\n"
                "Fix or remove the file, then re-run.",
                err=True,
            )
            sys.exit(1)
        # Preserve all non-codebox servers.
        mcp_servers = {
            k: v
            for k, v in existing.get("mcpServers", {}).items()
            if k != "codebox"
        }

    mcp_servers["codebox"] = codebox_entry
    config = {"mcpServers": mcp_servers}

    # 6. Write output JSON with indent=2 and a trailing newline.
    out.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    # 7. Success message.
    click.echo(f"Wrote MCP config to: {out}")
