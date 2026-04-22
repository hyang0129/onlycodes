# Task: Enumerate All 7-Queens Solutions

Place 7 queens on a 7×7 chessboard so that no two attack each other (no two share a row, column, or diagonal).

## Your goal

Enumerate **all** distinct placements — **no symmetry reduction**. Rotations and reflections are considered distinct unless they happen to coincide with another placement as-written.

## Output

Write `output/solutions.jsonl` — one JSONL line per solution, encoded as a length-7 list where entry `i` is the **column** of the queen in **row `i`** (0-indexed):

```
[0, 2, 4, 6, 1, 3, 5]
[0, 3, 6, 2, 5, 1, 4]
...
```

- Each line: list of 7 ints, each in `{0..6}`, forming a permutation (exactly one queen per row and column).
- Additionally, no two queens share a diagonal: for any two rows `i < j`, `abs(row[i] - row[j]) != j - i`.
- Order of lines does not matter; no duplicates.

## Verification

Run `python verify.py` to check output schema. The hidden grader checks completeness —
every valid placement is listed exactly once.
