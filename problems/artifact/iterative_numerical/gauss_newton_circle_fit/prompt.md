# Task: Fit a Circle to Noisy 2D Points

A computer-vision pipeline produces noisy `(u, v)` pixel coordinates
tracing a roughly circular fiducial mark. Downstream code expects a fit
circle — center `(cx, cy)` and radius `r` — so it can check for drift
between frames. Please fit a circle to the points.

## Input

Read `points.jsonl` — 60 2-D points, one per line:

```json
{"u": 3.12, "v": -1.47}
{"u": 2.98, "v": -1.85}
...
```

## Your goal

Find `(cx, cy, r)` minimising the **geometric** residuals

```
r_i = sqrt((u_i - cx)^2 + (v_i - cy)^2) - r
```

The grader computes

```
rms = sqrt( mean( r_i^2 ) )
```

and requires `rms < 0.08`.

Constraints:
- `r > 0`
- All three values finite

## Methods

Any iterative fitter works. Gauss–Newton on the geometric residual, or
Levenberg–Marquardt (`scipy.optimize.least_squares`) are typical. A good
initial guess is the *algebraic* circle fit (solve `u^2 + v^2 = 2*cx*u +
2*cy*v + (r^2 - cx^2 - cy^2)` as a linear system in `(cx, cy, r^2 - cx^2
- cy^2)`), then polish with Gauss–Newton.

## Output

Write `output/circle.json`:

```json
{"cx": 2.0, "cy": -1.0, "r": 3.5}
```

## Verification

Run `python verify.py` to sanity-check the schema.
