# Task: Container Loading — Minimum Bin Packing

We ship identical-capacity containers to a single destination. Today's manifest
has 15 parcels of various weights; we need to decide how many containers to
dispatch. A container can hold any combination of parcels as long as their total
weight does not exceed its capacity.

**Find the minimum number of containers needed to ship ALL parcels.** Every
parcel must be assigned to exactly one container. Containers are identical and
unordered.

## Input

Read `parcels.json` from your working directory:

```json
{
  "capacity": 100,
  "weights": [42, 17, 55, ...]
}
```

- `capacity`: positive integer bin capacity.
- `weights`: 15 positive integers, each `<= capacity`.

## Output

Write `output/bins.json`:

```json
{
  "num_bins": <integer>,
  "bins": [[item_ids_in_bin_0], [item_ids_in_bin_1], ...]
}
```

- `num_bins`: the minimum number of bins. Must be globally optimal.
- `bins`: (optional but validated if present) partition of 0..14 into `num_bins`
  non-empty lists, each with total weight `<= capacity`.

## Requirements

- `num_bins` must be **globally optimal**. First-fit-decreasing is a known
  heuristic but does NOT guarantee optimality; you will need an exact method.
  With N=15, one exact approach is subset-DP: compute `dp[mask]` = minimum bins
  needed to cover the items in `mask`, iterating over the valid single-bin
  subsets of `mask`. That runs in well under a second in pure Python for
  N=15.

## Verification

Run `python verify.py` to check your output has the correct shape before submitting.
