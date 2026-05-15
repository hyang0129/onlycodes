"""Integration smoke test for CodexRunner against a real codex binary.

Skipped automatically if:
- ``codex`` is not on PATH, OR
- ``~/.codex/auth.json`` is absent (user not authenticated).

Run with: pytest -m integration tests/test_runner_codex_integration.py
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from swebench.runner import CodexRunner


@pytest.mark.integration
def test_codex_real_invocation(tmp_path):
    """CodexRunner.invoke() produces a non-empty, all-valid-JSON JSONL log."""
    # --- Preflight: skip if environment is not ready --------------------------
    if shutil.which("codex") is None:
        pytest.skip("codex binary not found on PATH — skipping integration test")

    auth_path = Path.home() / ".codex" / "auth.json"
    if not auth_path.is_file():
        pytest.skip(
            "~/.codex/auth.json not found — Codex CLI not authenticated; "
            "skipping integration test"
        )

    # --- Setup ----------------------------------------------------------------
    runner = CodexRunner()
    binary = runner.find_binary()

    result_file = tmp_path / "agent.jsonl"
    result_file.touch()

    prompt = "Just print the string hello and exit. Do nothing else."

    # --- Invoke ---------------------------------------------------------------
    runner.invoke(
        prompt=prompt,
        cwd=str(tmp_path),
        system_prompt="You are a helpful assistant.",
        tools_flags=[],
        result_file=str(result_file),
        binary=binary,
        mcp_config_path=None,
    )

    # --- Assertions -----------------------------------------------------------
    content = result_file.read_text()
    assert content.strip(), "JSONL log must be non-empty after a codex invocation"

    lines = [ln for ln in content.splitlines() if ln.strip()]
    assert lines, "JSONL log must contain at least one non-blank line"

    for i, line in enumerate(lines):
        try:
            json.loads(line)
        except json.JSONDecodeError as exc:
            pytest.fail(
                f"Line {i + 1} of the JSONL log is not valid JSON: {exc}\n"
                f"Line content: {line!r}"
            )

    # --- Metadata extraction --------------------------------------------------
    _cost, turns = runner.extract_metadata(result_file)
    assert turns is not None, (
        "extract_metadata() must return a non-None turn count after a real run. "
        f"JSONL content:\n{content}"
    )
