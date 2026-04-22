# SCHEMA_ARTIFACT — Artifact-Graded Task Schema (v1)

**Status:** Frozen for epic #92 (Artifact-Graded Diagnostic Benchmark). Load-bearing: the harness (#2) and all seed-task slices (#3, #5–#10) derive from this document.

**Audience:** Task authors drafting a new `problems/artifact/<category>/<slug>/` directory; harness implementers writing the loader; reviewers checking a task PR.

**Scope:** This document is normative for the on-disk layout of a task, the `task.yaml` manifest, the `grade()` contract, and the materialization/leakage rules. It does NOT specify the CLI surface for running the benchmark — that is tracked as Open Question #1 in the epic and will land via the harness slice (#2) plus ADR `docs/adr-0001-artifact-mode.md`.

---

## 1. Directory Layout

Every task lives under `problems/artifact/<category>/<slug>/` in the `onlycodes` repo. The directory is self-contained: no external clones, no HuggingFace fetches, no network access at task-run time.

```
problems/artifact/<category>/<slug>/
    task.yaml                 # manifest — REQUIRED, parsed by the harness
    prompt.md                 # natural-language spec shown to the agent — REQUIRED
    workspace/                # starter inputs — REQUIRED (may be empty)
        <task-specific files> # e.g. access.jsonl, package.json, source/**
        verify.py             # PUBLIC structural verifier — OPTIONAL
    grader/                   # HARNESS-ONLY — never materialized into agent scratch
        hidden.py             # REQUIRED — exposes grade(scratch_dir) -> GradeResult
        reference_output.*    # REQUIRED — sanity-check artifact (not graded at run time)
sets/
    seed-v1.txt               # curated task-id list; one instance_id per line, # comments ok
```

**Filenames.** The following filenames are **enforced** (the harness looks for them by name):

- `task.yaml` (manifest)
- `prompt.md` (problem statement — path may be overridden in `task.yaml`, but convention is `prompt.md`)
- `workspace/` (directory)
- `grader/hidden.py` (module; must define `grade`)

The following filenames are **conventional** (chosen by the task author, declared in `task.yaml`):

- Anything inside `workspace/` (the task author picks names for inputs and for `verify.py` if present)
- `output_artifact` path (agent writes here; may be `output/p95.jsonl`, `answer.txt`, etc.)
- `grader/reference_output.*` extension (matches the artifact format)

---

## 2. `task.yaml` Schema (v1)

### 2.1 Full example (canonical)

```yaml
instance_id: data_processing__p95_latency_easy
category: data_processing
difficulty: easy
problem_statement: prompt.md
workspace_dir: workspace/
output_artifact: output/p95.jsonl
structural_verifier: workspace/verify.py   # optional
hidden_grader: grader/hidden.py
reference_output: grader/reference_output.jsonl
execution_budget:
  max_code_runs: 0          # 0 = unlimited (see §2.3)
  max_wall_seconds: 0       # 0 = unlimited
tags: [aggregation, jsonl]
```

### 2.2 Field reference

| Field | Required? | Type | Description |
|---|---|---|---|
| `instance_id` | **required** | string | Globally unique, stable. Format: `<category>__<slug>` (two underscores). Must match `^[a-z][a-z0-9_]*__[a-z0-9_]+$`. Stable across re-grades — do not rename. If a task is replaced with a different problem shape, allocate a new `instance_id` instead of reusing. |
| `category` | **required** | string | One of the six canonical categories: `data_processing`, `algorithmic`, `verification_heavy`, `enumeration`, `stateful_reasoning`, `iterative_numerical`. Must equal the `<category>` segment of `instance_id`. |
| `difficulty` | **required** | string | One of: `easy`, `medium`, `hard`. Author's self-assessment against `docs/TASK_REALISM_CHECKLIST.md`; the seed-v2 ladder targets 2 easy / 3 medium / 3 hard per category. |
| `problem_statement` | **required** | string (relative path) | Path to the natural-language prompt shown to the agent. Convention: `prompt.md`. Resolved relative to the task directory. The file's entire contents are placed verbatim into the agent's problem prompt. |
| `workspace_dir` | **required** | string (relative path) | Directory copied into the agent's scratch dir at run time. Convention: `workspace/`. May be empty (rare — e.g. pure-enumeration tasks that need no input files) but the field must still be declared. |
| `output_artifact` | **required** | string (relative path) | Path, **relative to the scratch dir**, that the agent MUST write. The grader reads from `scratch_dir / output_artifact`. Parent directories are created by the agent, not pre-created by the harness. |
| `structural_verifier` | optional | string (relative path) | Path to a PUBLIC Python module the agent MAY import. Convention: `workspace/verify.py`. Omit the field entirely when the task ships no verifier. See §4. |
| `workspace_generator` | optional | string (relative path) | Path to a Python script that writes bulk workspace data into the agent's scratch dir at materialize time, instead of committing the data to git. Convention: `workspace/generator.py`. When set, the script itself is EXCLUDED from the scratch copy (the agent never sees it) and is invoked as a subprocess with `--seed <derived>`, `--output-dir <scratch>`, `--instance-id <id>`. A marker file (`.workspace_generator_done`) makes `materialize()` idempotent across repeated calls on the same scratch. See §5.1. |
| `hidden_grader` | **required** | string (relative path) | Path to the grader module. Convention: `grader/hidden.py`. The module MUST define `grade(scratch_dir: Path) -> GradeResult`. See §3. |
| `reference_output` | **required** | string (relative path) | Path to a known-good artifact used by the pre-merge sanity check (see §5). Extension matches the artifact's natural format (`.jsonl`, `.json`, `.txt`, …). |
| `execution_budget.max_code_runs` | **required** | integer ≥ 0 | Max number of `execute_code` invocations the agent may make. `0 = unlimited`. See §2.3. |
| `execution_budget.max_wall_seconds` | **required** | integer ≥ 0 | Max wall-clock seconds for the run. `0 = unlimited`. See §2.3. |
| `tags` | optional | list\[string] | Free-form tags for analysis/filtering. Convention: lowercase, underscored. No semantics enforced by the harness. Omit the field (or use `[]`) when not needed. |

**Unknown fields.** The loader rejects unknown top-level fields with a parse error. This keeps the schema tight during seed; future additive fields require a schema revision bump.

**Path resolution.** Every `*_dir`, `*_verifier`, `*_grader`, `problem_statement`, `output_artifact`, and `reference_output` path is resolved relative to the task directory (i.e. the directory containing `task.yaml`), EXCEPT `output_artifact`, which is resolved relative to the agent's scratch dir at run time.

### 2.3 Execution budgets: `0 = unlimited`

Both `max_code_runs` and `max_wall_seconds` accept `0` as a sentinel meaning "no limit". This is the intended default for seed-v1 tasks: we do not yet know what reasonable caps are for any seed task, so guessing now would manufacture false failures.

**Behavior in this epic:** The harness reads both fields, stores them on the run record for later analysis, and **does not enforce them**. Any non-zero value is treated the same as `0` for enforcement purposes in seed-v1.

**Future enforcement:** A follow-up epic will flip the enforcement switch. At that point, a non-zero value becomes a hard cap (run terminated with a budget-exceeded outcome). Authors MAY set non-zero values today as forward-looking hints, but they will not fire until enforcement ships.

Rationale: wiring the fields now means a later "turn enforcement on" change is a single harness patch, not a sweep through every task manifest.

---

## 3. Grader Contract

### 3.1 Signature

Every `grader/hidden.py` MUST define exactly one public function:

```python
from pathlib import Path
from dataclasses import dataclass

@dataclass(frozen=True)
class GradeResult:
    passed: bool           # binary pass/fail — the headline result
    score: float           # in closed interval [0.0, 1.0]
    detail: str            # short human-readable explanation (≤ 500 chars; no secrets)

def grade(scratch_dir: Path) -> GradeResult:
    ...
```

The harness (#2) will ship the `GradeResult` dataclass as part of its implementation; graders MAY either import it from the harness once that module exists, or define an identically-shaped local dataclass and return an instance of it. The harness treats any object with `passed: bool`, `score: float`, and `detail: str` attributes as a valid return value (structural typing).

### 3.2 Invariants on `grade()`

All of the following are ABSOLUTE requirements — a grader that violates any of them is considered broken and MUST NOT land:

1. **Determinism.** Given the same `scratch_dir` contents, `grade()` returns the same `GradeResult` on every invocation. No wall-clock reads, no `time.time()`, no `datetime.now()`, no `random.random()` without a fixed seed.
2. **Offline.** No network I/O. No `urllib`, `requests`, `socket`, subprocess calls to `curl`/`wget`/`git fetch`, etc.
3. **Seeded randomness.** If the grader uses randomness (e.g. for sampled property tests), the RNG MUST be seeded from the task's `instance_id`. Recommended:
   ```python
   import hashlib, random
   seed = int(hashlib.sha256(b"<instance_id>").hexdigest()[:16], 16)
   rng = random.Random(seed)
   ```
   Hard-coded `instance_id` in the grader is fine because the grader lives next to the task.
4. **No clock dependence.** No branches on current date, timezone, or elapsed time.
5. **Read-only on scratch_dir.** The grader SHOULD NOT modify files in `scratch_dir`. (Not enforced by the harness, but mutation makes re-grading non-reproducible.)
6. **Cheap.** Graders should complete in seconds, not minutes. No full pytest runs, no subprocess compilation cascades. A grader that needs to execute the agent's artifact (e.g. run 30 property tests against the agent's implementation) MAY do so, but the total grader wall-time SHOULD stay under 60 seconds on a 2-core developer machine.

### 3.3 Semantics of `passed` vs. `score`

- `passed` is the binary headline used by per-category summary tables.
- `score ∈ [0, 1]` is a graded sub-signal for analysis. For binary-grade tasks, `score = 1.0 if passed else 0.0`. For partial-credit tasks (e.g. "14 of 15 property tests pass"), `score = fraction_passed` and `passed = (score >= threshold)` with the threshold baked into the grader.
- `detail` is for humans reading the results log. It MUST NOT leak the reference answer or the correctness criterion in full — a task author reviewing a failed run should be able to see *what kind of thing went wrong* without the grader dumping the golden output. Examples of acceptable `detail`: `"missing endpoint /api/v2/users"`, `"p95 off by > 5% on 3 of 12 endpoints"`. Not acceptable: `"expected 42, got 41"` if the reference value is itself the answer.

### 3.4 Failure modes the grader MUST handle gracefully

The grader receives `scratch_dir` as-is after the agent's run — it may contain a malformed artifact, the wrong file, or no file at all. `grade()` MUST NOT raise on agent-caused failures; instead return `GradeResult(passed=False, score=0.0, detail="<what went wrong>")`. Specifically:

- Missing `output_artifact` → `passed=False, detail="output artifact not produced"`.
- Malformed JSON/JSONL/etc. → `passed=False, detail="output artifact failed to parse: <error>"`.
- Empty output → `passed=False, detail="output artifact is empty"`.
- Wrong shape (missing required keys, wrong types) → `passed=False, detail="..."`.

Exceptions raised from `grade()` are bugs in the grader and are surfaced by the harness as infrastructure errors, NOT as task failures.

---

## 4. Public Structural Verifier (`workspace/verify.py`)

When present, `verify.py` is a Python module the agent MAY import from its scratch dir to sanity-check the *shape* of its output before finalizing. It is declared in `task.yaml` as `structural_verifier: workspace/verify.py` and is copied into the scratch dir along with the rest of `workspace/`.

### 4.1 What the verifier MAY check

Structural properties only:

- Schema: required keys present, no unknown keys.
- Shape: correct number of rows/entries, non-empty.
- Types: values match declared types (`int`, `float`, `str`, lists of the right element type).
- Bounds: non-negative, within a stated range, sorted, unique.
- Format: valid JSON/JSONL/CSV, UTF-8, trailing newline if the format requires one.

### 4.2 What the verifier MUST NOT check

Anything that leaks correctness:

- No comparison against reference values.
- No numerical tolerance checks against a golden answer.
- No "is this the right answer" logic of any kind.

If a task author needs to decide whether a check is structural or correctness-revealing, the test is: **could a trivial-but-wrong artifact pass the verifier?** If yes, it's structural and belongs in `verify.py`. If no, it belongs in `grader/hidden.py`.

### 4.3 Convention

`verify.py` SHOULD expose a `verify(artifact_path: Path) -> None` that raises `AssertionError` with a helpful message on failure and returns `None` on success. Agents are not required to call it, and not calling it is not a grading signal.

---

## 5. No-Leak Materialization Rule

This section is the authoritative answer to the reviewer question *"which files does the agent see and which are hidden?"*.

### 5.1 Materialized into the agent's scratch dir (visible to the agent)

- Every file under `workspace/`, copied recursively, preserving structure,
  **except** the file declared in `workspace_generator` (when set).
- When `workspace_generator` is set, that script is invoked as a subprocess
  after the copy, with `cwd=scratch_dir` and a derived `--seed`. It writes
  the bulk data files (e.g. `access.jsonl`, 48× `metrics_*.jsonl`) directly
  into the scratch dir. The generator script itself never lands in scratch;
  the agent sees only the generated data plus the small hand-curated files
  that were copied. A `.workspace_generator_done` marker is written on
  success so repeat calls on the same scratch dir are no-ops.
- The task's `prompt.md` contents are embedded in the agent's initial problem prompt; the file itself is NOT copied into the scratch dir (but a curious agent reading its own prompt sees the same text).

Nothing else.

**Determinism.** The seed is `int(sha256(instance_id)[:8], 16)` — stable
across Python versions and across hosts. A given `instance_id` always
materializes to the same bytes, which is the contract the `reference_output.*`
sanity check relies on.

**Generator execution contract.** Generator scripts are invoked with a
deliberately scrubbed environment — only `PATH` and `PYTHONDONTWRITEBYTECODE`
are passed through. `VIRTUAL_ENV`, `PYTHONPATH`, and similar are NOT
forwarded. Consequently, generators MUST use only the Python standard
library (``random``, ``json``, ``hashlib``, ``pathlib``, …). Third-party
dependencies are not available. If a future task genuinely needs a
third-party package, widen this contract explicitly — do not add
environment fallbacks case-by-case.

**Sentinel file.** A hidden marker file ``.workspace_generator_done`` is
written inside the scratch dir after a successful generator run to make
repeated `materialize()` calls idempotent. It is benign and carries no
task-relevant information; agents may safely ignore it.

### 5.2 NEVER materialized (never visible to the agent, in any arm)

- The entire `grader/` directory, including `hidden.py` and `reference_output.*`.
- The `task.yaml` manifest.
- Sibling tasks' directories.
- Any repo-level files outside the task directory.

### 5.3 Enforcement

The harness (#2) is responsible for the copy step and for ensuring no grader path is reachable from the scratch dir (no symlinks, no parent-dir traversal artifacts). The `code_only` arm's sandbox PYTHONPATH resolution is tracked as epic Open Question #2 and will be pinned in `docs/adr-0001-artifact-mode.md` when the harness lands.

The invariant "no golden solution or correctness signal is ever visible to the agent" is a hard epic invariant (see #92). Any task author who finds themselves needing to reference `grader/` or `reference_output` from inside `workspace/` has a bug — the task is miscategorized and needs re-shaping.

### 5.4 Pre-merge sanity check

Before a task PR lands, a harness utility runs the task's `reference_output` through its `grade()` function and asserts `passed=True, score=1.0`. This catches graders that reject their own known-good answer — the single most common silent-failure mode.

This sanity check is run by the harness slice (#2); task authors MAY run it locally once the harness lands by invoking the sanity-check entry point on their task directory.

---

## 6. `instance_id` Format and Stability

### 6.1 Format

`instance_id` = `<category>__<slug>` (exactly two underscores separating the two parts).

- `<category>` is one of the six canonical categories, lowercase.
- `<slug>` is `[a-z0-9_]+`, chosen by the task author. Convention: `<topic>_<difficulty>` (e.g. `p95_latency_easy`, `lru_cache_impl_medium`). Difficulty may be elided from the slug when the category has only one task at that difficulty in seed-v1, but including it is harmless and more explicit.

Full regex: `^[a-z][a-z0-9_]*__[a-z0-9_]+$`.

### 6.2 Stability

`instance_id` MUST be stable across:

- Re-grades (the same task, same inputs, same grader → same `instance_id`).
- Grader bugfixes (fixing a grader that was too lenient does NOT change the `instance_id`).
- Prompt clarifications that do not change the task's intent.

`instance_id` MUST change (allocate a new one) when:

- The task's intent changes (different question, different winning condition).
- The workspace inputs are materially swapped (different dataset, different starter files).

### 6.3 No version suffix (epic decision)

Open Question #1 of this child asked whether `instance_id` should carry a version suffix (`..._v2`) for future re-grades. **Decision:** no suffix in seed-v1. Rationale: re-grading is an operational concern handled by the `run_id` dimension in results, not a task-identity concern. If a future epic needs to ship a second version of a task while keeping the first in-corpus, we allocate a fresh `instance_id` (different slug) rather than bolting on a version axis. This keeps the primary key one-dimensional and analysis-friendly.

If this decision is revisited, update this section in-place and flag the change in the PR description.

---

## 7. Curated Sets

Sets live at `sets/<name>.txt`. Each file is a plain-text list of `instance_id`s, one per line. Blank lines and `#`-prefixed comments are ignored. The harness resolves each line to its task directory by grepping `problems/artifact/**/task.yaml` for the matching `instance_id`.

Seed-v1 ships a single set: `sets/seed-v1.txt` containing the 12 seed `instance_id`s.

Adding a new set is a file-creation operation — no harness change needed.

---

## 8. Summary Checklist for Task Authors

A new task is ready to merge when all of the following are true:

- [ ] Directory exists at `problems/artifact/<category>/<slug>/`.
- [ ] `task.yaml` parses, every required field is present, no unknown fields.
- [ ] `instance_id` matches `^[a-z][a-z0-9_]*__[a-z0-9_]+$` and its category prefix matches the `category` field.
- [ ] `prompt.md` exists and describes the task without leaking the answer.
- [ ] `workspace/` contains every input file the agent needs; no file > 10MB; total ≤ 50MB.
- [ ] `workspace/verify.py`, if present, does structural checks only (test: would a trivial-wrong artifact pass?).
- [ ] `grader/hidden.py` defines `grade(scratch_dir) -> GradeResult`, is deterministic, offline, and seeds randomness from `instance_id`.
- [ ] `grader/reference_output.*` exists and is known-good.
- [ ] The grader returns `passed=True, score=1.0` on the reference output (sanity check).
- [ ] `execution_budget.max_code_runs` and `max_wall_seconds` are declared (`0` is fine for seed-v1).
- [ ] Nothing in `workspace/` references `grader/` or `reference_output` by path or name.

---

## 9. Open Items Deferred to the Harness Slice (#2)

These items are intentionally NOT specified here because they are harness-implementation concerns, not schema concerns:

- The exact CLI surface for running artifact-mode tasks (new subcommand vs. flag on existing `run`). Tracked in `docs/adr-0001-artifact-mode.md`.
- How `grader/` is kept off the agent's PYTHONPATH in the `code_only` arm (sandbox copy vs. path filtering).
- Whether the existing OverlayFS cache layer applies to `workspace/` mounts or a new cache path is introduced.
- Per-run wiring of randomness seed into the grader (whether the harness passes the seed in, or the grader derives it locally from `instance_id`).

If any of these decisions force a schema change, this document is amended and the PR description calls out the amendment.
