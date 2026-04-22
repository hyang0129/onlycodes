# Task: Enumerate All Integer Partitions of 15

An **integer partition** of `n` is a way of writing `n` as an unordered sum of **positive** integers. For example, `4 = 4 = 3+1 = 2+2 = 2+1+1 = 1+1+1+1` — five partitions of 4.

## Your goal

List every integer partition of **15**.

## Output

Write `output/partitions.jsonl` — one JSONL line per partition. Each line is a JSON array
of positive integers in **non-increasing order** (largest part first):

```
[15]
[14, 1]
[13, 2]
[13, 1, 1]
[12, 3]
...
[1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]
```

- Each list's entries sum to 15.
- Each list is sorted in non-increasing (descending) order.
- All entries are positive integers.
- The order of lines does not matter; no duplicate partitions.

## Verification

Run `python verify.py` to check output schema. The hidden grader checks that every
partition of 15 is present exactly once and that every listed entry is a valid partition.
