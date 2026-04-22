# Task: Permutations of [0..4] with Exactly 2 Fixed Points

A **fixed point** of a permutation `p` of `[0, 1, 2, 3, 4]` is an index `i` where `p[i] == i`.

## Your goal

List every permutation of `[0, 1, 2, 3, 4]` that has **exactly 2 fixed points**.

## Output

Write `output/perms.jsonl` — one JSONL line per qualifying permutation:

```
[0, 1, 3, 2, 4]
[0, 2, 1, 3, 4]
...
```

Each line is a JSON array of the 5 integers in permutation order. The order of lines does not matter; the grader will normalize.

## Constraints

- Length exactly 5; each value in `{0,1,2,3,4}` appears exactly once.
- Exactly 2 positions satisfy `p[i] == i`.
- List each permutation once — no duplicates.

## Verification

Run `python verify.py` to check output schema. The hidden grader checks completeness
(all qualifying permutations listed, no missing, no extras).
