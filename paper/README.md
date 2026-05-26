# onlycodes Paper Build System

Every number and every figure in the paper traces back to a single CSV cell.
When an experiment re-runs and its CSV regenerates, `make paper` picks up new
values automatically. **A stale value is a build failure, not a proofreading
task.**

Adapted from the hallulens paper build system (see [`hyang0129/hallulens/paper/`](https://github.com/hyang0129/hallulens/tree/main/paper)). Macro namespace prefix is `oc@` (onlycodes) instead of `hl@` (hallulens); otherwise identical contracts.

## Quick start

```bash
cd paper/
make paper        # renders figures, builds values.tex, lints, compiles PDF
make figures      # render figures_src/*.py only
make values       # build generated/values.tex from data/ + sidecar CSVs
make lint         # check prose for bare digits outside citation macros
make clean        # remove generated/ and LaTeX byproducts
```

LaTeX (`latexmk`) is required for `make paper`. All other targets need only
Python 3.11+ + pandas + matplotlib.

---

## Submission target: KDD 2026 Workshop on Evaluation and Trustworthiness of Agentic AI

- **Workshop CFP:** https://kdd-eval-workshop.github.io/agenticai-evaluation-kdd2026/
- **Submission deadline:** 2026-06-01 AOE
- **Notification:** 2026-07-01
- **Camera-ready:** 2026-07-10
- **Workshop dates:** 2026-08-09 or 08-10, ICC Jeju, Korea
- **Page limit:** 9 pages excl. references, ACM Conference Proceeding template
- **Page target:** ~7.5 pages (see [`outline.md`](outline.md#page-budget-target-75-pages-not-9)). 9 is the ceiling, not the goal — dense > stuffed.
- **Submission portal:** [OpenReview](https://openreview.net/group?id=KDD.org/2026/Workshop/Agentic_AI_Evaluation_and_Trustworthiness)
- **Anonymous review:** yes
- **Archival:** posted on workshop website only — not in KDD proceedings (does not preclude later journal/main-conference submission)

`main.tex` declares `\documentclass[sigconf, anonymous]{acmart}` — anonymous mode adds the placeholder authorship for blind review. Drop the `anonymous` option for the camera-ready.

### LaTeX dependencies

`make paper` requires the ACM template (`acmart.cls`) and a TeX Live installation with the standard set of packages plus `xfp` (for `\fpeval`) and `siunitx` (for `\num`):

```bash
sudo apt-get install -y --no-install-recommends \
    texlive-latex-base texlive-latex-recommended texlive-latex-extra \
    texlive-fonts-extra texlive-science texlive-publishers latexmk
```

Download `acmart.cls` (and the bibliography style files `ACM-Reference-Format.bst` etc.) from https://www.acm.org/publications/proceedings-template and place alongside `main.tex` before building.

---

## Citation macros

All macros are defined in `paper/macros.tex`. Values resolve at LaTeX build
time from `paper/generated/values.tex` (produced by `build_numbers.py`).

### `\result{csv}{key}[p]`

Look up one cell and render it with `p` decimal places.

```latex
The \texttt{tool\_rich} arm achieves a pass rate of
\result{headline}{modification:tool_rich:pass_rate}[2}
on the modification regime.
```

- `csv` is the stem of a file in `paper/data/` (e.g. `headline` for
  `headline.csv`) or `fig.<name>` for a figure sidecar.
- `key` is a colon-joined coordinate per the CSV's `key_schema` plus the
  column name (e.g. `modification:tool_rich:total_cost_usd`).
- `[p]` is the number of decimal places (optional; default from CSV header).

### `\resdelta{csv}{key_a}{key_b}[p]`

Compute `key_a - key_b` at build time via `\fpeval`. Renders with explicit sign.

```latex
a cost delta of \resdelta{headline}{modification:code_only:total_cost_usd}{modification:tool_rich:total_cost_usd}[2] USD.
```

### `\resratio{csv}{key_a}{key_b}[p]`

Compute `key_a / key_b` at build time. Used for cost ratios across arms or regimes.

```latex
\texttt{code\_only} is \resratio{headline}{computation:code_only:median_cost_usd}{computation:tool_rich:median_cost_usd}[2] of the \texttt{tool\_rich} cost on computation tasks.
```

### `\resultCI{csv}{mean_key,lo_key,hi_key}[p]`

Render as `mean [lo, hi]`. Three keys comma-separated in one brace group.

### `\resultPM{csv}{mean_key,err_key}[p]`

Render as `mean ± err`. Two keys comma-separated.

---

## CSV provenance header

Every CSV in `paper/data/` must start with this header block (read by `build_numbers.py`):

```
# source_commit: <sha>
# generated: <ISO timestamp>
# generator: <script name or "hand-built — <reason>">
# key_schema: col1:col2:col3   # colon-separated row-key columns
# default_precision: 3         # optional, falls back to 3
```

`build_numbers.py` checks `source_commit` is an ancestor of HEAD and warns if not — catches CSVs generated off a stale branch.

`key_schema` defines which columns form the row key; remaining columns are values. A row with `key_schema = regime:arm:metric` and value column `value` produces the key `<regime>:<arm>:<metric>:value`.

---

## Lint rules

`make lint` runs `paper/lint.py`, which flags any bare digit in `.tex` prose that isn't inside an approved macro (`\result`, `\resdelta`, `\resratio`, `\resultCI`, `\resultPM`, `\cite`, `\ref`, etc.) and isn't a year or whitelisted string.

To add a whitelist entry: edit `WHITELIST` in `paper/lint.py` with a literal string that overlaps the digit position, and document the entry in this README.

Current whitelist entries (non-exhaustive): model names (`Claude Sonnet 4.6`, `Codex CLI`, `gpt-5.5`, ...), benchmark names (`SWE-bench`, `SWE-agent`, ...), issue references (`Issue #287`), instance counts (`n=88`, `n=93`, `n=100`), enumeration markers (`(1) `, `(2) `, ...), and statistical phrases (`95% CI`).

---

## File map

| Path | Purpose |
|---|---|
| `outline.md` | Master paper skeleton with section budgets |
| `figures_outline.md` | Figure prioritization + production order |
| `00_abstract.md` through `99_limitations.md` | Per-section detailed outlines (planning docs, not compiled) |
| `sections/00_abstract.tex` through `sections/99_limitations.tex` | Final LaTeX prose (compiled via `\input`) |
| `main.tex` | LaTeX entry point — ACM template |
| `macros.tex` | `\result`, `\resdelta`, etc. macro definitions |
| `references.bib` | Bibliography (humans only — agents must propose entries via outline files first) |
| `build_numbers.py` | CSV → `values.tex` generator |
| `lint.py` | Digit-in-citation enforcement |
| `Makefile` | Build orchestration |
| `data/*.csv` | Hand-built or experiment-derived CSVs with provenance headers |
| `figures_src/*.py` | Figure rendering scripts; each emits PDF + `*.numbers.csv` sidecar |
| `generated/` | Build outputs — `values.tex`, `provenance.txt`, `figures/*.pdf` |

---

## CLAUDE.md guardrail

When using an LLM agent (Claude Code etc.) to draft or edit the paper, the agent is restricted to files inside `paper/` (per the top-level [CLAUDE.md](../CLAUDE.md)). Stale framing from `docs/ROADMAP.md` or the README's "Code Mode" pitch is **not allowed** to leak into the draft. The regime-dependent sign-flip framing in this paper supersedes the "code mode wins" narrative; do not reintroduce the old framing from external docs.

`paper/references.bib` is never edited by an agent — citations are proposed in outline files for human review first.
