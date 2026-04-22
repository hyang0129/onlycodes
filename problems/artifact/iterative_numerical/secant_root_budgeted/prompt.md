# Task: Root-Find a Black-Box Function Under an Evaluation Budget

We have five opaque scalar functions `f1, ..., f5` shipped as a module
`black_box.py`. Each is continuous and has exactly one root in its stated
bracket. Production telemetry has been paying per call on an embedded
analog of this function, so we want the root to a tight tolerance using
as few function evaluations as is reasonable.

## Input

Read `brackets.json` — a list of entries, one per function:

```json
[
  {"name": "f1", "a": 0.0, "b": 2.0},
  {"name": "f2", "a": -1.0, "b": 3.0},
  ...
]
```

For each entry, `f = getattr(black_box, name)`, and the root lies in
`[a, b]` (sign change guaranteed: `f(a) * f(b) < 0`).

## Your goal

For each function, find `x_star` with `|f(x_star)| < 1e-8`. Write them to
`output/roots.json`:

```json
{
  "f1": 1.23456,
  "f2": 0.78910,
  ...
}
```

All five names from `brackets.json` must be present. Values must be
finite numbers inside the bracket.

## Methods

Any root-finder is acceptable — secant method, bisection,
Brent (`scipy.optimize.brentq`), Newton with numerical derivative, etc.
Secant is what the tutorial page this task is cribbed from suggests,
because it converges faster than bisection without needing an analytic
derivative.

## Verification

Run `python verify.py` to check that `output/roots.json` parses, covers
all five names, and has finite values inside their brackets.
