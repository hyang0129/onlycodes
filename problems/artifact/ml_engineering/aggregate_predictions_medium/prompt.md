# Aggregate Model Predictions — Medium

The `predictions/` directory in your workspace contains prediction files in
multiple formats:

- **CSV** files (`.csv`) with header `id,pred_prob`
- **JSONL** files (`.jsonl`) where each line is a JSON object with fields
  `id` and `pred_prob`

One file may have a truncated last line — skip any line that cannot be parsed.

Aggregate all valid predictions from all files into a single output file at
`output/predictions.csv`.

## Output format

`output/predictions.csv` must:
- Have header `id,pred_prob`
- Contain one row per unique sample ID
- Be sorted by `id` ascending
- Use standard CSV format

## Constraints

- Use only the Python standard library (`csv`, `json`, `pathlib`, etc.)
- Do not hard-code filenames — read all files from the `predictions/` directory
- Skip lines or files that cannot be parsed; do not raise exceptions
