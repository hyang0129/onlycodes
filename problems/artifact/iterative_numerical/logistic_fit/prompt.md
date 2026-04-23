# Task: Fit a Logistic Growth Curve

Marketing collected weekly cumulative-signup counts from a product launch
and we want a logistic model so we can forecast the saturation level and
the midpoint week. Please fit the standard 3-parameter logistic:

```
y = L / (1 + exp(-k * (x - x0)))
```

- `L`:  carrying capacity / saturation (positive)
- `k`:  growth rate (positive)
- `x0`: midpoint (the `x` at which `y = L/2`)

## Input

Read `signups.jsonl` — 40 observations, one per line:

```json
{"x": 0.0, "y": 3.2}
{"x": 1.0, "y": 4.8}
...
```

`x` is weeks since launch (non-negative, monotonically increasing).
`y` is the observed cumulative signup count (positive, noisy).

## Your goal

Find `L`, `k`, `x0` that fit the data. The grader evaluates RMSE against
the observed points and requires:

```
RMSE = sqrt( mean( (y_i - L / (1 + exp(-k*(x_i - x0))))^2 ) ) < 5.0
```

In addition:

- `L`  must be finite and `> 0`
- `k`  must be finite and `> 0`
- `x0` must be finite

## Methods

Any iterative fitter is fine: `scipy.optimize.curve_fit`,
`scipy.optimize.least_squares`, manual Gauss–Newton / gradient descent,
or log-transform-and-linear-regression as a warm start. A reasonable
initial guess is `L0 ≈ max(y)`, `x0 ≈ median(x)`, `k0 ≈ 1.0`.

## Output

Write `output/params.json`:

```json
{"L": 200.0, "k": 0.4, "x0": 15.0}
```

## Verification

Run `python verify.py` to check schema (keys present, numbers finite,
`L > 0`, `k > 0`).
