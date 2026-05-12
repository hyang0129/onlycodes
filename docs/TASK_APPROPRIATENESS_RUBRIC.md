# Task Appropriateness Rubric (v1)

**Purpose.** External-reviewer rubric for judging whether an artifact-graded task in `problems/artifact/` represents a workload a practicing **data analyst, data scientist, or ML engineer** would actually encounter. Distinct from `TASK_REALISM_CHECKLIST.md`, which is the *author's* self-cert during task creation. This rubric is applied by a fresh reviewer (human or subagent) who did not write the task.

**Motivation.** The onlycodes benchmark currently shows the code-only arm winning on every artifact task. A skeptical reader (see issue #158, MVP-2) will ask: *are these tasks doing data-science work, or are they scientific-computing / pure-algorithm puzzles that happen to be written in Python?* This rubric is the instrument we use to answer that question per-task, then aggregate into a defensible regime figure.

## Scope of "data analysis / data science workload"

For this rubric, a **DS/DA workload** is work whose primary content is one or more of:

- Ingesting and inspecting tabular / log / event data of non-trivial schema.
- Cleaning, joining, reshaping, or aggregating data.
- Choosing and applying a statistical / ML method to answer a question.
- Producing a report-style artifact (numbers, tables, model predictions) that a stakeholder would consume.

Work that is **not** DS/DA workload (for the purposes of this rubric):

- Combinatorial enumeration / exhaustive search.
- Implementing a textbook algorithm from spec (knapsack, TSP, vertex cover).
- Pure numerical-method implementation (root-finding, gradient descent on a known objective).
- Parser / state-machine / verification work where the data is a means, not the subject.

A task can be a perfectly good benchmark task and still score low on this rubric — that's the point. The rubric measures *one* property (DS/DA fit), not overall quality.

## How to use this document

1. The reviewer reads `task.yaml`, `prompt.md`, the entire `workspace/` directory, and `grader/hidden.py`. The reviewer does **not** read `reference_output.*`.
2. The reviewer scores the task on the six axes below (0–3 each). The 0–3 anchors are concrete; do not interpolate.
3. The reviewer assigns one categorical **workload label** (see §Workload Labels).
4. The reviewer writes a one-paragraph **verdict** (≤ 120 words) explaining the scores and label, citing specific files / lines from the task.
5. Output is emitted as structured JSON (see §Output Schema) so downstream aggregation is mechanical.

## Scoring axes

Each axis is scored 0, 1, 2, or 3. Anchors:

### A1. Workflow shape (0–3)

Does the task force the agent through a recognizable DS workflow (load → inspect → clean / transform → analyze → report)?

- **0** — Single deterministic computation on a pre-shaped input. No load/clean/transform stages.
- **1** — Load + one transform / aggregate. Linear, no decisions about shape.
- **2** — Load + inspect + at least one cleaning or joining decision + aggregate / model.
- **3** — Full pipeline: load multi-source data, reconcile schema, clean, transform, analyze, produce stakeholder-facing artifact.

### A2. Data realism (0–3)

How closely does the input data resemble data a practitioner sees on the job?

- **0** — Toy / abstract input (a list of integers, a graph adjacency, a scalar). No domain shape.
- **1** — Synthetic but domain-flavored (e.g. fake latency numbers in JSONL, no messiness).
- **2** — Synthetic with realistic schema and at least one common messiness (missing values, mixed dtypes, duplicate keys, schema drift, multi-file).
- **3** — Looks like a real export from a real system: realistic distributions, multiple messiness sources, schema you would have to inspect to understand.

### A3. Decision content (0–3)

How much does the agent have to *choose* an approach, versus execute a dictated algorithm?

- **0** — Algorithm is dictated by the prompt or trivially implied (e.g. "compute the p95 of column X").
- **1** — One small decision (which aggregation function, which library call).
- **2** — Multiple decisions: which join, which fillna strategy, which model family, which significance test.
- **3** — Open-ended methodology: the agent must scope what "the answer" even means, then justify a method.

### A4. Domain authenticity (0–3)

Does the prompt read like something a working practitioner would receive (ticket / Slack / memo), and does the success criterion match a real business / research question?

- **0** — Reads like a textbook exercise or coding interview question.
- **1** — Domain-flavored framing but the underlying question is still abstract ("count the latin squares of order 3, presented as a checkerboard analyst would want").
- **2** — Plausible ticket framing, plausible deliverable.
- **3** — Indistinguishable from a real ticket: a stakeholder, a deadline-style ask, a numeric / artifact deliverable that maps to a known DS/DA work product.

### A5. Tool-surface relevance (0–3)

Would the IDE tool surface (Read, Grep, Glob, Edit, Write, Bash) actually be useful for a practitioner solving this task, beyond what a single Python REPL offers? **This axis matters for the paper's stratification claim.** Low scores here are where code-only is expected to win trivially.

- **0** — Single in-memory computation. IDE tools have nothing to grip on. Pandas inside Python REPL is strictly sufficient.
- **1** — Multi-file workspace but minimal navigation; a `glob` + read-all into pandas covers it.
- **2** — Genuine need to inspect schema across several files, grep for a column name, or skim large logs before computing.
- **3** — Repeated exploration: jump between files, search for usages, edit a small helper, iterate on a partial result. Tools would offer real ergonomic value.

### A6. Artifact type (0–3)

How report-shaped is the output?

- **0** — Scalar or fixed-shape JSON answer ("return one number").
- **1** — Small structured output (one JSONL with a fixed schema).
- **2** — Tabular result with multiple derived columns / a small set of summary statistics keyed by group.
- **3** — Multi-part deliverable: cleaned dataset + summary + diagnostic / model artifact. Stakeholder-facing.

## Workload labels

Pick exactly one. These are the labels the paper will use for the regime figure.

- **data_science** — analysis or modeling work that a data scientist / analyst would recognize as their day job. Score profile usually ≥2 on A1, A2, A4.
- **data_engineering** — ETL-shaped work: ingest, reshape, join, validate. Less analytical, more pipeline-shaped. Often high A1 and A2, lower A3.
- **ml_engineering** — model fitting / evaluation / calibration where the *method* is the point.
- **scientific_computing** — numerical methods on well-defined inputs (root-finding, fitting a known model, optimization on a known objective). Often low A2 and A4.
- **algorithmic** — implements a known algorithm (knapsack, TSP, bin packing). Low A2/A3/A4.
- **enumeration** — exhaustive search under a constraint. Low A2/A4.
- **verification** — correctness-critical parsing / state machines / invariant checking. Often low A2/A4, high A3.

A task whose category directory is e.g. `data_processing/` is **not automatically** labeled `data_engineering` — the reviewer judges based on what the task actually does, not its directory.

## Output schema

The reviewer emits one JSON object per task. The aggregator concatenates these into `runs/appropriateness/<run_id>/scores.json`.

```json
{
  "instance_id": "data_processing__p95_latency_easy",
  "scores": {
    "workflow_shape": 1,
    "data_realism": 1,
    "decision_content": 0,
    "domain_authenticity": 2,
    "tool_surface_relevance": 0,
    "artifact_type": 1
  },
  "label": "data_engineering",
  "verdict": "≤120 word paragraph citing specific files and lines.",
  "ds_da_fit": 5,
  "reviewer_confidence": "high"
}
```

Fields:

- `scores` — six 0–3 integers, in the order A1..A6.
- `label` — one of the seven workload labels above.
- `verdict` — short prose, must cite at least one specific file or line from the task.
- `ds_da_fit` — convenience sum of `A1 + A2 + A3 + A4 + A6` (excludes A5 because A5 is about tool surface, not DS-ness). Range 0–15.
- `reviewer_confidence` — `low | medium | high`. Use `low` if the task is ambiguous or the reviewer is guessing.

## Aggregation

The summary report (`runs/appropriateness/<run_id>/report.md`) presents:

1. **Headline counts:** how many of the 48 tasks land in each workload label.
2. **DS/DA fit distribution:** histogram of `ds_da_fit` scores. Median, IQR.
3. **Per-axis means:** the mean score per axis across all tasks, and broken down by `category/` directory.
4. **Outliers:** top-5 highest and lowest `ds_da_fit` tasks, with the reviewer's verdict quoted.
5. **Regime plot data:** for the paper, the (workload_label × ds_da_fit) cross-tab in CSV form.

Aggregation is mechanical — no LLM judgment involved past this point.

## Anti-patterns (reviewer guidance)

- Do not score generously to be polite. The point is to surface gaps.
- Do not let the `category/` directory name bias the label. Read the task.
- A task scoring high on A5 (tool-surface relevance) is *not* automatically a better task — it just means it's a harder test of the code-only hypothesis. That's a feature, not a flaw.
- If you cannot justify a score by pointing at a file or line, your confidence is `low`, not `high`.
- The verdict is **for the paper**. Write it like a reviewer comment, not a code review.
