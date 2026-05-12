# Category: ml_engineering

## What this category tests

ML engineering tasks represent the experiment management and evaluation work that surrounds model training — not the training itself. The agent receives a workspace containing training logs, experiment result files, configuration files, or prediction outputs, and must extract, compare, or transform that information into a structured artifact. The domain is recognizable ML engineering work; the graded output is a file or computed value, not a trained model.

## Why these tasks belong in the benchmark

The rubric review found zero tasks labeled `ml_engineering` across the entire corpus. This is a gap: the benchmark currently says nothing about whether a code-only agent handles ML workflow pieces differently from a tool-rich agent. Experiment log parsing, metric aggregation across runs, and hyperparameter selection under constraints are routine ML engineering subtasks — bounded, delegable, and output-artifact-graded.

Importantly, some of these tasks are candidates where the tool-rich arm might have an ergonomic advantage. Multi-file log parsing (reading 20 JSON log files and extracting a specific field per run) is easier with filesystem tools than with `execute_code` alone. Including these tasks allows the benchmark to test regime-dependence rather than only confirming code-only wins.

## Task archetypes

**Training log extraction.** A workspace containing 5–20 training log files (one per experiment run) in a consistent format (JSON lines, CSV, or structured text). The agent must extract a specified field per run (e.g. best validation loss, epoch at convergence, wall time) and output a summary CSV. Grader checks extracted values against reference.

**Experiment selection under constraints.** A CSV of experiment results with hyperparameter columns and metric columns. The agent must filter to runs meeting specified constraints (e.g. `val_acc > 0.85 AND params < 10M`) and output the Pareto-optimal set or the single best run. Grader checks the selected row(s) against reference.

**Learning curve analysis.** A CSV or JSON file of per-epoch metrics across one or more runs. The agent must identify a specified feature of the curve: first epoch where improvement drops below a threshold, number of epochs to convergence, epoch of best validation metric. Grader checks the returned epoch number or value.

**Config file transformation.** A workspace containing one or more YAML or JSON config files used for ML training. The agent must apply specified changes (update a field, merge two configs, validate a field against constraints, produce a diff-style summary of changes between two configs). Grader checks the output file or summary against reference.

**Prediction file aggregation.** Multiple per-fold or per-run prediction CSVs. The agent must aggregate them (e.g. average ensemble, majority vote, concatenate with run labels) and output a combined predictions file. Grader checks the aggregated output against reference.

## Grading approach

All tasks grade a file artifact or extracted value. For log extraction and aggregation tasks: grader checks extracted values within floating-point tolerance. For selection tasks: grader checks the exact row set or single row against reference — since constraints are fully specified, there is only one correct answer. For config transformation tasks: grader checks the output file field by field.

The grader must not run any model or training code. It reads only static files in `scratch_dir` and the task's own `grader/` directory.

## Limitations

**No model training or execution.** This is the defining constraint of the category. Tasks cannot ask the agent to train a model, run a forward pass, or evaluate a model on test data — these outputs are stochastic or GPU-dependent. ML engineering as a category is therefore scoped to the *logistics layer* around training: reading outputs, comparing experiments, managing configurations. The most common conception of "ML engineering work" (writing training code, debugging loss curves interactively) is mostly out of scope.

**Code modification tasks are not gradeable here.** A task like "add early stopping to this training loop" cannot be graded by checking a file artifact alone — correctness requires running the modified code against a model. Running a toy sklearn model introduces stochasticity that must be controlled by seeding, and even then the grader is checking model behavior rather than code correctness. Such tasks belong in a code-correctness category with an execution-based grader, not here. Authors who want to test code modification should frame the output as a structural artifact (e.g. "produce a diff or describe the change") rather than a behavioral one.

**Log format must be fully specified.** Experiment log formats vary widely in practice. For the grader to be deterministic, the workspace log format must be defined in the problem statement or inferable from the files. Tasks that require the agent to infer a novel log format without any examples shift from engineering to format-reverse-engineering, which is a different skill.

**File count creates an arm neutrality tradeoff.** Tasks with more input files (e.g. 20 experiment logs) give the tool-rich arm a larger ergonomic advantage — Glob and Read are faster than opening files via `execute_code`. This is intentional: these tasks are designed to test regime-dependence, not to be arm-neutral. Authors should document the expected arm advantage in the task's design notes and ensure the benchmark reports these tasks under a "search-heavy" regime label rather than mixing them with computation-dominated tasks.
