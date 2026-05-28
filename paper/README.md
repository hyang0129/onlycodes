# onlycodes Paper Build System

Every number and every figure in the paper traces back to a single CSV cell.
When an experiment re-runs and its CSV regenerates, `make paper` picks up new
values automatically. **A stale value is a build failure, not a proofreading
task.**

Adapted from the hallulens paper build system (see [`hyang0129/hallulens/paper/`](https://github.com/hyang0129/hallulens/tree/main/paper)). Macro namespace prefix is `oc@` (onlycodes) instead of `hl@` (hallulens); otherwise identical contracts.

## Quick start

```bash
cd paper/
make deps         # first-time only: pip install pandas, numpy, scipy, matplotlib
make paper        # renders figures, builds values.tex, lints, compiles PDF
make figures      # render figures_src/*.py only
make values       # build generated/values.tex from data/ + sidecar CSVs
make lint         # check prose for bare digits outside citation macros
make clean        # remove generated/ and LaTeX byproducts
```

LaTeX (`latexmk`) is required for `make paper`. All other targets need only
Python 3.11+ and the packages pinned in [requirements.txt](requirements.txt)
(pandas, numpy, scipy, matplotlib).

If your system Python lacks these packages, `make figures` / `values` / `paper`
will fail fast with a pointer to `make deps`. To use a non-system Python
(e.g. a project venv), pass `PYTHON=` on the make command line, for example:

```bash
make PYTHON=/workspaces/.venvs/tts_server/bin/python paper
```

---

## Submission target: Agentic Software Engineering (SE 3.0) Workshop at KDD 2026

- **Workshop CFP:** https://agent-se.github.io/
- **Submission deadline:** 2026-06-01 AOE
- **Workshop dates:** August 2026, ICC Jeju, Korea (alongside KDD 2026)
- **Page limit:** **8 pages excl. references** (long paper); 4 pages for short/position. ACM KDD template.
- **Page target:** ~7.5 pages (see [`outline.md`](outline.md)). 8 is the ceiling — slack absorbs the 1-page haircut from the prior 9-page target but no further ceiling room remains.
- **Required template line:** `\documentclass[sigconf,anonymous,review]{acmart}` (the `review` option is mandated by the SE 3.0 CFP).
- **Double-blind:** yes — anonymize before submission.
- **Archival:** non-archival, no formal proceedings — does not preclude later journal/main-conference submission.

**Venue switch (2026-05-27):** moved from the KDD Eval & Trustworthiness workshop to SE 3.0 (same conference, same June 1 deadline, same ACM template family, both non-archival). SE 3.0 directly lists "Agent Tool Use & Environments", "Failure Modes & Root Causes", "Economic Cost & Impact", and "Trustworthiness & Reliability" among its tracks — four direct topic hits versus one ("Agent-centric benchmarks") for the prior venue. Reviewer pool is coding-agent researchers rather than monitoring/governance. The cost is one page off the ceiling (9 → 8); §3.3/§3.5/§3.6 minima are unchanged. See issue #158 comment thread for the full comparison.

`main.tex` declares `\documentclass[sigconf,anonymous,review]{acmart}` — `anonymous` and `review` both stay on through submission. Drop `anonymous` (and optionally `review`) for the camera-ready.

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

When using an LLM agent (Claude Code etc.) to draft or edit the paper, the agent is restricted to files inside `paper/` (per the top-level [CLAUDE.md](../CLAUDE.md)). Stale framing from `docs/ROADMAP.md` or the README's "Code Mode" pitch is **not allowed** to leak into the draft. The paper's current framing (as of 2026-05-28) is the **four-cell cost structure** across (regime, agent) pairs — `code_only` is cheaper or tied in 3 of 4 cells, with the lone exception (SWE-bench/Claude +14%) NS at p=0.12; see [05_results.md](05_results.md) §5.1 framing-change note. Do not reintroduce: (a) the "code mode wins" narrative from `docs/ROADMAP.md`, or (b) the earlier "regime-dependent sign-flip" framing this paper itself used pre-2026-05-28 (retired because it dramatised a non-significant directional point estimate).

`paper/references.bib` is never edited by an agent — citations are proposed in outline files for human review first.
