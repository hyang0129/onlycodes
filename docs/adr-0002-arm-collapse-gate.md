# ADR-0002 — Arm-Collapse Smoke Gate for the Artifact Benchmark

- **Status:** Proposed (implementer proposal — requires user ratification per epic #92 Open Q #6).
- **Context:** Child issue [#95](https://github.com/hyang0129/onlycodes/issues/95) of epic [#92](https://github.com/hyang0129/onlycodes/issues/92).
- **Decision date:** 2026-04-20.
- **Related:** ADR-0001 (artifact-mode harness), SCHEMA_ARTIFACT.md.

---

## 1. Context

Epic #92's **secondary, smoke-checkable** feared failure mode is *arm collapse*:

> Tool-rich and code-only arms show no separation because the artifact-output
> constraint itself forces both arms into the same write-a-file workflow,
> flattening the axis the benchmark is trying to isolate.

The epic defers a concrete gate criterion to the first-task slice (#95). The
proposal recorded in epic Open Q #6 is: *"after `p95_latency_easy` lands, run
both arms once and require non-identical execution traces; if identical, pause
decomposition of the remaining 11 tasks and reconsider task shape."*

This ADR turns that one sentence into a mechanically applicable check.

## 2. Decision

The **arm-collapse smoke gate** is a three-signal check run after a single
`artifact run --filter data_processing__p95_latency_easy --arms both` completes.
The run must produce two agent JSONL logs, one per arm:

- `results_artifact/<instance_id>/code_only/run0/agent.jsonl`
- `results_artifact/<instance_id>/tool_rich/run0/agent.jsonl`

A small script at `tools/arm_collapse_check.py` (slice #95 ships a stub; full
implementation may land in #96 alongside `verify_graders.py`) computes the
three signals below from those logs.

### 2.1 Signal A — Tool-call sequence divergence (PRIMARY)

Extract from each arm's log the ordered list of tool-use events:

```
tool_seq(arm) = [event.tool_name for event in agent_jsonl if event.type == "tool_use"]
```

Two operational definitions of divergence, in order of strictness:

- **A1 — Multiset difference:** `Counter(tool_seq(code_only)) != Counter(tool_seq(tool_rich))`.
  Cheap and robust against ordering noise. Passes iff the arms used different
  tools or different frequencies.
- **A2 — Sequence-edit distance:** normalised Levenshtein distance over the
  ordered tool-name strings, `levenshtein(A, B) / max(len(A), len(B))`.

**Signal A is a PASS if A1 holds OR A2 ≥ 0.20.** (A1 alone is sufficient; A2
is a tie-breaker for the degenerate case where both arms make literally the
same tool calls in the same count but reorder them — we do not want to fail
that.)

### 2.2 Signal B — Step count divergence (SECONDARY)

Let `N(arm) = len(tool_seq(arm)) + 1` (tool calls plus a final-message step).

**Signal B is a PASS if `abs(N_code_only - N_tool_rich) / max(N_code_only, N_tool_rich) >= 0.25`.**

Rationale: a 25% gap in step count is large enough to exceed run-to-run
noise on a 10k-row aggregation task, and small enough that a genuinely
divergent workflow will routinely clear it (code-only typically fires one
`execute_code` that does everything; tool-rich typically fires 5–15 `Read` +
`Grep` + `Write` calls).

### 2.3 Signal C — Intermediate-write divergence (TERTIARY)

Let `writes(arm)` be the set of distinct file paths the agent wrote to under
`scratch/` during the run (excluding the final `output/p95.jsonl` which is
required by the task and therefore identical by construction).

**Signal C is a PASS if `writes(code_only) != writes(tool_rich)` as sets.**

Rationale: if both arms only touch the required output file and nothing else,
the arms are in fact executing identical workflows at the file-system level,
which is the sharpest possible statement of collapse.

### 2.4 Overall verdict

| Gate verdict | Condition |
|---|---|
| **GO (green)**   | Signal A passes AND at least one of B or C passes. |
| **AMBER**        | Signal A passes alone (no B, no C). Proceed to decomposition of #97–#102, but flag for re-evaluation after the second task (`algorithmic__*_easy`) runs. |
| **NO-GO (red)**  | Signal A fails (A1 false AND A2 < 0.20). Stop decomposition of #97–#102. Intent holder (issue author) must ratify a task-shape change before any further seed task lands. |

### 2.5 Why not statistical separation?

Epic #92 explicitly calls out: *"A statistical-power-class arm-separation
analysis — the gate is qualitative (non-identical traces), not quantitative
separation."* This ADR honours that — the gate is about execution-trace
non-identity, not about a pass-rate delta. A statistical-separation analysis
belongs to a later epic once the benchmark shape is validated.

## 3. Consequences

- This ADR is self-contained: the signals can be computed from the existing
  agent JSONL emitted by the harness (#94). No new instrumentation is
  required in the agent runner.
- The gate script (`tools/arm_collapse_check.py`) is small and side-effect-free;
  it reads two JSONL files and prints `GO | AMBER | NO-GO` plus one line per
  signal. Landing it in a follow-up slice (#96 or a dedicated follow-up) is
  acceptable — the gate definition here is sufficient to run manually.
- If the gate trips NO-GO, the epic pauses decomposition of the remaining
  task slices. The intent holder decides whether to (a) reshape the task
  (e.g. permit partial-credit property tests instead of a single JSONL),
  (b) pivot away from artifact grading for certain categories, or (c)
  proceed despite collapse with a recorded caveat.

## 4. Alternatives considered

- **Wall-time delta as the primary signal.** Rejected: wall time is dominated
  by model latency and API jitter, not workflow structure. A 10× faster arm
  could still be doing the same workflow.
- **Requiring a pass/fail delta between arms.** Rejected as above — this is
  separation analysis, not trace analysis, and belongs to a later epic.
- **Requiring A1 to hold strictly (no A2 tie-break).** Rejected because strict
  multiset equality is achievable by two genuinely divergent arms that both
  happen to call `execute_code` the same number of times (e.g. both arms
  ran one `execute_code` for the same reason but very different code). The
  A2 escape clause catches "same tools, but the code itself differs" via
  the content of tool arguments in a future extension.
- **Requiring all three signals.** Rejected: the epic frames the gate as
  "non-identical traces," and Signal A alone captures that. Requiring B and
  C adds noise without strengthening the primary claim.

## 5. Open items

- The `tools/arm_collapse_check.py` implementation lands either alongside
  `tools/verify_graders.py` in slice #96, or as a small dedicated PR. This
  ADR is the source of truth for what that script must compute.
- After the first execution of the gate on `p95_latency_easy`, append a
  short postscript to this ADR recording the observed verdict (GO / AMBER /
  NO-GO) and the signal values. That record is what the user ratifies.

## 6. Ratification

Per epic Open Q #6, the intent holder must ratify this gate definition
before the second seed task (`algorithmic__*_easy`) is decomposed. A
ratification comment on epic #92 or on the PR introducing this ADR is
sufficient; no code change is required after ratification unless the
signals or thresholds are adjusted.
