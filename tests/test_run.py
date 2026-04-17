"""Unit tests for swebench.run.

Only the offline helpers are covered here. End-to-end CLI behaviour is
exercised by the larger integration suites — this file intentionally stays
fast and hermetic (no subprocess, no network, no real repos).
"""

from __future__ import annotations

from swebench.run import _is_triple_complete


INSTANCE = "django__django-16379"
ARM = "baseline"
RUN_IDX = 1


def _write(path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _paths(tmp_path):
    jsonl = tmp_path / f"{INSTANCE}_{ARM}_run{RUN_IDX}.jsonl"
    test_txt = tmp_path / f"{INSTANCE}_{ARM}_run{RUN_IDX}_test.txt"
    return jsonl, test_txt


# --- missing files ----------------------------------------------------------


def test_is_triple_complete_missing_jsonl(tmp_path):
    """Test file has a verdict but the jsonl is absent → incomplete."""
    _, test_txt = _paths(tmp_path)
    _write(test_txt, "PASS\n")

    assert _is_triple_complete(tmp_path, INSTANCE, ARM, RUN_IDX) is None


def test_is_triple_complete_missing_test_file(tmp_path):
    """jsonl exists but the test file is absent → incomplete."""
    jsonl, _ = _paths(tmp_path)
    _write(jsonl, '{"foo": "bar"}\n')

    assert _is_triple_complete(tmp_path, INSTANCE, ARM, RUN_IDX) is None


def test_is_triple_complete_both_missing(tmp_path):
    """Neither file exists → incomplete."""
    assert _is_triple_complete(tmp_path, INSTANCE, ARM, RUN_IDX) is None


# --- verdict parsing --------------------------------------------------------


def test_is_triple_complete_no_verdict(tmp_path):
    """Both files present, but the test file has no PASS/FAIL line → incomplete."""
    jsonl, test_txt = _paths(tmp_path)
    _write(jsonl, '{"foo": "bar"}\n')
    _write(test_txt, "ran 12 tests\nsome warnings\n")

    assert _is_triple_complete(tmp_path, INSTANCE, ARM, RUN_IDX) is None


def test_is_triple_complete_pass_verdict(tmp_path):
    """Last non-empty line is PASS → complete (returns 'PASS')."""
    jsonl, test_txt = _paths(tmp_path)
    _write(jsonl, '{"foo": "bar"}\n')
    _write(test_txt, "ran 12 tests\nPASS\n")

    assert _is_triple_complete(tmp_path, INSTANCE, ARM, RUN_IDX) == "PASS"


def test_is_triple_complete_fail_verdict(tmp_path):
    """Last non-empty line is FAIL → complete (returns 'FAIL')."""
    jsonl, test_txt = _paths(tmp_path)
    _write(jsonl, '{"foo": "bar"}\n')
    _write(test_txt, "ran 12 tests\nFAIL\n")

    assert _is_triple_complete(tmp_path, INSTANCE, ARM, RUN_IDX) == "FAIL"


def test_is_triple_complete_trailing_blank_lines(tmp_path):
    """Verdict followed by blank lines still counts — we take the last *non-empty* line."""
    jsonl, test_txt = _paths(tmp_path)
    _write(jsonl, '{"foo": "bar"}\n')
    _write(test_txt, "ran 12 tests\nPASS\n\n\n   \n")

    assert _is_triple_complete(tmp_path, INSTANCE, ARM, RUN_IDX) == "PASS"


def test_is_triple_complete_mixed_content_noise_after(tmp_path):
    """PASS appears mid-file but trailing non-empty noise wins → incomplete."""
    jsonl, test_txt = _paths(tmp_path)
    _write(jsonl, '{"foo": "bar"}\n')
    # 'PASS' is somewhere in the middle, but the last non-empty line is
    # unrelated — that is what --resume must treat as incomplete, so the
    # triple gets re-run.
    _write(test_txt, "ran 12 tests\nPASS\ntraceback follows\nsome error\n")

    assert _is_triple_complete(tmp_path, INSTANCE, ARM, RUN_IDX) is None


def test_is_triple_complete_empty_test_file(tmp_path):
    """Empty test file → incomplete (killed mid-run before first write)."""
    jsonl, test_txt = _paths(tmp_path)
    _write(jsonl, '{"foo": "bar"}\n')
    _write(test_txt, "")

    assert _is_triple_complete(tmp_path, INSTANCE, ARM, RUN_IDX) is None


def test_is_triple_complete_whitespace_only_test_file(tmp_path):
    """Test file with only whitespace/blank lines → incomplete."""
    jsonl, test_txt = _paths(tmp_path)
    _write(jsonl, '{"foo": "bar"}\n')
    _write(test_txt, "\n\n   \n")

    assert _is_triple_complete(tmp_path, INSTANCE, ARM, RUN_IDX) is None


def test_is_triple_complete_pass_without_trailing_newline(tmp_path):
    """Test file that ends with 'PASS' (no trailing newline) → complete."""
    jsonl, test_txt = _paths(tmp_path)
    _write(jsonl, '{"foo": "bar"}\n')
    _write(test_txt, "ran 12 tests\nPASS")

    assert _is_triple_complete(tmp_path, INSTANCE, ARM, RUN_IDX) == "PASS"


def test_is_triple_complete_accepts_path_object(tmp_path):
    """Helper should accept both str and Path objects for results_dir."""
    jsonl, test_txt = _paths(tmp_path)
    _write(jsonl, '{"foo": "bar"}\n')
    _write(test_txt, "PASS\n")

    # Path object
    assert _is_triple_complete(tmp_path, INSTANCE, ARM, RUN_IDX) == "PASS"
    # str form
    assert _is_triple_complete(str(tmp_path), INSTANCE, ARM, RUN_IDX) == "PASS"
