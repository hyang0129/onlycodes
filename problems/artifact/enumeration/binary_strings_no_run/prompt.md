# Task: Enumerate Length-10 Binary Strings With No Run of 1s Longer Than 2

A reliability engineer is listing all fault-sequence patterns of length 10 where
an active-fault indicator (`1`) never stays on for more than two consecutive steps.
`0` means "no fault", `1` means "fault". A "run of 1s" is a maximal consecutive
substring of `1`s; its length is the number of `1`s in it.

## Your goal

Enumerate every binary string of length **exactly 10** such that **no run of `1`s exceeds length 2**.

## Output

Write `output/strings.jsonl` — one JSONL line per qualifying string, encoded as a JSON string of length 10 containing only `'0'` and `'1'`:

```
"0000000000"
"0000000001"
"0000000010"
"0000000011"
"0000000100"
...
```

- Each line is a JSON string (wrapped in double quotes).
- Exactly 10 characters, each `'0'` or `'1'`.
- No run of `'1'`s longer than 2 (so `"111"` as a substring is forbidden).
- Order of lines does not matter; no duplicates.

## Verification

Run `python verify.py` to check output schema. The hidden grader checks completeness —
every qualifying string is listed exactly once.
