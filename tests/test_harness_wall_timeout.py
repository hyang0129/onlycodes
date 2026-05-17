"""Unit test for wall-time cap enforcement in ClaudeRunner.invoke().

Issue #223 — harness: enforce wall-time cap on agent invocations.

The Coder agent adds ``wall_timeout_seconds`` to ``ClaudeRunner.invoke()``.
When the subprocess exceeds the cap the harness must:
  1. Kill the subprocess.
  2. Append a synthetic JSON line with ``{"type": "system", "subtype": "wall_timeout"}``
     to the result file.
  3. Return (not raise) so the caller can treat it as a completed (timed-out) arm.

This test uses a fake agent binary that sleeps 5 seconds, a 1-second cap, and
verifies the whole round-trip completes in under 3 seconds.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from swebench.runner import ClaudeRunner


def test_wall_timeout_kills_runaway_agent(tmp_path: Path) -> None:
    """ClaudeRunner.invoke() must kill a runaway agent and record a timeout sentinel."""
    # A fake agent that just sleeps — no real claude binary needed.
    fake_agent = tmp_path / "fake_agent.sh"
    # Sleep 30s so the kill is clearly early even under system load.
    fake_agent.write_text("#!/bin/sh\nsleep 30\n")
    fake_agent.chmod(0o755)

    result_file = tmp_path / "result.jsonl"

    start = time.time()
    ClaudeRunner().invoke(
        prompt="does not matter",
        cwd=str(tmp_path),
        system_prompt="",
        tools_flags=[],
        result_file=str(result_file),
        binary=str(fake_agent),
        wall_timeout_seconds=1,
    )
    elapsed = time.time() - start

    assert elapsed < 5.0, (
        f"Expected invoke() to return within 5 s after 1-s cap, took {elapsed:.2f}s"
    )

    assert result_file.exists(), "result_file must be created even on timeout"
    lines = [ln for ln in result_file.read_text().splitlines() if ln.strip()]
    assert lines, "result_file must not be empty after a wall-timeout"

    last = json.loads(lines[-1])
    assert last.get("type") == "system", (
        f"Last JSON line must have type='system', got: {last!r}"
    )
    assert last.get("subtype") == "wall_timeout", (
        f"Last JSON line must have subtype='wall_timeout', got: {last!r}"
    )
