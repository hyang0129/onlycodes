# Task: Minimum Coin Change

Our cash-drawer allocation service needs to hand out a requested payout using the
fewest physical coin tokens possible. We have an unlimited supply of each
denomination.

Given a set of coin denominations and a target amount, **compute the minimum
number of coins that sum exactly to the target**. If no combination of the
available denominations can produce the target, report `-1`.

## Input

Read `request.json` from your working directory:

```json
{
  "denominations": [1, 5, 10, 25],
  "amount": 63
}
```

- `denominations`: list of positive integers (distinct, ≤ 10 entries).
- `amount`: non-negative integer target to make up (≤ 2000).

Each denomination can be used any number of times (including zero).

## Output

Write `output/answer.json`:

```json
{
  "min_coins": <integer>
}
```

- `min_coins`: the minimum number of coins that sum to `amount`, or `-1` if the
  target is not representable.

## Notes

- This is the classic unbounded-coin-change problem; a standard DP runs in
  `O(amount * len(denominations))`.
- `amount = 0` is representable with `0` coins.

## Verification

Run `python verify.py` to check your output has the correct shape before submitting.
