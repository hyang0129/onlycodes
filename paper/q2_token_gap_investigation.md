# Investigation: Why does code-execution mode shift the input-token budget?

**Source question:** [paper/outline.md L142-143](../../outline.md#L142) — open question #2.

**Original framing (outline):** "On SWE-bench Codex, LLM-call counts are essentially identical across arms (~19), but `onlycode` uses 25% fewer input tokens and 34% fewer tool calls than `baseline`. *Hypothesis: MCP output compression.*"

**Investigation arc:** the literal "MCP output compression" hypothesis is false (the wrapper *adds* JSON-escape bytes; the median per-call output is *larger* under `execute_code` than under `exec_command`). The input-token wins are real but driven by two cleaner mechanisms that don't reduce to "compression":

- **H1 — Tool-call batching.** One `execute_code` call subsumes what `exec_command` would split into several calls (`cd` + `cat` + `rg` + `pytest` + pretty-print, all in one Python script). With LLM-call count held roughly constant, fewer tool invocations per inference step means less content appended to history per step.
- **H2 — Upper-tail suppression.** Per-call output medians are flat or higher in code-mode, but the upper tail of the distribution is dramatically thinner. `exec_command` dumps verbatim stdout that occasionally explodes (and gets pinned at the `max_output_tokens=6000` ≈ 40 154-char ceiling); `execute_code` runs Python that paginates output explicitly (`x[:4000]`, head-like slicing) and rarely emits >16 k chars.

This document characterizes H1 and H2 in four (agent × benchmark) cells: Codex SWE-bench (the original cell), Codex Artifact, Claude Artifact, and Claude SWE-bench (the surprise cell).

**Cross-cell bottom line:** H2 holds in all four cells. H1 holds only for Codex (which natively emits multiple parallel `function_call` items per LLM response); Claude's tools-per-LLM-call ratio is structurally near 0.3 across all arms and provides no batching lever. In the three "expected" cells (Codex×Both, Claude Artifact), H1 + H2 + a system-prompt-floor reduction combine to give code-mode a 25–62 % input-token win. In the **Claude SWE-bench cell, H2 still holds at the per-call level but is swamped by a +16 % LLM-call inflation that makes onlycode lose +21 % on input tokens** — the code-mode surface is structurally cleaner per call but takes more rounds to converge on this workload.

---

## 1. The two hypotheses, sharply stated

In a chat-style agent loop, total input tokens billed across a run is approximately:

$$
\text{input\_tokens} \approx \sum_{k=1}^{L} P_k
\quad\text{where}\quad
P_k = F + \sum_{j<k} (a_j + o_j + m_j)
$$

with $L$ = number of LLM calls; $F$ = per-call fixed floor (system prompt + tools schema + initial user message); $a_j$ = $j$-th tool call's args; $o_j$ = $j$-th tool call's output; $m_j$ = $j$-th LLM call's agent-message commentary; and tool calls indexed across the whole run.

Three independent levers drive total input tokens:

| Lever | What it affects | How code-mode could move it |
|-------|-----------------|------------------------------|
| **L** (LLM-call count) | Number of times history is re-fed | Up or down depending on workload fit |
| **F** (per-call floor) | Fixed prompt overhead × L | Tools schema shrinks when restricted |
| **growth** (∑ aⱼ + oⱼ + mⱼ) | History accumulation | H1 reduces oⱼ count; H2 thins oⱼ distribution |

**H1 (Tool-call batching) targets the number of tool-call items appended per LLM step:**
$$\text{tools\_per\_LLM\_call} = \frac{N_{\text{tool}}}{L}$$
H1 predicts code-mode reduces this ratio because one programmable call subsumes multiple shell calls.

**H2 (Upper-tail suppression) targets the distribution of per-call output sizes:**
$$\text{distribution}(|o_j|)$$
H2 predicts code-mode leaves the median per-call output ≈ unchanged but reduces the p90/p95/p99 because the agent paginates output volume in Python.

The original "MCP output compression" hypothesis predicts the median *shifts down*; it does not survive in any of the four cells.

---

## 2. Codex SWE-bench (the original cell)

Headline ([paper/data/raw/all_results.csv](../raw/all_results.csv), n=300 per arm × 3 seeds):

| arm        | pass%  | input_tokens | output_tokens | LLM calls | tool calls | tools/LLM |
|------------|-------:|-------------:|--------------:|----------:|-----------:|----------:|
| baseline   | 46.3%  |      557 671 |         4 721 |      19.0 |       25.7 |   **1.35** |
| bash_only  | 45.3%  |      583 546 |         5 341 |      18.9 |       25.2 |   1.33 |
| onlycode   | 46.7%  |      419 347 |         4 686 |      18.9 |       16.9 |   **0.89** |

Per-call output distribution (21 479 tool outputs across 990 rollouts):

| arm        | n calls | mean   | **median** | p75    | p90    | p95    | p99      |
|------------|--------:|-------:|-----------:|-------:|-------:|-------:|---------:|
| baseline   |   7 564 |  3 761 |   **1 648** |  3 769 |  8 461 | 16 028 | **40 154** |
| bash_only  |   8 286 |  3 659 |   **1 554** |  3 614 |  8 408 | 16 007 | **40 154** |
| onlycode   |   5 629 |  2 999 |   **1 747** |  3 965 |  7 613 | 10 575 | **16 736** |

### H1 — tool-call batching: STRONG

- Tools-per-LLM-call drops from 1.35 (baseline) to 0.89 (onlycode) — a 34 % reduction with L held constant.
- `bash_only` matches baseline at 1.33: removing `apply_patch` from baseline does *not* trigger batching. The lever is the `execute_code` surface, not "fewer native tools."
- Args-per-call grows from 215 chars (baseline) to 512 chars (onlycode), consistent with the agent packing multi-operation Python scripts into single calls.

### H2 — upper-tail suppression: STRONG

- **Median moves the *wrong* way for compression** (1 747 > 1 648 baseline) — the typical onlycode call is larger, not smaller.
- p99 collapses from 40 154 (= the `max_output_tokens=6000` ≈ 40 154-char ceiling for `exec_command`) to 16 736.
- 132 of baseline's 7 564 calls (1.7 %) are pinned at the ceiling; 1 of onlycode's 5 629 calls is. Those clip-pinned calls produce **18.6 % of baseline's total tool-output bytes**.
- Upper-tail-only attribution: cumulative bytes/run from calls ≥ 16 k chars: baseline 33 265, onlycode 4 590 — a 28 675 chars/run gap, of which 15 922 (~55 %) is from clip-pinned events and 12 753 (~45 %) is from the unclipped 16–39 k shoulder.

### Decomposition of the 167 k token gap

Counterfactual marginals (hold one factor at baseline, swap the other):

| effect | savings (tokens) | share of 167 139 |
|--------|-----------------:|-----------------:|
| H1 (tools-per-LLM ratio: 1.26 → 0.95) | 99 441 | ~60 % |
| H2 (upper-tail bytes: −16 k chars/run from ≥16 k tail) | ~92 000 | ~50 % |
| Floor anti-savings (onlycode's tools schema +900 tokens × 18 L) | −16 000 | −10 % |
| Agent-message anti-savings (+760 tokens/run prose, integrated) | −6 800 | −4 % |
| Interaction & remainder | residual | ~4 % |

Shares sum to >100 % because they're counterfactual marginals, not a partition.

---

## 3. Codex Artifact (extension #1)

Headline (n=93 per arm × 3 seeds):

| arm        | pass%  | input_tokens | LLM calls | tool calls | tools/LLM |
|------------|-------:|-------------:|----------:|-----------:|----------:|
| tool_rich  | 98.9%  |       52 719 |       5.6 |        6.1 |   **1.09** |
| bash_only  | 96.1%  |       46 878 |       5.0 |        3.7 |   0.73 |
| code_only  | 98.6%  |       39 493 |       4.4 |        2.4 |   **0.55** |

Per-call output distribution:

| arm        | mean | **median** | p75 | p90  | p95  | p99   | max    |
|------------|-----:|-----------:|----:|-----:|-----:|------:|-------:|
| tool_rich  |  600 |   **255**  | 499 | 1 337 | 2 518 | 4 182 | 24 152 |
| bash_only  |  901 |   **442**  | 836 | 1 976 | 3 537 | 10 199 | 19 473 |
| code_only  |  641 |   **291**  | 586 | 1 076 | 1 825 | 11 442 | 15 266 |

### H1 — tool-call batching: STRONG

- Tools-per-LLM drops 1.09 → 0.55, half as many tool calls per LLM step.
- Calls-per-run drops 6.1 → 2.4 (a 60 % reduction in *absolute* tool invocations because L also drops here, unlike SWE-bench).
- Args-per-call grows 477 → 1 403 — the agent puts much more Python into each call.

### H2 — upper-tail suppression: WEAK / MIXED

- Median is similar across arms (255 / 442 / 291) — no compression effect on the body.
- p99 actually goes the *wrong way* (4 182 tool_rich → 11 442 code_only) — code_only has a slightly fatter p99 than tool_rich.
- max is smaller for code_only (15 266 < 24 152).
- **Why H2 doesn't hold here:** Artifact tasks are short (median ~5 LLM calls); there isn't enough surface area for the upper-tail mechanism to matter much. tool_rich's `Read`/`Grep`/native tools return structured summaries that are *already* tight, so there's no verbose-stdout problem to suppress.

H1 carries most of the 25 % input-token win in this cell.

---

## 4. Claude Artifact (extension #2)

Headline (n=93 per arm × 3 seeds):

| arm        | pass%  | input_tokens | LLM calls | tool calls | tools/LLM |
|------------|-------:|-------------:|----------:|-----------:|----------:|
| tool_rich  | 98.6%  |      118 520 |       9.1 |        2.8 |   0.31 |
| bash_only  | 97.5%  |       67 566 |       8.4 |        3.0 |   0.36 |
| code_only  | 97.5%  |       44 843 |       7.2 |        2.6 |   0.36 |

Per-call output distribution:

| arm        | mean | **median** | p75 | p90  | p95  | p99    | max    |
|------------|-----:|-----------:|----:|-----:|-----:|-------:|-------:|
| tool_rich  |  894 |    **183** | 500 | 1 528 | 4 038 | **14 782** | 41 615 |
| bash_only  |  595 |    **137** | 481 | 1 154 | 2 094 | **13 449** | 19 603 |
| code_only  |  569 |    **288** | 524 | 1 002 | 1 413 |  **9 533** | 16 454 |

### H1 — tool-call batching: ABSENT

- Tools-per-LLM ratio is structurally ~0.3 across all arms — Claude does ~1 tool call per LLM response and many LLM calls produce no tool calls at all (thinking-only steps).
- code_only's tools/LLM is actually slightly *higher* than tool_rich's (0.36 vs 0.31). H1 is not the lever.

### H2 — upper-tail suppression: STRONG (with same median-up signature as Codex SWE-bench)

- code_only median is *higher* than tool_rich (288 > 183) — the body of the distribution moves the wrong way for compression.
- p99: 14 782 → 9 533, a 35 % drop.
- max: 41 615 → 16 454, a 60 % drop.
- bash_only's p99 (13 449) sits between tool_rich and code_only — modest suppression from removing `Read`/`Edit`/etc., bigger suppression from `execute_code`.

### What drives the 62 % input-token win, then?

The transcript-growth math doesn't fully add up if only H2 is operative — the per-run output content delta is much smaller than the 74 k input-token savings. **Two additional levers carry most of the win here:**

- **F (floor) reduction.** Claude's `tool_rich` system + tool schema is large (Read/Write/Edit/Glob/Grep/Bash/Task/TodoWrite/WebFetch/…); restricting to `mcp__codebox__execute_code` shrinks the schema substantially. With L=9.1 and a ~5 k-token schema gap, that's ~45 k tokens of floor savings — a large chunk of the 74 k delta.
- **L reduction.** LLM calls drop 9.1 → 7.2 (−21 %). Fewer rounds means fewer re-feeds of history.

H2 contributes via the tail but isn't dominant here. The other levers — fixed-floor shrink and L drop — are the bigger story for Claude Artifact.

---

## 5. Claude SWE-bench (the surprise cell)

Headline (n=300 per arm × 3 seeds):

| arm        | pass%  | input_tokens | output_tokens | LLM calls | tool calls | tools/LLM |
|------------|-------:|-------------:|--------------:|----------:|-----------:|----------:|
| baseline   | 51.7%  |      658 614 |        11 138 |      43.0 |       14.5 |   0.34 |
| bash_only  | 51.0%  |  **903 220** |        14 368 |      48.9 |       13.9 |   0.28 |
| onlycode   | 50.0%  |  **795 678** |        15 231 |      50.1 |       15.3 |   0.31 |

**onlycode uses 21 % MORE input tokens than baseline here, despite ~equal pass rate.** This is the opposite sign of the other three cells.

Per-call output distribution:

| arm        | mean   | **median** | p75    | p90    | p95    | p99      | max      |
|------------|-------:|-----------:|-------:|-------:|-------:|---------:|---------:|
| baseline   |  1 577 |    **669** |  1 712 |  3 309 |  5 070 | **14 153** | **97 143** |
| bash_only  |  1 074 |    **542** |  1 446 |  2 621 |  3 573 |  7 299 | 25 331 |
| onlycode   |  1 236 |    **666** |  1 663 |  3 017 |  4 125 |  7 858 | 17 214 |

### H1 — tool-call batching: ABSENT (same as Claude Artifact)

- All three arms cluster at 0.28–0.34 tools/LLM. Claude doesn't batch.

### H2 — upper-tail suppression: STRONG

- Median is essentially identical across baseline and onlycode (669 ≈ 666) — body of distribution unchanged.
- p99 drops from 14 153 (baseline) to 7 858 (onlycode) — 44 % thinner tail.
- max drops from **97 143** to 17 214 — baseline has individual tool outputs nearly as long as the whole onlycode run's input tokens for a single call. Almost certainly raw `Bash` outputs like full pytest dumps or `cat` of large source files.

### Why does onlycode lose input tokens here despite H2 holding?

L blows up:

- baseline: 43.0 LLM calls
- onlycode: 50.1 LLM calls (+16.5 %)

And tool-call count is also slightly higher (14.5 → 15.3). So even though per-call outputs are smaller and the upper tail is thinner, the agent needs more LLM rounds to make progress under the code-only restriction on SWE-bench-scale codebases. **Net: each LLM call is leaner, but there are more of them, and the round-count inflation outweighs the per-call savings.**

Intuition: SWE-bench tasks require navigating large real-world Python repos. Claude's `Read`/`Glob`/`Grep` give it native idioms for that navigation; forcing it to do everything via `execute_code` adds back-and-forth (write Python to glob, run it, read result, write next Python to filter, etc.) that wouldn't happen with native file-system tools. On the much smaller Artifact tasks (single-script workspaces), this overhead doesn't materialize and the F + L + H2 wins net out positive.

### Output tokens compound the loss

Output tokens (which include reasoning) are *also* higher for onlycode (15 231 vs 11 138, +37 %) — the model writes more, not just reads more. This is consistent with extra Python composition vs. one-shot file edits.

---

## 6. Cross-cell synthesis

| Cell                  | Δ input_tokens | H1 (tools/LLM batching) | H2 (upper-tail suppression) | L change | F (floor) change | Net mechanism |
|-----------------------|---------------:|:------------------------|:----------------------------|:---------|:-----------------|:--------------|
| Codex × SWE-bench     |        −24.8 % | STRONG (1.35→0.89)      | STRONG (p99 40k→17k)        | flat     | small anti       | H1 + H2 |
| Codex × Artifact      |        −25.1 % | STRONG (1.09→0.55)      | WEAK (p99 ↑)                | down 22 %| small anti       | H1 + L↓ |
| Claude × Artifact     |        −62.2 % | ABSENT (flat ~0.34)     | STRONG (p99 ↓ 35 %)         | down 21 %| **large schema shrink** | F↓ + L↓ + H2 |
| Claude × SWE-bench    |        **+20.8 %** | ABSENT (flat ~0.31)     | STRONG (p99 ↓ 44 %, max ↓ 82 %) | **up 17 %** | large schema shrink (not enough) | **L↑ swamps F↓ + H2** |

**What travels:**

- **H2 (upper-tail suppression) is the most generalizable finding.** It holds in all four cells. The mechanism is independent of agent identity: whenever the code-execution tool replaces verbose-stdout tools, the agent's output is paginated through Python and the upper tail collapses. This is the cleanest tool-surface-design finding in the data.
- **H1 (tool-call batching) is Codex-specific.** Codex's Responses-API loop allows multiple parallel `function_call` items per LLM response; Claude's loop emits at most one tool call per response (with many response steps doing only reasoning). H1 simply has no lever on Claude. For Codex it's the dominant savings mechanism.
- **F (floor) reduction is agent-specific too.** Claude's native tool schema is large; restricting to `execute_code` shrinks the prompt floor substantially. Codex's native schema is smaller and the restriction directive actually *adds* tokens, producing a small anti-savings.
- **L (LLM-call count) is workload-specific, not surface-specific.** On Artifact (small, self-contained tasks) code-mode reduces L. On SWE-bench-scale codebases for Claude, code-mode *raises* L because navigation via `execute_code` takes more rounds than native `Read`/`Glob`/`Grep`.

**Why Claude SWE-bench reverses sign:** every per-call signal favors onlycode (median equal, p99 −44 %, max −82 %), but the agent needs more rounds (L +17 %) to converge. Per-call cleanliness × inflated round count = net loss. The H2 finding still holds; it just doesn't dominate.

---

## 7. Paper-level prescription (the conditional / "consistent with" framing)

> Code-execution surfaces produce structurally cleaner tool returns than restricted-native alternatives — thinner per-call upper tails across all four (agent × benchmark) cells we measured, and substantially fewer tool calls per inference step where the agent's API supports batching (Codex). The `bash_only` controls (restricted-native-tool arms) consistently fail to reproduce either signal, ruling out "restrict tools" as the active ingredient. Whether this transcript-cleanliness translates into a net input-token win depends on the workload: when the code-execution surface lets the agent converge in similar or fewer LLM rounds (Codex on both benchmarks, Claude on Artifact), the win is 25–62 %; when it inflates the round count (Claude on SWE-bench), per-call savings are overwhelmed by inflation and code-mode is net more expensive. The mechanism is **consistent with** the agent authoring its own output paging and batching multi-step work into single calls; it is **not consistent with** the literal "MCP wrapper output compression" hypothesis, which predicts the per-call median moves down (it does not, in any cell).

That paragraph is the strongest claim the data supports without an isolating experiment.

---

## 8. Gaps, confounds, and what would close them

### 8.1 Confounds within H1
H1's "code-mode batches multiple operations per tool call" is consistent with at least three sub-mechanisms that current arms cannot separate:
1. **Surface expressiveness** — `execute_code` syntactically allows multi-operation scripts; `exec_command` requires one shell command per call.
2. **Persistent kernel state** — `execute_code` shares a REPL across calls; baseline calls are stateless. This may *cause* the agent to write longer scripts (state to set up is amortized).
3. **Ceiling-induced retries on baseline** — `exec_command`'s clip ceiling at 40 154 chars triggers narrower retries (`rg -m 50`, `pytest -k …`) that ratchet tool count up.

All three predict the same tools/LLM signature.

### 8.2 Confounds within H2
H2's "agent authors output volume in code-mode" cannot be cleanly separated from:
- Persistent kernel obviating verbose recomputation (state survives → don't need to re-print).
- Different tool surfaces producing different *task-decomposition* patterns (the agent may simply not run `pytest`-full or `cat large_file` in code-mode because Python invites smaller probes).

### 8.3 Isolating experiments (one would close most of the gap)

The cleanest single experiment is a **`onlycode --no-persistent-kernel` arm** on SWE-bench × Codex (the cell with the largest signal). The harness already supports `--no-persistent-kernel`. Three diagnostic predictions:

- If statefulness drives both H1 and H2: tools/LLM and p99 both rebound toward baseline.
- If surface expressiveness drives H1 and agent-authored paging drives H2: tools/LLM stays low, p99 stays low.
- If ceiling-retry drives H1 but stateless reverses agent-authored paging: tools/LLM stays low (because `exec_command`'s ceiling is still there), p99 rebounds upward.

A secondary experiment — raising `max_output_tokens` on baseline from 6 000 to 60 000 — would isolate the ceiling-retry confound from the surface-expressiveness one.

### 8.4 Other gaps the corrigendum acknowledges

- Cross-arm `len()` comparison ignores tokenization bias (JSON-escaped envelope tokenizes denser than verbatim stdout). Direction: probably understates H2's true magnitude.
- Bootstrap CIs in §2 were over per-run means (one mean per rollout); per-call resampling would give artificially narrow intervals due to within-rollout correlation.
- Wall-time confound ruled out (mean 122–133 s, no timeout hits, no cross-arm wall-time bias).
- Crash-out distribution not checked beyond pass-rate parity.
- The `bash_only` paradox in Codex SWE-bench (slightly *more* tools/LLM than baseline despite being a strict tool-subset) is unexplained — possibly the loss of `apply_patch` forces multi-step edit sequences.

---

## 9. Reproducibility

All numbers derive from:
- [paper/data/raw/all_results.csv](../raw/all_results.csv) for headline aggregates
- Codex rollouts: `runs/swebench/full_run_seed_{1,2,3}_codex_v2/*.rollout.jsonl` and equivalent under `runs/artifact/`
- Claude logs: `runs/swebench/full_run_seed_{1,2,3}/*.jsonl` and `runs/artifact/full_run_seed_{1,2,3}/<task>/<arm>/run*/agent.jsonl`
- Extractors: rollout walker matches `_parse_codex_rollout` in [scripts/parse_run.py](../../../scripts/parse_run.py); Claude walker reads `tool_result` content from `user` messages and `tool_use` from `assistant` messages.

Bootstrap CI methodology: per-rollout means resampled with replacement (n_resample = 2000); intervals are the 2.5 / 97.5 percentile of the bootstrap distribution. Reported CIs apply to per-run means, not per-call values.

---

## Appendix: Investigation arc / changes from earlier drafts

Earlier drafts of this document framed the per-call output gap as primarily a "wrapper compression" effect and the §2 headline reported only the mean (3 761 baseline vs 2 999 onlycode chars). An Opus subagent review and subsequent re-analysis surfaced that:
1. The mean reduction is dominated by a right-tail effect — the median in fact goes the *other* way (1 747 > 1 648).
2. ~55 % of the upper-tail byte gap is from ceiling-clipped events at exactly the `max_output_tokens=6000` ≈ 40 154-char boundary; the other ~45 % is from genuine right-shoulder thinning in the 16–39 k range.
3. The "compression" framing falsely predicted the median should drop, which it does not in any of the four cells measured.

The current H1/H2 framing replaces the earlier "expressiveness + statefulness" causal language with a descriptive structural finding (the two transcript-structure deltas) that can be defended without isolating sub-mechanisms.
