# Task: Enumerate All Valid Sudoku Row Completions

A QA engineer has paused a Sudoku solver mid-run and wants to see **every** completion of the currently-active row that respects the constraints already propagated from columns and boxes.

## Input

`workspace/row.json` — a JSON object:

```json
{
  "fixed": [null, 3, null, null, 7, null, null, null, null],
  "forbidden": [
    [2, 5],
    [],
    [1, 6, 9],
    ...  // 9 lists total
  ]
}
```

- `fixed`: length-9 array. Each entry is either `null` (cell is empty) or an integer in 1..9 (cell is pre-filled).
- `forbidden`: length-9 array of lists. `forbidden[i]` is the set of digits that cannot go in position `i` due to column/box constraints. If `fixed[i]` is non-null, `forbidden[i]` will not conflict with it.

## Your goal

Enumerate every **length-9 permutation of `{1..9}`** (a valid Sudoku row) such that:
- `row[i] == fixed[i]` wherever `fixed[i]` is not null, and
- `row[i]` is NOT in `forbidden[i]` for any `i`.

## Output

Write `output/completions.jsonl` — one JSONL line per valid completion:

```
[4, 3, 5, 1, 7, 2, 8, 9, 6]
[4, 3, 8, 1, 7, 2, 5, 9, 6]
...
```

Each line is a JSON array of 9 integers (each in 1..9) forming a permutation. Order of lines does not matter; no duplicates.

## Verification

Run `python verify.py` to check output schema. The hidden grader checks completeness — every valid completion is listed, none missing, none invalid.
