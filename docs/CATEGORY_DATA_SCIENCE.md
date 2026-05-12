# Category: data_science

## What this category tests

Data science tasks represent the analytical and statistical work that sits between raw data and a decision: compute a metric, detect an anomaly, characterize a distribution, or produce a structured summary. The agent receives a dataset and a problem statement that specifies the analytical question and — critically — the method to apply. The output is a number, a flagged row set, a classification decision, or a structured report file.

## Why these tasks belong in the benchmark

The rubric review found only 4 tasks labeled `data_science` across the entire corpus, all in `data_processing/`, all scoring ≥8/15. These tasks demonstrate that analytical work with clear output contracts grades cleanly and resembles real delegation. The category extends this pattern to statistical analysis, metric computation, and anomaly detection — workflow pieces a practitioner would hand off with a short spec rather than doing themselves.

The work is authentically delegable when the method is specified. "Compute the 7-day rolling P95 of response_time_ms, flag any day where it exceeds 200ms for 3 consecutive days" is a realistic analyst request. The agent's judgment is applied to implementation, not to problem framing.

## Task archetypes

**Metric computation from predictions.** Given a predictions CSV and a labels CSV, compute a specified set of classification or regression metrics (precision, recall, F1, RMSE, MAE) at a specified threshold or aggregation level. Grader checks floats within tolerance.

**Anomaly flagging under a specified rule.** Given a time series or tabular dataset, identify rows or windows that violate a stated criterion (IQR method with specified factor, z-score above threshold, consecutive-period change above percentage). The problem statement names the method explicitly. Grader checks the flagged set against reference.

**Cohort comparison.** Given two or more groups in a dataset, compute a specified statistical test (t-test, Mann-Whitney U) and report the statistic, p-value, and accept/reject decision at a stated α. Grader checks the decision and spot-checks the statistic within tolerance.

**Rolling or window aggregation.** Given a time-indexed dataset, compute a rolling or expanding aggregate (mean, median, sum, percentile) at a specified window size and output the annotated series. Grader checks values within floating-point tolerance.

**Structured summary report.** Given a dataset, produce a JSON or CSV summary with specified fields (per-group row counts, null rates, value distributions). The output schema is fully specified in the problem statement. Grader checks schema compliance and spot-checks values.

## Grading approach

Tasks grade a numeric value, a flagged row set, or a structured file. For numeric outputs: tolerance is ±1e-4 unless the task involves percentile or rank statistics, where ±0.01 is appropriate. For flagged row sets: grader checks exact match against the reference set (the problem statement specifies the method, so there is only one correct answer). For structured files: grader checks schema and spot-checks values.

The grader must handle the case where the agent applies the right method but on a subtly wrong column or at a wrong aggregation level — these should fail rather than pass approximately.

## Limitations

**Method must be fully specified in the problem statement.** This is the central constraint for this category. Any task where the "correct" output depends on a method choice that the problem statement leaves open becomes ungradeable — different valid implementations produce different numbers. Every task must name the algorithm, the parameters, and the output format. This makes tasks feel slightly more prescriptive than real analytical requests, which sometimes leave method to the analyst's judgment.

**No model training or fitting beyond scipy/sklearn on CPU.** Tasks may involve fitting a simple regression, computing a decision boundary, or running a statistical test using scipy or scikit-learn. They may not involve training a neural network, tuning a deep model, or any GPU-dependent path. This rules out common DS tasks like "train a classifier on this dataset" — the output of training is stochastic and the grader cannot reliably check it.

**Stochastic outputs require seeding.** Any task that calls a function with randomness (e.g. train/test split, KMeans initialization) must specify `random_state=42` or equivalent in the problem statement. The grader checks the output of a seeded run; unseeded outputs are not gradeable.

**Visualization is out of scope.** The realism checklist bans visualization libraries. Tasks that would naturally produce a plot as their output must instead produce a structured numeric summary. This is a real limitation — a practitioner might expect a chart, but the grader cannot evaluate visual outputs.
