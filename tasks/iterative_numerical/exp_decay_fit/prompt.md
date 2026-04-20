# Task: Fit an Exponential Decay Curve

You are given noisy observations from a system that follows exponential decay.

## Model

```
y = A * exp(-k * t) + C
```

- `A`: initial amplitude (positive)
- `k`: decay rate (positive)  
- `C`: asymptotic value (offset)

## Input

Read `data.jsonl` — 50 data points, one per line:

```json
{"t": 0.0, "y": 12.1}
{"t": 0.163, "y": 11.4}
...
```

## Your goal

Find parameters `A`, `k`, `C` that best fit the data. The grader evaluates the RMSE of your model against the data points:

```
RMSE = sqrt( mean( (y_i - (A*exp(-k*t_i) + C))^2 ) )
```

Your fit must achieve **RMSE < 1.0**.

## Methods

Any curve-fitting approach is acceptable:
- `scipy.optimize.curve_fit`
- Gradient descent / numerical optimization
- Analytical least squares (nonlinear, so iterative methods are typical)

## Output

Write `output/params.json`:

```json
{"A": 10.0, "k": 0.5, "C": 2.0}
```

All values must be finite numbers. `k` must be positive.

## Verification

Run `python verify.py` to check your output has the correct schema.
