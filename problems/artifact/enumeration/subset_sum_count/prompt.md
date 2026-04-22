# Task: Enumerate All Subsets Summing to a Target

Finance is auditing a set of 12 reported line-item amounts and needs to know **every** combination that could reconcile to a target total. Not the count — the actual index sets.

## Input

`workspace/amounts.json` — a JSON object:

```json
{
  "amounts": [ ... 12 positive integers ... ],
  "target": <positive integer>
}
```

Amounts may repeat (treat them as a multiset indexed by position 0..11).

## Your goal

Enumerate **every** subset of **indices** (from `{0..11}`) whose corresponding `amounts` values sum exactly to `target`. Subsets are distinguished by their index set — two subsets with the same values at different positions are different subsets.

## Output

Write `output/subsets.jsonl` — one JSONL line per qualifying subset. Each line is a sorted JSON array of indices:

```
[0, 3, 7]
[1, 2, 4, 9]
...
```

- Indices within each line must be sorted ascending.
- The empty subset `[]` qualifies iff `target == 0` (it will not be in this task).
- Order of lines does not matter.
- Each subset appears at most once.

## Verification

Run `python verify.py` to check output schema. The hidden grader checks completeness
(every qualifying subset present; no missing, no extras, no duplicates, each sums to target).
