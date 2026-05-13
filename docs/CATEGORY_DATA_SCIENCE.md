# Category: data_science

## What this category tests

Data science tasks represent the analytical and statistical work that sits between raw data and a decision: compute a metric, detect an anomaly, characterize a distribution, or chain a few analytical steps into a pipeline. The agent receives a dataset and a problem statement that specifies the analytical question and — critically — the method to apply. The output is a number, a flagged row set, a classification decision, or a small structured record summarizing pipeline results.

## Why these tasks belong in the benchmark

The rubric review found only 4 tasks labeled `data_science` across the entire corpus, all in `data_processing/`, all scoring ≥8/15. These tasks demonstrate that analytical work with clear output contracts grades cleanly and resembles real delegation. The category extends this pattern to statistical analysis, metric computation, and anomaly detection — workflow pieces a practitioner would hand off with a short spec rather than doing themselves.

The work is authentically delegable when the method is specified. "Compute the 7-day rolling P95 of response_time_ms, flag any day where it exceeds 200ms for 3 consecutive days" is a realistic analyst request. The agent's judgment is applied to implementation, not to problem framing.

## Task archetypes

**Metric computation from predictions.** Given a predictions CSV and a labels CSV, compute a specified set of classification or regression metrics (precision, recall, F1, RMSE, MAE) at a specified threshold or aggregation level. Grader checks floats within tolerance.

**Anomaly flagging under a specified rule.** Given a time series or tabular dataset, identify rows or windows that violate a stated criterion (IQR method with specified factor, z-score above threshold, consecutive-period change above percentage). The problem statement names the method explicitly. Grader checks the flagged set against reference.

**Cohort comparison.** Given two or more groups in a dataset, compute a specified statistical test (t-test, Mann-Whitney U) and report the statistic, p-value, and accept/reject decision at a stated α. Grader checks the decision and spot-checks the statistic within tolerance.

**Rolling or window aggregation.** Given a time-indexed dataset, compute a rolling or expanding aggregate (mean, median, sum, percentile) at a specified window size and output the annotated series. Grader checks values within floating-point tolerance.

**Multi-step analytical pipeline.** Given a dataset, chain three or more sequential analytical steps where each step depends on the previous result (e.g. split → fit → evaluate; correlate → select → fit; fit → flag outliers → refit). The problem statement names every step, parameter, and stopping condition. Output is a small structured JSON record (coefficients, selected feature list, iteration count, final metric). Grader recomputes the pipeline and compares field-by-field. This archetype was chosen — over an earlier "structured summary report" — because its iterative variants stress the persistent-kernel mechanism: code that keeps a working DataFrame hot across many small computations gains over arms that pay per-call overhead.

## Grading approach

Tasks grade a numeric value, a flagged row set, or a small structured record. For numeric outputs: tolerance is ±1e-4 unless the task involves percentile or rank statistics, where ±0.01 is appropriate. For flagged row sets: grader checks exact match against the reference set (the problem statement specifies the method, so there is only one correct answer). For structured records (multi-step pipeline outputs): the grader recomputes the full pipeline and compares each field with its appropriate check (exact int, exact set, float ±1e-4). Scoring is all-or-nothing — score = 1.0 iff every field passes, else 0.0 — consistent with the category's "method fully specified → one correct answer" principle.

The grader must handle the case where the agent applies the right method but on a subtly wrong column or at a wrong aggregation level — these should fail rather than pass approximately.

## Limitations

**Method must be fully specified in the problem statement.** This is the central constraint for this category. Any task where the "correct" output depends on a method choice that the problem statement leaves open becomes ungradeable — different valid implementations produce different numbers. Every task must name the algorithm, the parameters, and the output format. This makes tasks feel slightly more prescriptive than real analytical requests, which sometimes leave method to the analyst's judgment.

**No model training or fitting beyond scipy/sklearn on CPU.** Tasks may involve fitting a simple regression, computing a decision boundary, or running a statistical test using scipy or scikit-learn. They may not involve training a neural network, tuning a deep model, or any GPU-dependent path. This rules out common DS tasks like "train a classifier on this dataset" — the output of training is stochastic and the grader cannot reliably check it.

**Stochastic outputs require seeding.** Any task that calls a function with randomness (e.g. train/test split, KMeans initialization) must specify `random_state=42` or equivalent in the problem statement. The grader checks the output of a seeded run; unseeded outputs are not gradeable.

**Visualization is out of scope.** The realism checklist bans visualization libraries. Tasks that would naturally produce a plot as their output must instead produce a structured numeric summary. This is a real limitation — a practitioner might expect a chart, but the grader cannot evaluate visual outputs.
