# Aggregate Model Predictions — Hard

The `predictions/` directory in your workspace contains prediction files in
various formats and schemas.  All files contain a sample identifier and a
predicted probability, but the exact representation varies:

- **CSV dialects**: standard, UTF-8 BOM, no header, quoted fields, mixed
  line endings, reversed column order
- **JSONL** (`.jsonl`): one JSON object per line; some files use different
  field names (`sample_id`, `probability`) or include comment lines starting
  with `#` that must be skipped
- **JSON array** (`.json`): entire file is a JSON array of objects; field
  names may differ (`identifier`) and `pred_prob` values may be strings
- **Gzipped CSV** (`.csv.gz`): standard CSV inside a gzip archive
- **Binary files**: some files are not valid predictions — skip them

Field names and column order may vary across files.  All files contain a
sample identifier and a predicted probability, but the exact names differ.
You must infer the correct fields from each file's structure.

Some files contain duplicate sample IDs; keep the **first occurrence** of
each ID.

Aggregate all valid predictions into `output/predictions.csv`.

## Output format

`output/predictions.csv` must:
- Have header `id,pred_prob`
- Contain one row per unique sample ID (first occurrence wins)
- Be sorted by `id` ascending
- Use standard CSV format

## Constraints

- Use only the Python standard library (`csv`, `json`, `gzip`, `pathlib`, etc.)
- Do not hard-code filenames — discover files dynamically
- Skip files or lines that cannot be parsed
