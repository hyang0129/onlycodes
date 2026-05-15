# Aggregate Model Predictions — Easy

The `predictions/` directory in your workspace contains CSV files with model
predictions.  Each file has two columns: `id` (a sample identifier) and
`pred_prob` (a predicted probability in [0, 1]).

Aggregate all predictions from all files into a single output file at
`output/predictions.csv`.

## Output format

`output/predictions.csv` must:
- Have header `id,pred_prob`
- Contain one row per unique sample ID
- Be sorted by `id` ascending
- Use standard CSV format (no quoting unless required)

## Constraints

- Use only the Python standard library (`csv`, `pathlib`, etc.)
- Do not hard-code filenames — read all files from the `predictions/` directory
