# Task Appropriateness Rubric (v1)

**Purpose.** External-reviewer rubric for judging whether an artifact-graded task in `problems/artifact/` represents the kind of **delegable subtask** a practicing data analyst, data scientist, or ML engineer would actually hand off to an agent. Distinct from `TASK_REALISM_CHECKLIST.md`, which is the *author's* self-cert during task creation. This rubric is applied by a fresh reviewer (human or subagent) who did not write the task.

**Motivation.** The onlycodes benchmark currently shows the code-only arm winning on every artifact task. A skeptical reader (see issue #158, MVP-2) will ask: *are these tasks doing the kind of work a DS/DA practitioner actually delegates, or are they scientific-computing / pure-algorithm puzzles that happen to be written in Python?* This rubric is the instrument we use to answer that question per-task, then aggregate into a defensible regime figure.

## Scope: delegated DS/DA subtasks

A practitioner does **not** hand an agent the entire job ("load → explore → clean → transform → model → report"). They hand off a **slice** of it. The rubric judges whether each task looks like a plausible slice.

A task is **in scope** if it resembles work a DS/DA practitioner would realistically delegate to an agent:

- Compute a metric / aggregate / percentile from log or tabular data.
- Clean / join / reshape / dedupe a specific dataset to a specified spec.
- Detect outliers, anomalies, or regressions in a series under a defined rule.
- Fit a *specified* model or run a *specified* test on prepared data.
- Validate, parse, or extract structured information from a known-format input.
- Produce a small report artifact (top-K, summary stats, predictions) from prepared inputs.

The DS already decided what they want; they are delegating the **execution** of a well-scoped slice. A scalar answer is a perfectly normal deliverable for a delegated subtask — do not penalize narrow scope.

Work **out of scope** (would not realistically be delegated as a DS/DA subtask):

- Combinatorial enumeration / exhaustive search of mathematical objects.
- Implementing a textbook algorithm from spec where no data-flavored input exists (knapsack, TSP, vertex cover on abstract inputs).
- Pure numerical-method implementation on a known objective where the data is incidental.
- Parser / state-machine / verification work where the input is a synthetic puzzle, not data.

A task can be a perfectly good benchmark task and still score low on this rubric — that's the point. The rubric measures *one* property (delegated-DS-subtask fit), not overall quality.

## How to use this document

1. The reviewer reads `task.yaml`, `prompt.md`, the entire `workspace/` directory, and `grader/hidden.py`. The reviewer does **not** read `reference_output.*`.
2. The reviewer scores the task on the six axes below (0–3 each). The 0–3 anchors are concrete; do not interpolate.
3. The reviewer assigns one categorical **workload label** (see §Workload Labels).
4. The reviewer writes a one-paragraph **verdict** (≤ 120 words) explaining the scores and label, citing specific files / lines from the task.
5. Output is emitted as structured JSON (see §Output Schema) so downstream aggregation is mechanical.

## Scoring axes

Each axis is scored 0, 1, 2, or 3. Anchors:

### A1. Workflow shape (0–3)

Does the task look like a recognizable **slice** of a DS workflow — load / inspect / clean / transform / aggregate / model / summarize? A high score does not require the full pipeline; it requires that the slice is recognizable and substantive.

- **0** — No data-shaped input at all. The "input" is an abstract mathematical object (a graph, a list of integers, a problem specification). Nothing to load, inspect, or shape. *Note: loading from a JSON or CSV file does not by itself promote the score — what matters is whether the content is a domain-shaped record (rows with named columns representing real entities) or an abstract mathematical object (weights, values, adjacency lists, etc.).*
- **1** — Trivially shaped input that goes straight into a single computation. Load + one-line compute + return. No reading, joining, reshaping, or aggregation worth the name.
- **2** — Recognizable slice of a DS workflow: load + at least one shaping / aggregating / filtering / fitting step that a practitioner would describe as "the analysis". A scalar or small structured return is fine.
- **3** — Same as 2, but the slice involves multiple coordinated steps (e.g. join across files, then aggregate, then rank; or clean + transform + fit) such that an analyst would naturally describe the work in stages.

### A2. Data realism (0–3)

How closely does the input data resemble data a practitioner sees on the job?

- **0** — Toy / abstract input (a list of integers, a graph adjacency, a scalar). No domain shape.
- **1** — Synthetic but domain-flavored (e.g. fake latency numbers in JSONL, no messiness).
- **2** — Synthetic with realistic schema and at least one common messiness (missing values, mixed dtypes, duplicate keys, schema drift, multi-file).
- **3** — Looks like a real export from a real system: realistic distributions, multiple messiness sources, schema you would have to inspect to understand.

### A3. Decision content (0–3)

How much execution judgment does the agent need to apply? Note that **delegation usually comes with a dictated approach** — the practitioner has already decided which method they want, and the agent's job is faithful execution under that spec. Score this axis on *execution-time* judgment, not methodological autonomy.

- **0** — The "task" is so abstract that no judgment about real data is involved. Just implement an algorithm on abstract inputs (weights, values, graph edges, combinatorial objects). If A1 is 0, A3 is almost always 0.
- **1** — Faithful execution of a specified method on specified data. The agent must read the spec carefully and translate it to code, including handling the schema correctly and respecting tolerances / edge-case rules stated in the prompt.
- **2** — Specified method, but the agent has to handle real shaping decisions: which rows count, how to break ties, how to handle missing or malformed entries that the spec didn't fully pin down.
- **3** — Multiple substantive decisions the prompt leaves open: choice of join strategy, fillna policy, model family, significance test, or scoping what "the answer" even means.

### A4. Domain authenticity (0–3)

Does the prompt read like something a working practitioner would hand off (ticket / Slack / memo / DM), and does the success criterion map to a real business / research / engineering question?

- **0** — Textbook exercise or coding-interview framing. Pure math/algorithm phrasing, abstract inputs, no domain. A practitioner would not phrase any handoff this way.
- **1** — Thin domain veneer over an algorithmic / mathematical core. The "business framing" is window-dressing; the underlying ask is still abstract.
- **2** — Plausible handoff: domain-appropriate names, a recognizable ask, a deliverable shape a colleague would actually use.
- **3** — Indistinguishable from a real handoff: a specific stakeholder context, a concrete deliverable that maps to a known DS/DA work product, named entities/columns that match how a practitioner would actually describe their data.

### A5. Tool-surface relevance (0–3)

Would the IDE tool surface (Read, Grep, Glob, Edit, Write, Bash) actually be useful for a practitioner solving this task, beyond what a single Python REPL offers? **This axis matters for the paper's stratification claim.** Low scores here are where code-only is expected to win trivially.

- **0** — Single in-memory computation. IDE tools have nothing to grip on. Pandas inside Python REPL is strictly sufficient.
- **1** — Multi-file workspace but minimal navigation; a `glob` + read-all into pandas covers it.
- **2** — Genuine need to inspect schema across several files, grep for a column name, or skim large logs before computing.
- **3** — Repeated exploration: jump between files, search for usages, edit a small helper, iterate on a partial result. Tools would offer real ergonomic value.

### A6. Artifact type (0–3)

Does the output shape match what a downstream consumer would actually use? A scalar can be a perfectly good delegated deliverable; this axis rewards *fit-for-purpose*, not size.

- **0** — Output shape would not be directly useful to any downstream consumer: e.g. a list of mathematical objects (all Latin squares), an enumeration result, an algorithmic optimum on abstract inputs.
- **1** — A specific answer to a specific question, in a shape a colleague could paste into a doc or feed into the next step: a scalar metric, a model parameter set, a small key/value JSON.
- **2** — A small structured deliverable a downstream pipeline would consume: top-K records, per-group summary stats, classified rows, a cleaned subset.
- **3** — A multi-part deliverable matching a recognizable DS work product: e.g. a cleaned dataset plus a summary, or predictions plus a diagnostic, or a report-shaped JSON with grouped findings.

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

- **Do not penalize narrow scope.** A well-scoped delegated subtask returning a scalar is a 1 or 2 on A1/A6, not a 0. The rubric rewards "looks like a real handoff", not "looks like the whole job of a data scientist".
- **Do not penalize dictated methodology.** Delegation usually comes with a specified method. Score A3 on the agent's execution-time judgment, not on how much methodological autonomy the prompt offers.
- Do not score generously to be polite. The point is to surface gaps where they exist (mainly A2 data realism and A4 domain authenticity for our corpus).
- Do not let the `category/` directory name bias the label. Read the task.
- A task scoring high on A5 (tool-surface relevance) is *not* automatically a better task — it just means it's a harder test of the code-only hypothesis. That's a feature, not a flaw.
- If you cannot justify a score by pointing at a file or line, your confidence is `low`, not `high`.
- The verdict is **for the paper**. Write it like a reviewer comment, not a code review.

## Change history

- **v1 (current).** Reframed scope from "full DS/DA workload" to "delegated DS/DA subtask" after a 4-task pilot revealed the original framing systematically under-scored well-scoped narrow tasks (e.g. compute-a-metric-from-logs) that a practitioner would in fact delegate to an agent. A1, A3, A4, A6 anchors recalibrated; A2 and A5 unchanged. The pilot scores from the pre-recalibration draft are not directly comparable to v1 scores and should be re-run before reporting.
