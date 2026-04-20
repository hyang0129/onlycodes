# Bisection Calibration

## Problem

A black-box function `f(x)` is provided in `black_box.py`. The function has exactly one root in the interval `[0, 100]`.

Your goal is to find `x*` such that `|f(x*)| < 1e-6`.

## Setup

Import the function as follows:

```python
from black_box import f
```

Every call to `f(x)` counts as one evaluation. Track how many evaluations you use.

## Output

Write your result to `output/result.json` with this structure:

```json
{
  "x_star": 37.0079...,
  "f_x_star": -2.3e-10,
  "evaluations": 42
}
```

- `x_star`: the root you found (a float in `[0, 100]`)
- `f_x_star`: the actual value of `f(x_star)` — compute this yourself, the grader re-evaluates it
- `evaluations`: the number of times you called `f` — report honestly

## Hints

- Bisection on `[0, 100]` converges to `1e-6` precision in approximately 50 iterations
- Check the sign of `f` at the endpoints to confirm the bracket: `f(0) < 0` and `f(100) > 0`
- Create the `output/` directory before writing the file
