# Task: Minimize the Rosenbrock Function

One of our numerical-methods interview problems is "minimize the
Rosenbrock function". The canonical test function is:

```
f(x, y) = (a - x)^2 + b * (y - x^2)^2
```

with `a = 1.0` and `b = 100.0`. Its global minimum is at `(a, a^2) = (1, 1)`
with `f = 0`. The function has a long curved "banana" valley that trips
up naive gradient descent, which is why it is a classic test.

## Input

Read `problem.json` — it specifies the constants and a starting point:

```json
{"a": 1.0, "b": 100.0, "x0": -1.2, "y0": 1.0}
```

## Your goal

Find `(x_min, y_min)` with `f(x_min, y_min) < 1e-6`. Write to
`output/minimum.json`:

```json
{"x": 1.0000001, "y": 1.0000002, "f": 5.0e-14}
```

The grader re-evaluates `f` on your reported `(x, y)` — a hallucinated `f`
field will not pass.

All fields must be finite numbers.

## Methods

Gradient descent with a constant step size will not converge on this
function — it will zig-zag or diverge. Reasonable choices:

- Backtracking / Armijo line search on steepest descent
- Conjugate gradient (`scipy.optimize.minimize(..., method="CG")`)
- BFGS (`scipy.optimize.minimize(..., method="BFGS")`)
- Newton with the analytical Hessian
- `scipy.optimize.minimize` with `method="Nelder-Mead"` also works but
  is slower

Analytical gradient:
```
df/dx = -2*(a - x) + b * 2*(y - x^2)*(-2*x)
df/dy =  2*b*(y - x^2)
```

## Verification

Run `python verify.py` to check schema.
