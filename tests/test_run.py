"""Unit tests for swebench.run.

Only the offline helpers are covered here. End-to-end CLI behaviour is
exercised by the larger integration suites — this file intentionally stays
fast and hermetic (no subprocess, no network, no real repos).
"""

from __future__ import annotations

import pytest

from swebench.run import _is_triple_complete, _parse_filter_ids, run_command


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


# --- runtime backend default (image-only, ADR-0004 / #314) ------------------

def test_runtime_defaults_to_image():
    """Image is the default/supported backend (100% Verified image coverage);
    overlay is the deprecated legacy fallback (#320)."""
    opt = next(p for p in run_command.params if p.name == "runtime")
    assert opt.default == "image"
    # image listed first; overlay retained but deprecated.
    assert list(opt.type.choices) == ["image", "overlay"]


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


# --- _parse_filter_ids (#299: comma list OR @file) --------------------------


def test_parse_filter_ids_comma_list():
    """Comma-separated form splits and strips whitespace."""
    assert _parse_filter_ids("a__b-1, c__d-2 ,e__f-3") == {
        "a__b-1",
        "c__d-2",
        "e__f-3",
    }


def test_parse_filter_ids_comma_list_drops_empties():
    """Trailing/duplicate commas don't produce empty IDs."""
    assert _parse_filter_ids("a__b-1,,c__d-2,") == {"a__b-1", "c__d-2"}


def test_parse_filter_ids_at_file(tmp_path):
    """@file reads newline-delimited IDs, ignoring blanks and comments."""
    ids_file = tmp_path / "ids.txt"
    ids_file.write_text(
        "# buildable Verified subset\n"
        "django__django-11790\n"
        "\n"
        "sphinx-doc__sphinx-7985   # flaky once, kept\n"
        "   \n"
        "scikit-learn__scikit-learn-13496\n"
    )
    assert _parse_filter_ids(f"@{ids_file}") == {
        "django__django-11790",
        "sphinx-doc__sphinx-7985",
        "scikit-learn__scikit-learn-13496",
    }


def test_parse_filter_ids_at_file_missing(tmp_path):
    """A missing @file path is a clean CLI error, not a traceback."""
    with pytest.raises(SystemExit):
        _parse_filter_ids(f"@{tmp_path / 'nope.txt'}")


def test_parse_filter_ids_at_file_empty(tmp_path):
    """An @file with only comments/blanks yields no IDs → CLI error."""
    ids_file = tmp_path / "empty.txt"
    ids_file.write_text("# only a comment\n\n   \n")
    with pytest.raises(SystemExit):
        _parse_filter_ids(f"@{ids_file}")
