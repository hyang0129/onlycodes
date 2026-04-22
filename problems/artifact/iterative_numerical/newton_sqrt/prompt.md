# Task: Compute Square Roots via Newton's Method

A numerics tutorial is being put together for junior engineers and we need
a small reference table of square roots computed iteratively rather than
via `math.sqrt`. The teaching point is Newton's method — so please produce
the results using that algorithm (or an equivalent iterative scheme),
not a direct library call.

## Input

Read `inputs.json` from the current working directory. It is a JSON object
mapping an integer id to a non-negative real number `x` whose square root
is wanted:

```json
{
  "1": 2.0,
  "2": 9.0,
  "3": 0.25,
  ...
}
```

Ids are strings (as JSON requires). Values of `x` are guaranteed finite
and `>= 0.0`.

## Your goal

For each `(id, x)` pair, compute `sqrt(x)` to an absolute accuracy of
`1e-8`. Write the results to `output/roots.json` as a JSON object mapping
the same ids to the computed roots:

```json
{
  "1": 1.4142135623730951,
  "2": 3.0,
  "3": 0.5,
  ...
}
```

All output ids from the input must be present. Values must be finite
non-negative numbers. `sqrt(0.0)` is `0.0`.

## Method

Newton's iteration for `y = sqrt(x)` solves `f(y) = y*y - x = 0`:

```
y_{n+1} = 0.5 * (y_n + x / y_n)
```

starting from a reasonable positive guess (e.g. `y_0 = max(x, 1.0)`),
iterating until `|y_{n+1} - y_n| < 1e-12` or a max iteration count is hit.
Handle `x == 0.0` as a special case.

## Verification

Run `python verify.py` to check that `output/roots.json` parses, covers
every input id, and has finite non-negative values.
