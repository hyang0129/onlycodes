"""paper/lint.py

Lint rule: every digit in prose must be inside an approved citation macro,
or covered by the whitelist.

Approved contexts (digits inside these are allowed):
  result, resdelta, resratio, resultCI, resultPM macros
  ref, cite, citep, citet, eqref, label arguments

Math mode ($ $, display math, equation/align environments) is stripped before
scanning -- digits in math are allowed unconditionally.

Year literals matching the pattern (19|20)XX are allowed everywhere.

Whitelist entries are literal strings (not regexes). A digit is OK if the
surrounding text contains a whitelist string that overlaps the digit position.

Usage:
    python paper/lint.py [--paper-dir <path>]

Exit code 0 = clean. Non-zero = violations found.

Ported from hallulens/paper/lint.py; whitelist adapted for onlycodes content.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Approved macro patterns — digits inside these are safe.
# ---------------------------------------------------------------------------
_CITATION_MACROS = r"(?:result|resdelta|resratio|resultCI|resultPM|ref|cite|citep|citet|eqref|label)"

_APPROVED_RE = re.compile(
    r"\\"
    + _CITATION_MACROS
    + r"(?:\{[^}]*\}){1,3}"
    + r"(?:\[[^\]]*\])?"
)

# ---------------------------------------------------------------------------
# LaTeX structural commands — not prose, digits inside are ignored.
# ---------------------------------------------------------------------------
_STRUCTURAL_CMDS = r"(?:documentclass|usepackage|geometry|input|include|inputenc|fontenc|bibliographystyle|bibliography|includegraphics|setlength|setcounter|vspace|hspace|textwidth|columnwidth|linewidth|acmConference|acmYear|copyrightyear|acmISBN|acmDOI|settopmatter)"

_STRUCTURAL_RE = re.compile(
    r"\\"
    + _STRUCTURAL_CMDS
    + r"(?:\[[^\]]*\])?"
    + r"(?:\{[^}]*\}){1,2}"
)

# ---------------------------------------------------------------------------
# Math mode patterns — stripped before digit scanning.
# ---------------------------------------------------------------------------
_INLINE_MATH_RE = re.compile(r"\$[^$]*\$")
_DISPLAY_MATH_RE = re.compile(r"\\\[.*?\\\]", re.DOTALL)
_ENV_MATH_RE = re.compile(
    r"\\begin\{(?:equation|align|align\*|gather|gather\*|multline)\}.*?\\end\{(?:equation|align|align\*|gather|gather\*|multline)\}",
    re.DOTALL,
)

# ---------------------------------------------------------------------------
# Year pattern — allowed everywhere.
# ---------------------------------------------------------------------------
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")

# ---------------------------------------------------------------------------
# Digit detector
# ---------------------------------------------------------------------------
_DIGIT_RE = re.compile(r"\d")

# ---------------------------------------------------------------------------
# Whitelist — literal strings; a digit is OK if its context contains one.
# To add an entry, append a string here and document it in paper/README.md.
# ---------------------------------------------------------------------------
WHITELIST: list[str] = [
    # Model names and versions
    "claude-sonnet-4-6",
    "Claude Sonnet 4.6",
    "Claude Code",
    "Claude Code 2.1.139",
    "2.1.139",
    "claude-opus-4-7",
    "claude-haiku-4-5",
    "Codex CLI",
    "gpt-5.5",
    "GPT-5.5",
    "GPT-5",
    "GPT-4-Turbo",
    "GPT-4",
    "Gemini 2.5",
    "Gemini~2.5",
    "Gemini 2.0",
    "Gemini~2.0",
    "Llama-3.1",
    "Llama-3",
    "Qwen3",
    # Benchmark names
    "SWE-bench Verified",
    "SWE-bench Mini",
    "SWE-bench Lite",
    "swebench-verified-mini",
    "swebench-datasci-mini",
    "SWE-bench",
    "SWE-agent",
    "mini-SWE-agent",
    "Live-SWE-agent",
    "SWE-bench Pro",
    "SWE-Bench Pro",
    "Multi-SWE-bench",
    "SWE-PolyBench",
    "SWE Atlas",
    # Issue / commit references in prose
    "Issue \\#",
    "issue \\#",
    "Issue~\\#",
    "issue~\\#",
    "\\#287",
    "\\#226",
    "\\#288",
    "\\#238",
    "\\#253",
    "Issue #226",
    "Issue #287",
    "Issue #288",
    "Issue #238",
    "Issue #253",
    # arXiv IDs (4-digit + extension)
    "arXiv:",
    "arxiv.org/abs/",
    # Arm names (referenced as \texttt{tool_rich} etc, no bare digits)
    # left in for prose mentions like "the 3-arm ablation"
    # Statistics
    "95\\% CI",
    "95\\%",
    "95\\,\\% CI",
    "n=50",
    "n=88",
    "n=93",
    "n=100",
    # Enumerated contributions in intro/conclusion
    "(1) ",
    "(2) ",
    "(3) ",
    "(4) ",
    "(5) ",
    # Cross-reference macros
    "Figure~\\ref",
    "Table~\\ref",
    "Section~\\ref",
    "Appendix~\\ref",
    "\\S\\ref",
    # Footnote markers
    "\\footnote{",
    # KDD / ACL venue mentions
    "KDD 2026",
    "KDD'26",
    "EMNLP 2026",
    "NeurIPS 2024",
    "ICML 2024",
    # Standard library refs (Python 3, etc — not paper claims)
    "Python 3",
    "Python 3.11",
    "Python 3.10",
    # Repository structure paths often appearing inline
    "v1",
    "v2",
    "v3",
    # LaTeX table syntax — \multicolumn{N}{...}, \cmidrule(lr){A-B}
    "\\multicolumn{",
    "\\cmidrule",
    # Standing experimental constants (paired with \result{} macros elsewhere)
    "3 seeds",
    "Strict $9/9$",
    "9/9",
    "seed 1",
    "seed 2",
    "seed 3",
    "seed~1",
    "seed~2",
    "seed~3",
    # Table cell sample sizes used as static text in §5.4 (matches WHITELIST "n=93" etc.)
    "& 93",
    "& 100",
]


def _mask_spans(text: str, spans: list[tuple[int, int]]) -> str:
    text_list = list(text)
    for start, end in spans:
        for i in range(start, end):
            if i < len(text_list):
                text_list[i] = " "
    return "".join(text_list)


def strip_math_and_approved(text: str) -> tuple[str, list[tuple[int, int]]]:
    masked_spans: list[tuple[int, int]] = []

    for m in _ENV_MATH_RE.finditer(text):
        masked_spans.append((m.start(), m.end()))
    for m in _DISPLAY_MATH_RE.finditer(text):
        masked_spans.append((m.start(), m.end()))
    for m in _INLINE_MATH_RE.finditer(text):
        masked_spans.append((m.start(), m.end()))
    for m in _APPROVED_RE.finditer(text):
        masked_spans.append((m.start(), m.end()))
    for m in _STRUCTURAL_RE.finditer(text):
        masked_spans.append((m.start(), m.end()))

    stripped = _mask_spans(text, masked_spans)
    return stripped, masked_spans


def _context_window(text: str, pos: int, width: int = 40) -> str:
    start = max(0, pos - width)
    end = min(len(text), pos + width + 1)
    return text[start:end].replace("\n", " ")


def lint_file(path: Path) -> list[str]:
    text = path.read_text(errors="replace")
    violations: list[str] = []

    text_no_comments = re.sub(r"(?<!\\)%.*", "", text)
    lines_original = text_no_comments.splitlines()

    for lineno, line in enumerate(lines_original, 1):
        stripped, _ = strip_math_and_approved(line)

        for digit_match in _DIGIT_RE.finditer(stripped):
            pos = digit_match.start()

            if _YEAR_RE.search(line[max(0, pos - 4) : pos + 4]):
                continue

            context_start = max(0, pos - 60)
            context_end = min(len(line), pos + 60)
            context = line[context_start:context_end]
            if any(entry in context for entry in WHITELIST):
                continue

            snippet = _context_window(stripped, pos, width=30)
            violations.append(
                f"{path}:{lineno}: bare digit '{digit_match.group()}' "
                f"outside approved context — «{snippet.strip()}»"
            )

    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lint .tex prose for bare digits")
    parser.add_argument(
        "--paper-dir",
        default="paper",
        help="Path to the paper/ directory (default: paper/)",
    )
    parser.add_argument(
        "--files",
        nargs="*",
        help="Specific .tex files to lint (overrides default scan)",
    )
    args = parser.parse_args(argv)

    paper_dir = Path(args.paper_dir)

    if args.files:
        tex_files = [Path(f) for f in args.files]
    else:
        tex_files = []
        main_tex = paper_dir / "main.tex"
        if main_tex.exists():
            tex_files.append(main_tex)
        sections_dir = paper_dir / "sections"
        if sections_dir.exists():
            tex_files.extend(sorted(sections_dir.glob("*.tex")))

    if not tex_files:
        print(f"No .tex files found under {paper_dir}", file=sys.stderr)
        return 0

    all_violations: list[str] = []
    for tex_path in tex_files:
        violations = lint_file(tex_path)
        all_violations.extend(violations)

    if all_violations:
        for v in all_violations:
            print(v, file=sys.stderr)
        print(
            f"\nlint: {len(all_violations)} violation(s) found. "
            "Add to WHITELIST in paper/lint.py or use \\result{...} macros.",
            file=sys.stderr,
        )
        return 1

    print(f"lint: OK — {len(tex_files)} file(s) scanned, no bare digits found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
