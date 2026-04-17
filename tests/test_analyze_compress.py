"""Tests for ``swebench.analyze.compress`` (Stage 2a log compressor).

Uses the shared fixtures in ``tests/fixtures/logs/`` plus a synthetic
``traceback_large.jsonl`` crafted to exercise error-aware truncation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swebench.analyze import compress as compress_module
from swebench.analyze.compress import (
    ERROR_MARKERS,
    TRUNCATE_HEAD_LINES,
    TRUNCATE_TAIL_LINES,
    TRUNCATE_THRESHOLD_LINES,
    compress,
)
from swebench.analyze.extractor import TURN_DEFINITION, count_turns, iter_records

FIXTURES = Path(__file__).parent / "fixtures" / "logs"
DJANGO_ONLYCODE = FIXTURES / "django__django-16379_onlycode_run1.jsonl"
DJANGO_BASELINE = FIXTURES / "django__django-16379_baseline_run1.jsonl"
XARRAY_ONLYCODE = FIXTURES / "pydata__xarray-7229_onlycode_run1.jsonl"
ORPHAN_BASELINE = FIXTURES / "orphan_only_baseline_run1.jsonl"
ARM_CRASH = FIXTURES / "arm_crash_onlycode_run1.jsonl"
TRACEBACK_LARGE = FIXTURES / "traceback_large.jsonl"


# ---------------------------------------------------------------------------
# Smoke / basic contract
# ---------------------------------------------------------------------------


def test_compress_returns_string():
    out = compress(DJANGO_ONLYCODE)
    assert isinstance(out, str)
    assert out.strip()


def test_compress_header_includes_turns_and_definition():
    out = compress(DJANGO_ONLYCODE)
    turns = count_turns(iter_records(DJANGO_ONLYCODE))
    assert f"turns ({TURN_DEFINITION}): {turns}" in out


def test_compress_is_plain_text_not_json():
    out = compress(DJANGO_ONLYCODE)
    # It must NOT parse as a single JSON object.
    with pytest.raises(json.JSONDecodeError):
        json.loads(out)


def test_compress_empty_arm_crash():
    # Has no assistant records; should still produce a header and not crash.
    out = compress(ARM_CRASH)
    assert "Compressed run transcript" in out
    assert "turns" in out


# ---------------------------------------------------------------------------
# rate_limit_event stripping
# ---------------------------------------------------------------------------


def test_rate_limit_events_stripped(tmp_path: Path):
    path = tmp_path / "with_rate_limits.jsonl"
    records = [
        {"type": "system", "subtype": "init", "cwd": "/tmp", "session_id": "s"},
        {"type": "rate_limit_event", "message": "SHOULD_NOT_APPEAR_IN_OUTPUT_12345"},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}},
        {"type": "rate_limit_event", "message": "ALSO_SHOULD_NOT_APPEAR_98765"},
        {"type": "result", "subtype": "success", "num_turns": 0, "total_cost_usd": 0.0},
    ]
    with path.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    out = compress(path)
    assert "SHOULD_NOT_APPEAR_IN_OUTPUT_12345" not in out
    assert "ALSO_SHOULD_NOT_APPEAR_98765" not in out
    assert "rate_limit_event" not in out


# ---------------------------------------------------------------------------
# thinking preservation (including signature)
# ---------------------------------------------------------------------------


def test_thinking_signature_preserved_verbatim(tmp_path: Path):
    path = tmp_path / "thinking.jsonl"
    sig = "EpMCClsIDBgCKkC0kJidyssjzpKyNZZcuZy8ODOWkwTBPdQdRDYe2dnyVxlQ57Er"
    thinking_text = "Let me reason about this in extreme detail."
    records = [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "thinking",
                        "thinking": thinking_text,
                        "signature": sig,
                    }
                ]
            },
        }
    ]
    with path.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    out = compress(path)
    assert sig in out, "thinking.signature must be preserved verbatim"
    assert thinking_text in out


# ---------------------------------------------------------------------------
# Nested tool_result unwrap (codebox shape)
# ---------------------------------------------------------------------------


def test_tool_result_nested_json_unwrapped(tmp_path: Path):
    path = tmp_path / "toolres.jsonl"
    payload = json.dumps(
        {
            "stdout": "hello world\nsecond line",
            "stderr": "a warning",
            "exit_code": 0,
        }
    )
    records = [
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_abc",
                        "content": [{"type": "text", "text": payload}],
                    }
                ]
            },
        }
    ]
    with path.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    out = compress(path)
    assert "hello world" in out
    assert "second line" in out
    assert "a warning" in out
    assert "exit_code: 0" in out
    # Raw JSON braces/keys should not be the dominant shape.
    assert '"stdout"' not in out


def test_tool_result_non_codebox_string_passthrough(tmp_path: Path):
    path = tmp_path / "plain.jsonl"
    records = [
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_plain",
                        "content": [{"type": "text", "text": "just a plain string"}],
                    }
                ]
            },
        }
    ]
    with path.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    out = compress(path)
    assert "just a plain string" in out


# ---------------------------------------------------------------------------
# Error-aware truncation
# ---------------------------------------------------------------------------


def test_truncation_keeps_head_and_tail():
    out = compress(TRACEBACK_LARGE)
    # The synthetic fixture's stdout starts with "log line 0" and ends
    # (after the final filler block) with "log line 199".
    assert "log line 0" in out, "head of long output must be preserved"
    assert "log line 199" in out, "tail of long output must be preserved"


def test_truncation_error_aware_preserves_traceback():
    out = compress(TRACEBACK_LARGE)
    # Traceback and Error: lines live in the middle of the output; they
    # must be preserved by the error-aware branch.
    assert "Traceback" in out
    assert "RuntimeError: boom" in out
    assert "Error: something specific" in out


def test_truncation_actually_shortens_output():
    out = compress(TRACEBACK_LARGE)
    # The original fixture's stdout is well over 400 lines; the
    # compressed output must NOT contain every "log line N".
    missing_middle = [f"log line {i}" for i in range(50, 150)]
    present = [m for m in missing_middle if m in out]
    # Most of the deep middle should be elided.
    assert len(present) < len(missing_middle), (
        "truncation did not shorten: all middle lines still present"
    )


def test_truncation_threshold_constants_sane():
    assert TRUNCATE_THRESHOLD_LINES >= TRUNCATE_HEAD_LINES + TRUNCATE_TAIL_LINES
    assert TRUNCATE_HEAD_LINES > 0
    assert TRUNCATE_TAIL_LINES > 0


def test_truncate_output_short_passthrough():
    short = "\n".join(f"l{i}" for i in range(5))
    assert compress_module._truncate_output(short) == short


def test_truncate_output_long_no_errors_has_head_and_tail():
    long = "\n".join(f"l{i}" for i in range(TRUNCATE_THRESHOLD_LINES * 3))
    out = compress_module._truncate_output(long)
    assert "l0" in out
    assert f"l{TRUNCATE_THRESHOLD_LINES * 3 - 1}" in out
    assert "lines omitted" in out


def test_truncate_output_long_with_error_marker_preserves_it():
    total = TRUNCATE_THRESHOLD_LINES * 3
    # Put the error in the deep middle.
    lines = [f"l{i}" for i in range(total)]
    lines[total // 2] = "Traceback (most recent call last):"
    long = "\n".join(lines)
    out = compress_module._truncate_output(long)
    assert "Traceback (most recent call last):" in out


def test_error_markers_sane():
    assert "Traceback" in ERROR_MARKERS
    assert "Error:" in ERROR_MARKERS


# ---------------------------------------------------------------------------
# Turn-definition sourcing (ADR Q1)
# ---------------------------------------------------------------------------


def test_imports_turn_api_from_extractor():
    # The compress module must not redefine turn constants/functions.
    import swebench.analyze.compress as compress_mod
    import swebench.analyze.extractor as extractor_mod

    assert compress_mod.TURN_DEFINITION is extractor_mod.TURN_DEFINITION
    assert compress_mod.count_turns is extractor_mod.count_turns


def test_compress_turns_match_count_turns():
    out = compress(XARRAY_ONLYCODE)
    expected = count_turns(iter_records(XARRAY_ONLYCODE))
    assert f": {expected}" in out.splitlines()[2]  # third header line


# ---------------------------------------------------------------------------
# Purity: does not write anywhere
# ---------------------------------------------------------------------------


def test_compress_does_not_modify_input(tmp_path: Path):
    # Copy a fixture into a tmp path, compress it, and verify the bytes
    # on disk are unchanged.
    src = DJANGO_ONLYCODE.read_bytes()
    path = tmp_path / "copy.jsonl"
    path.write_bytes(src)
    _ = compress(path)
    assert path.read_bytes() == src


def test_compress_real_fixtures_all_runs():
    # Smoke: every fixture must compress without raising.
    for p in [
        DJANGO_ONLYCODE,
        DJANGO_BASELINE,
        XARRAY_ONLYCODE,
        ORPHAN_BASELINE,
        ARM_CRASH,
        TRACEBACK_LARGE,
    ]:
        out = compress(p)
        assert isinstance(out, str)
        assert out.endswith("\n")


# ---------------------------------------------------------------------------
# Tool_use formatting
# ---------------------------------------------------------------------------


def test_tool_use_without_code_input(tmp_path: Path):
    # tool_use without a `code` key — exercises the non-codebox branch.
    path = tmp_path / "tu2.jsonl"
    records = [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_read",
                        "name": "Read",
                        "input": {"file_path": "/etc/hosts"},
                    }
                ]
            },
        }
    ]
    with path.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    out = compress(path)
    assert "Read" in out
    assert "/etc/hosts" in out


def test_tool_use_with_extra_input_keys(tmp_path: Path):
    # codebox-shaped `code` plus extras — exercises the other_input branch.
    path = tmp_path / "tu3.jsonl"
    records = [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_extra",
                        "name": "mcp__codebox__execute_code",
                        "input": {
                            "language": "python",
                            "code": "print(1)",
                            "timeout": 30,
                        },
                    }
                ]
            },
        }
    ]
    with path.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    out = compress(path)
    assert "other_input" in out
    assert "timeout" in out


def test_tool_use_non_dict_input(tmp_path: Path):
    path = tmp_path / "tu4.jsonl"
    records = [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_weird",
                        "name": "WeirdTool",
                        "input": "not-a-dict",
                    }
                ]
            },
        }
    ]
    with path.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    out = compress(path)
    assert "WeirdTool" in out
    assert "not-a-dict" in out


def test_unknown_assistant_block_type(tmp_path: Path):
    path = tmp_path / "weird.jsonl"
    records = [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "mystery", "payload": "abc-UNIQUE-PAYLOAD"}
                ]
            },
        }
    ]
    with path.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    out = compress(path)
    assert "mystery" in out
    assert "abc-UNIQUE-PAYLOAD" in out


def test_user_string_content(tmp_path: Path):
    path = tmp_path / "ustr.jsonl"
    records = [
        {"type": "user", "message": {"content": "bare user string ZZZ"}},
    ]
    with path.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    out = compress(path)
    assert "bare user string ZZZ" in out


def test_user_unknown_block_and_string_in_list(tmp_path: Path):
    path = tmp_path / "umix.jsonl"
    records = [
        {
            "type": "user",
            "message": {
                "content": [
                    "inline-string-UNIQUE-QQ",
                    {"type": "weird_block", "x": "XVAL-UNIQUE"},
                ]
            },
        },
    ]
    with path.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    out = compress(path)
    assert "inline-string-UNIQUE-QQ" in out
    assert "XVAL-UNIQUE" in out


def test_unknown_record_type(tmp_path: Path):
    path = tmp_path / "unknown.jsonl"
    records = [{"type": "something_else", "marker": "UNK-MARKER-42"}]
    with path.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    out = compress(path)
    assert "something_else" in out
    assert "UNK-MARKER-42" in out


def test_tool_result_content_is_plain_string(tmp_path: Path):
    path = tmp_path / "plainstr.jsonl"
    records = [
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_s",
                        "content": "direct-string-UNIQUE-77",
                    }
                ]
            },
        }
    ]
    with path.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    out = compress(path)
    assert "direct-string-UNIQUE-77" in out


def test_tool_result_content_list_of_strings(tmp_path: Path):
    path = tmp_path / "liststr.jsonl"
    records = [
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_ls",
                        "content": ["str-A-UNIQUE", "str-B-UNIQUE"],
                    }
                ]
            },
        }
    ]
    with path.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    out = compress(path)
    assert "str-A-UNIQUE" in out
    assert "str-B-UNIQUE" in out


def test_tool_result_content_none(tmp_path: Path):
    path = tmp_path / "none.jsonl"
    records = [
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_none",
                        "content": None,
                    }
                ]
            },
        }
    ]
    with path.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    out = compress(path)
    assert "toolu_none" in out


def test_tool_result_codebox_empty_stdout_stderr(tmp_path: Path):
    path = tmp_path / "empty.jsonl"
    payload = json.dumps({"stdout": "", "stderr": "", "exit_code": 0})
    records = [
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_e",
                        "content": [{"type": "text", "text": payload}],
                    }
                ]
            },
        }
    ]
    with path.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    out = compress(path)
    assert "stdout: <empty>" in out
    assert "stderr: <empty>" in out


def test_tool_result_scalar_content(tmp_path: Path):
    path = tmp_path / "scalar.jsonl"
    records = [
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_sc",
                        "content": 42,
                    }
                ]
            },
        }
    ]
    with path.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    out = compress(path)
    assert "42" in out


def test_tool_result_list_with_non_text_dict(tmp_path: Path):
    path = tmp_path / "nontext.jsonl"
    records = [
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_nt",
                        "content": [
                            {"type": "image", "marker": "IMG-UNIQUE-99"},
                            42,
                        ],
                    }
                ]
            },
        }
    ]
    with path.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    out = compress(path)
    assert "IMG-UNIQUE-99" in out
    assert "42" in out


def test_thinking_without_signature(tmp_path: Path):
    path = tmp_path / "nosig.jsonl"
    records = [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "thinking", "thinking": "no-sig-thought-UNIQUE"}
                ]
            },
        }
    ]
    with path.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    out = compress(path)
    assert "no-sig-thought-UNIQUE" in out
    # No "signature: " line should appear.
    assert "signature:" not in out


def test_non_dict_assistant_block_skipped(tmp_path: Path):
    path = tmp_path / "nd.jsonl"
    records = [
        {
            "type": "assistant",
            "message": {
                "content": [
                    "raw-string-block-UNIQUE",
                    {"type": "text", "text": "real-text-UNIQUE"},
                ]
            },
        }
    ]
    with path.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    out = compress(path)
    # The bare-string block should be skipped (non-dict path).
    assert "raw-string-block-UNIQUE" not in out
    assert "real-text-UNIQUE" in out


def test_tool_use_code_is_rendered(tmp_path: Path):
    path = tmp_path / "tu.jsonl"
    code = "print('hello from codebox')"
    records = [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_xyz",
                        "name": "mcp__codebox__execute_code",
                        "input": {"language": "python", "code": code},
                    }
                ]
            },
        }
    ]
    with path.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    out = compress(path)
    assert code in out
    assert "language: python" in out
    assert "toolu_xyz" in out
