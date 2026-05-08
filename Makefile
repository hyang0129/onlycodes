# Top-level Makefile for the onlycodes repo.
#
# These targets are convenience wrappers around the Python tooling under
# tools/ and tests/. They are intended for local developer use and for CI
# (.github/workflows/check-graders.yml).

PYTHON ?= python3

.PHONY: help check-graders check-graders-positive check-graders-negative \
        check-graders-leaks check-graders-fast test

help:
	@echo "Available targets:"
	@echo "  make check-graders            run positive + negative + leak gates on every task"
	@echo "  make check-graders-positive   run only the positive sanity check (verify_graders.py)"
	@echo "  make check-graders-negative   run only the negative sanity check (check_grader_negative.py)"
	@echo "  make check-graders-leaks      run only the answer-leak lint (check_grader_leaks.py)"
	@echo "  make check-graders-fast       run negative gate ONLY for tasks that ship grader/negative_cases.py"
	@echo "  make test                     run pytest"

# ---------------------------------------------------------------------------
# Grader pre-merge sanity gates.
#
# A task PR must pass:
#   1. The positive check (reference output → grader returns passed=True).
#      Catches graders that reject their own known-good answer.
#   2. The negative check (deliberately wrong artifacts → grader returns
#      passed=False). Catches graders that ACCEPT artifacts they shouldn't.
#   3. The answer-leak lint (no embedded reference values in detail strings).
#
# All three are individually invokable; ``check-graders`` is the umbrella
# target the CI workflow uses.
# ---------------------------------------------------------------------------

check-graders: check-graders-positive check-graders-negative check-graders-leaks
	@echo ""
	@echo "All grader gates passed."

check-graders-positive:
	$(PYTHON) tools/verify_graders.py

check-graders-negative:
	$(PYTHON) tools/check_grader_negative.py

check-graders-leaks:
	$(PYTHON) tools/check_grader_leaks.py

# A faster lane for PRs that only add or modify a single task: skip the
# default-mutation pass for unrelated tasks and only exercise tasks that
# ship a per-task grader/negative_cases.py.
check-graders-fast:
	$(PYTHON) tools/check_grader_negative.py --tasks-with-custom-cases-only

test:
	$(PYTHON) -m pytest tests/
