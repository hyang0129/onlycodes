# Concrete examples for H1 (batching) and H2 (token-limit avoidance)

Working notes for §6 of the paper. Two example pairs drawn from rollout sidecars under
`runs/swebench/full_run_seed_*_codex_v2/`. Each example pair compares the **baseline**
and **onlycode** arms of the same Codex SWE-bench instance, with the JSONL excerpts
that illustrate the structural difference.

Both examples are from the **Codex × SWE-bench** cell (the cell where H1 and H2 are
both strongest — see [paper/q2_token_gap_investigation.md §2](../q2_token_gap_investigation.md)).
For H1, Claude has no batching lever (its API emits at most ~one tool call per LLM
response across all arms — see q2 §4–5), so a Codex example is mandatory.

Aggregate metrics for the two instances (from `paper/data/raw/all_results.csv`):

| instance                         | seed | arm      | verdict | tool_calls | llm_calls | input_tokens |
|----------------------------------|-----:|----------|---------|-----------:|----------:|-------------:|
| H1 — `sphinx-doc__sphinx-7757`   | 3    | baseline | PASS    | 81         | 59        | 2 624 279    |
|                                  | 3    | onlycode | PASS    | **14**     | 16        | **292 845**  |
| H2 — `django__django-11848`      | 1    | baseline | PASS    | 18         | 14        | 454 946      |
|                                  | 1    | onlycode | PASS    | 7          | 9         | **108 245**  |

Both pairs are **pass / pass** (so the comparison isn't confounded by capability
collapse — the agents converge on the same fix, but along different transcript paths).

---

## H1 — Tool-call batching: `sphinx-doc__sphinx-7757` (Codex)

The agents are inspecting Sphinx's Python-domain signature parser to fix a
positional-only-argument rendering bug. After a first scoping turn, both arms decide
on the same three-step investigation: **(a) read a slice of `sphinx/domains/python.py`,
(b) read a slice of a test file, (c) scan the tests directory for related test names.**
Baseline (`exec_command`) emits three parallel `function_call` items in a single LLM
response; onlycode (`execute_code`) collapses the equivalent work into a single Python
script that returns one combined output.

### Baseline rollout — three parallel `exec_command` calls in one LLM step

File: `runs/swebench/full_run_seed_3_codex_v2/sphinx-doc__sphinx-7757_baseline_run1.jsonl.rollout.jsonl`, lines 19–22.

```jsonl
// line 19 — assistant commentary
{"type":"message","role":"assistant","content":[{"type":"output_text","text":
"The relevant path is `sphinx/domains/python.py`: it parses directive arglists into
`inspect.Parameter` objects and then reconstructs display nodes. I'm checking that
reconstruction now, especially the branch that inserts `/`."}]}

// line 20 — first parallel function_call
{"type":"function_call","name":"exec_command","call_id":"call_uRxtXPfpQCEnNZ3zo1fEK1AQ",
 "arguments":"{\"cmd\":\"sed -n '130,200p' sphinx/domains/python.py\",
              \"workdir\":\"/tmp/sphinx-doc__sphinx-7757-eval/merged\",
              \"yield_time_ms\":1000,\"max_output_tokens\":5000}"}

// line 21 — second parallel function_call
{"type":"function_call","name":"exec_command","call_id":"call_YS9NIDNcnGxC8Xim3OxIA6OE",
 "arguments":"{\"cmd\":\"sed -n '250,355p' tests/test_util_inspect.py\",
              \"workdir\":\"/tmp/sphinx-doc__sphinx-7757-eval/merged\",
              \"yield_time_ms\":1000,\"max_output_tokens\":5000}"}

// line 22 — third parallel function_call
{"type":"function_call","name":"exec_command","call_id":"call_C8VopYsrc5MPPzigNdeQ2Tee",
 "arguments":"{\"cmd\":\"rg -n \\\"_parse_arglist|desc_parameterlist|py:function|function::\\\" tests/test_domain_py.py tests -g '*py*'\",
              \"workdir\":\"/tmp/sphinx-doc__sphinx-7757-eval/merged\",
              \"yield_time_ms\":1000,\"max_output_tokens\":10000}"}

// lines 24, 25, 26 — three function_call_output responses, one per call_id
```

Three tool-call items, three tool-output items appended to history in this one
inference step. (The 81 vs 14 tool-call ratio for this instance is largely produced
by repetition of this pattern across the run.)

### Onlycode rollout — single `execute_code` call doing the equivalent work

File: `runs/swebench/full_run_seed_3_codex_v2/sphinx-doc__sphinx-7757_onlycode_run1.jsonl.rollout.jsonl`, line 28.

```jsonl
// line 28 — single function_call
{"type":"function_call","name":"execute_code","call_id":"call_b4Ox72RoEFeQW3iHUq5oyOxp",
 "arguments":"{\"language\":\"python\",
              \"cwd\":\"/tmp/sphinx-doc__sphinx-7757-eval/merged\",
              \"code\":\"import codebox\\nprint(codebox.read_lines('tests/test_domain_py.py', 320, 380))\\nprint('--- imports ---')\\nprint(codebox.read_lines('sphinx/domains/python.py', 1, 40))\\nprint('--- signature_from_str source ---')\\nprint(codebox.source_of('signature_from_str', 'sphinx'))\",
              \"timeout_seconds\":30}"}

// line 31 — single function_call_output with all three pieces concatenated
```

One tool-call item, one tool-output item appended to history. The Python script
executes three logically independent reads (two file slices + a symbol-source lookup
via `codebox.source_of`) and concatenates the results with `print()` delimiters.

### Notes

- Files:
  - baseline: `runs/swebench/full_run_seed_3_codex_v2/sphinx-doc__sphinx-7757_baseline_run1.jsonl.rollout.jsonl`, turns 19–22 (and parallel output lines 24–26)
  - onlycode: `runs/swebench/full_run_seed_3_codex_v2/sphinx-doc__sphinx-7757_onlycode_run1.jsonl.rollout.jsonl`, turn 28
- For this single LLM step: **3 baseline tool calls vs 1 onlycode tool call** doing
  the same logical "read two files + check related symbol" operation.
- The mechanism (per [q2_token_gap_investigation.md §2](../q2_token_gap_investigation.md)):
  Codex's Responses-API loop natively emits multiple `function_call` items in one
  assistant response (baseline avg 1.35 tools/LLM call across the cell). The `execute_code`
  surface lets the model author a multi-step Python script as the *body* of one tool
  call, collapsing the same work into one item appended to history.
- A second instance of the same pattern in this rollout is at baseline lines 10–12
  (two parallel `rg` scoping queries + `git status --short`) vs onlycode line 10
  (one `execute_code` call running `codebox.grep('positional', 'sphinx')` plus
  `codebox.outline('sphinx/domains/python.py')`).

---

## H2 — Token-limit avoidance: `django__django-11848` (Codex)

Both arms are inspecting Django's `parse_http_date` for the two-digit-year fix.
The baseline arm runs a broad `ripgrep` query whose output exceeds the call's
`max_output_tokens=12000` ceiling and is clipped by the `exec_command` wrapper —
the truncated payload is exactly the **40 154-char p99 ceiling** identified in
[q2_token_gap_investigation.md §2](../q2_token_gap_investigation.md) (clip pinning
at the 6000-token cap × ~4 bytes/token). The onlycode arm runs a narrower,
scoped `codebox.grep` (only the symbol `parse_http_date`, omitting noise terms)
and returns 1 514 chars cleanly — no truncation marker. Same fix, same final
verdict (PASS), 4.2× fewer input tokens billed across the run.

### Baseline rollout — limit hit (explicit truncation marker)

File: `runs/swebench/full_run_seed_1_codex_v2/django__django-11848_baseline_run1.jsonl.rollout.jsonl`, lines 10 and 13.

```jsonl
// line 10 — the function_call that triggers truncation
{"type":"function_call","name":"exec_command","call_id":"call_...",
 "arguments":"{\"cmd\":\"rg -n \\\"parse_http_date|RFC 850|rfc850|two-digit|69|2069\\\" django tests\",
              \"workdir\":\"/tmp/django__django-11848-eval/merged\",
              \"yield_time_ms\":1000,\"max_output_tokens\":12000}"}

// line 13 — function_call_output, total payload = 40 165 chars (the p99 ceiling)
{"type":"function_call_output","output":
"Chunk ID: c62cce
 Wall time: 1.0013 seconds
 Process running with session ID 66248
 Original token count: 13918
 Output:
 Total output lines: 223

 django/middleware/http.py:5:from django.utils.http import parse_http_date_safe
 ...
 [~20 000 chars of noisy hits: SVG path data from test fixtures, cache key hashes,
  unrelated `869` matches in postgresql/introspection.py, etc.]
 ...
 9.7059900058266777, -95.3896062677805787 29.7060738276384…3918 tokens truncated…7387804389000, 946502.2630172523204237
 ...
 django/db/backends/mysql/base.py:63:        1690,  # BIGINT UNSIGNED value is out of range
 django/db/backends/postgresql/introspection.py:18:        869: 'GenericIPAddressField',"}
```

Key signals:
- The wrapper inserts a literal `…3918 tokens truncated…` ellipsis in the middle
  of the payload at offset 20 155 — explicit confirmation of the cap hit.
- The payload header reports `Original token count: 13918`, which exceeded the
  `max_output_tokens: 12000` cap declared in the call args.
- Total payload size is 40 165 chars, sitting at the p99 ceiling of 40 154 chars
  observed across all 7 564 baseline tool outputs in this cell (see
  [q2 §2](../q2_token_gap_investigation.md), per-call output distribution table).
- The `2069` term in the regex (intended to match the millennium-boundary year)
  also matched coordinate tokens in SVG fixture data and a Postgres OID 869 —
  this is exactly the kind of broad-grep pathology the `exec_command` ceiling
  is designed to clip.

Baseline then spends the next 2 turns (lines 18, 19, 24, 25) running narrower
follow-up probes (`sed '1,220p' django/utils/http.py`, `sed '280,345p' tests/utils_tests/test_http.py`,
plus a `mock|utcnow` rg) to recover the context that the truncated query failed
to surface.

### Onlycode rollout — limit avoided (narrower scoped grep)

File: `runs/swebench/full_run_seed_1_codex_v2/django__django-11848_onlycode_run1.jsonl.rollout.jsonl`, lines 10 and 13.

```jsonl
// line 10 — scoped execute_code call
{"type":"function_call","name":"execute_code","call_id":"call_...",
 "arguments":"{\"cwd\":\"/tmp/django__django-11848-eval/merged\",
              \"language\":\"python\",
              \"timeout_seconds\":30,
              \"code\":\"import codebox\\nprint(codebox.grep('parse_http_date', 'django'))\\nprint(codebox.grep('parse_http_date', 'tests'))\"}"}

// line 13 — function_call_output, total payload = 1 514 chars, no truncation
{"type":"function_call_output","output":
"Wall time: 1.4369 seconds
 Output:
 [{\"type\":\"text\",\"text\":\"
   django/middleware/http.py:5:from django.utils.http import parse_http_date_safe
   django/middleware/http.py:26: ... = ... and parse_http_date_safe(last_modified)
   django/utils/cache.py:28: http_date, parse_etags, parse_http_date_safe, quote_etag,
   django/utils/cache.py:142: if_unmodified_since = ... parse_http_date_safe(if_unmodified_since)
   django/utils/cache.py:145: if_modified_since = ...
   ...
   tests/utils_tests/test_http.py:299: def test_parse_http_date(self):
   ...\"}]"}
```

Key signals:
- The agent uses **only the symbol name** (`parse_http_date`) as the regex,
  omitting the noise terms (`RFC 850|rfc850|two-digit|69|2069`) that the
  baseline included.
- Returned payload: 1 514 chars, ~27× smaller than baseline's clipped 40 165.
- No truncation marker; no follow-up "recovery" probes are needed — the next
  call (line 16) jumps straight to reading the relevant code lines
  (`codebox.read_lines('django/utils/http.py', 130, 205)` + the focused test slice).

### Notes

- Files:
  - baseline: `runs/swebench/full_run_seed_1_codex_v2/django__django-11848_baseline_run1.jsonl.rollout.jsonl`, turns 10 / 13
  - onlycode: `runs/swebench/full_run_seed_1_codex_v2/django__django-11848_onlycode_run1.jsonl.rollout.jsonl`, turns 10 / 13
- Per-run aggregate metrics (codex SWE-bench, instance `django__django-11848` seed 1):

  | arm      | verdict | tool_calls | llm_calls | input_tokens | output_tokens |
  |----------|---------|-----------:|----------:|-------------:|--------------:|
  | baseline | PASS    | 18         | 14        | 454 946      | 3 376         |
  | onlycode | PASS    | 7          | 9         | **108 245**  | 2 210         |

- The truncation is a **per-tool-output cap hit** (`exec_command`'s `max_output_tokens=12000`
  ≈ 40 154 chars), not a stop_reason on the LLM response itself — Codex's `exec_command`
  silently clips and inserts a `…N tokens truncated…` marker rather than failing the call.
  See [q2 §2](../q2_token_gap_investigation.md) for the population-level evidence:
  132 of baseline's 7 564 tool outputs (1.7 %) pin at this exact boundary, contributing
  ~55 % of the upper-tail byte gap between baseline and onlycode.
- The H2 mechanism here is **not** "the agent paginates explicitly with slicing"
  (the canonical `x[:4000]` form). Instead it is the simpler "the `execute_code`
  surface invites a more targeted query" effect — the Python `codebox.grep` API
  takes a single symbol argument, while `ripgrep` regex syntax invites the agent
  to OR together related terms. Both predictions of H2 (thinner upper tail without
  median compression) are visible at the population level in q2 §2.

---

## Caveats

- The H1 example is a single LLM step; it illustrates the per-step mechanism that
  produces the population-level 1.35 → 0.89 tools-per-LLM-call drop, but the
  paper's claim should cite the population statistic, with this excerpt as
  illustration.
- **Phrasing nit, not a substantive caveat:** the H2 example shows a *scoping*
  difference (broad `rg` vs targeted `grep` for one symbol) rather than the
  textbook explicit-pagination tactic (`print(x[:4000])`). Both are surface
  tactics of the **same root mechanism** — in code mode the agent has
  programmatic control over the query and the printed output, so it can keep
  the returned payload bounded; in native-tool mode it submits a query and
  receives whatever the tool emits (pinned at the 40,154-char cap when output
  blows up). I scanned the 132 ceiling-pin events for a baseline-vs-onlycode
  pair where the onlycode arm used literal slicing on the same wide query,
  but every cap-hit had the same structure (broad regex catching fixture
  noise) and the onlycode counterpart simply ran a narrower query rather than
  slicing a wide one. So: the *claim* — "code mode avoids the per-call output
  cap because the agent controls output volume programmatically" — is fully
  supported by this example. The §6 prose should just avoid naming the
  specific `x[:4000]` tactic when pointing here; "the agent issued a narrower
  query" or "the agent constrained output programmatically" is the right
  phrasing. The literal-slicing prediction is best supported by aggregate
  median-vs-tail evidence in q2 §2.
- Both examples are Codex-only. Claude does not batch (q2 §4–5), so an H1 Claude
  example is not available; the Claude SWE-bench H2 evidence is in q2 §5
  (baseline max 97 143 chars vs onlycode max 17 214 chars, ~82 % drop) but
  no clean single-pair excerpt was selected for here.
- These instances were chosen from `paper/data/raw/all_results.csv` by ranking
  Codex SWE-bench (baseline, onlycode) pairs on `tool_calls_baseline − tool_calls_onlycode`
  (H1) and by scanning all baseline rollouts for outputs ≥ 39 000 chars (H2);
  both selections are verified against the actual JSONL bytes.
