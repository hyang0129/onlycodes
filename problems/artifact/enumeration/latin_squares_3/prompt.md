# Task: Enumerate All 3×3 Latin Squares

A **Latin square** of order 3 is a 3×3 grid filled with the symbols {1, 2, 3} such that:
- Each symbol appears exactly once in every row
- Each symbol appears exactly once in every column

## Your goal

Enumerate **all** distinct 3×3 Latin squares using the symbols {1, 2, 3}.

Two Latin squares are **distinct** if they differ in at least one cell. There is no symmetry reduction — list all of them, not just reduced or canonical forms.

## Output

Write `output/latin_squares.jsonl` — one JSONL line per Latin square:

```
[[1, 2, 3], [2, 3, 1], [3, 1, 2]]
[[1, 2, 3], [3, 1, 2], [2, 3, 1]]
...
```

Each line is a JSON array of 3 rows, each row a list of 3 integers from {1, 2, 3}.
The order of lines does not matter.

## Verification

Run `python verify.py` to check that your output has the correct schema.
The hidden grader checks for **completeness** (no missing squares) and **validity** (no non-Latin or duplicate entries).
