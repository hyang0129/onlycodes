# Category: data_engineering

## What this category tests

Data engineering tasks represent the ETL and data pipeline work that practitioners routinely delegate: ingest messy inputs, apply deterministic transformations, and produce a clean output artifact (CSV, JSON, Parquet-compatible CSV). The agent receives a workspace containing one or more data files, a problem statement framed as a ticket or DM, and must produce an output file that a downstream consumer could use without further cleaning.

## Why these tasks belong in the benchmark

Data engineering is the highest-confidence DS/DA delegation target in the corpus. The rubric review found the existing 8 `data_processing/` tasks average 10.25/15 on ds_da_fit — the only category above 7. The tasks in this category extend that pattern with harder schemas, multi-file layouts, and realistic messiness that the existing set lacks.

The work is authentically delegable. A practitioner receiving "normalize timestamps across these three event logs and join on session_id, dropping orphan rows" has no reason to do it themselves — it is mechanical, bounded, and verifiable. The output is a file, not a decision.

## Task archetypes

**Multi-file join with schema inconsistency.** Two or more CSVs with the same logical columns but different names, types, or date formats. The agent must reconcile them and produce a merged output. Grader checks row count, key uniqueness, and spot-checks specific values.

**Deduplication under a composite key.** A single file with duplicate records that share a business key but differ on secondary fields (e.g. last_updated timestamp). The agent must apply a specified strategy (keep latest, keep highest-value) and output the deduplicated set. Grader checks exact row set against reference.

**Timestamp normalization.** A file with mixed timestamp formats across rows (ISO-8601, epoch seconds, human-readable strings). The agent must parse and normalize to a single format. Grader checks parsed values within a one-second tolerance.

**Filtered aggregation across files.** Multiple period files (e.g. monthly sales CSVs). The agent must aggregate across files under a filter condition and output a summary table. Grader checks aggregate values within tolerance.

**Schema repair.** A file with known structural problems called out in the problem statement (mixed numeric/string in a column, malformed nulls represented as strings, inconsistent categorical values). The agent must apply the specified repair rules. Grader checks the repaired column distributions.

## Grading approach

All tasks grade a file artifact. The grader loads the agent's output, checks:
- File exists and is parseable
- Expected columns present
- Row count within tolerance (for tasks where row count is determined by filter logic, allow ±0)
- Spot-check of specific cell values or aggregate statistics against the reference output

No statistical tolerance beyond what is inherent to the task (e.g. floating-point sums). The reference output is produced by the author's reference solution run on the same workspace data.

## Limitations

**All data is synthetic.** The workspace generator produces controlled data, which means A2 (data realism) scores are bounded. To push A2 above 2/3, generators must deliberately inject missing values, format inconsistencies, and realistic skew distributions — not just vary row counts. Authors must treat data messiness as a first-class design parameter, not an afterthought.

**Determinism requires specifying the tie-breaking rule.** Any task where the correct output depends on ordering or tie-breaking must state the rule explicitly in the problem statement. Ambiguous tie-breaking means different valid implementations disagree, and the grader cannot distinguish correctness from implementation choice.

**Multi-file tasks require careful scope bounding.** Tasks involving many files can become search-heavy, which would shift the arm neutrality balance toward the tool-rich arm. Keep file counts to 2–5 files and total workspace size under 5 MB for this category.
