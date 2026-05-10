# Task: Hyperparameter Search

You are provided a deterministic toy model in `toy_model.py`. Your goal is to find hyperparameters that maximize its accuracy and report a configuration achieving **accuracy ≥ 0.90**.

## The Model

```python
from toy_model import evaluate

accuracy = evaluate(learning_rate=0.001, hidden_size=64, dropout=0.5)
# returns a float in [0.0, 0.95]
```

The function is **deterministic** — same inputs always return the same accuracy.

The model has per-instance calibration data (loaded from `calibration.bin`
sitting next to the module). The Gaussian *shape* of the response surface is
fixed, but the *location* of its peak varies per task instance, so reading
`toy_model.py` will NOT tell you the optimum. Call `evaluate()` and search.

Parameters to search:
- `learning_rate`: float, try values in [1e-4, 0.1] (log scale recommended)
- `hidden_size`: int, try values like 16, 32, 64, 128, 256, 512
- `dropout`: float in [0.0, 0.8]

## Your goal

Find parameters with **accuracy ≥ 0.90**. The model has a unique global optimum
inside the declared search space — search to find it.

Suggested approach:
1. Start with a coarse grid search across the declared ranges
2. Refine around the best-performing region
3. Report the best configuration found

## Output

Write `output/result.json`:

```json
{
  "learning_rate": 0.001,
  "hidden_size": 64,
  "dropout": 0.5,
  "accuracy": 0.95
}
```

(Values above are illustrative — they are *not* the answer.)

The grader will **re-evaluate** `evaluate(learning_rate, hidden_size, dropout)` on your reported parameters. Reported `accuracy` is informational — the grader computes the actual value.

## Verification

Run `python verify.py` to check your output has the correct schema.
