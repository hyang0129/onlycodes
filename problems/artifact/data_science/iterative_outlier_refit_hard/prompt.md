# Iterative Outlier Refit (Fit → Flag → Drop → Repeat)

## Background

You have a tabular regression dataset with three features and one target.
Most rows are well-described by a linear model; a small minority are
contaminated with a large additive y-shift and should be excluded from
the final fit. Your job is to find those outliers by an iterative
fit-and-flag loop, return the converged outlier set, and report the
final fit on the cleaned rows.

The workspace contains:

- `data.csv` — a CSV with columns `x1, x2, x3, y`. All columns are
  numeric (floats). There are no missing values. The original row order
  in this file defines row indices `0, 1, 2, …, N-1`; preserve that
  order throughout — do not shuffle, do not re-sort.

## Your task

Run the iterative pipeline below **exactly** as specified, then write
`output/result.json`.

### Algorithm (run this loop until convergence)

Initialize:

```
included = set of all original row indices {0, 1, …, N-1}
prev_outliers = None
iteration = 0
```

Then loop:

```
iteration += 1
fit a sklearn.linear_model.LinearRegression() with its default constructor
    on the rows whose original index is in `included`,
    using features [x1, x2, x3] (in that exact column order) as X,
    and y as the target.

predict y_hat for ALL original rows (i.e. all N rows, including any
    rows currently excluded from `included`), using the model just fit.

compute residuals  r_i = y_i - y_hat_i  for every row i in 0..N-1.

compute the residual standard deviation, restricted to the currently
    included rows, using NumPy's population standard deviation:
        sigma = numpy.std([r_i for i in included], ddof=0)
    (ddof=0 — the NumPy default. Do NOT use ddof=1 / sample std.)

compute z_i = r_i / sigma  for every row i in 0..N-1
    (z-scores against the included-rows sigma, evaluated on every row).

flag outliers — current_outliers is the set of original row indices i
    such that  abs(z_i) > 3.0  (STRICT greater-than; the comparator is
    `>` not `>=`). Evaluate this over ALL N rows, not just the currently
    included ones — a previously-excluded row whose |z| drops to ≤ 3.0
    rejoins the included set on the next iteration.

if current_outliers == prev_outliers:
    # Converged — the outlier set is identical to the previous
    # iteration's outlier set. STOP. Record n_iterations = iteration.
    break

prev_outliers = current_outliers
included = {0, 1, …, N-1} \ current_outliers
```

Convergence is guaranteed for this dataset within a handful of
iterations; cap the loop at 50 iterations as a defensive guard. If you
hit the cap without converging, that is a bug in your implementation —
do not write a partial result.

After the loop exits with convergence:

- The **final fit** is the linear regression from the last iteration
  (fit on `included` at the start of that iteration, i.e. the inliers
  whose indices are in `prev_outliers`'s complement).
- The **final RMSE** is the in-sample RMSE of that final fit on the
  rows it was fit on (the inliers). Define RMSE explicitly as:

  ```
  RMSE = sqrt( mean( (y_pred - y_true) ** 2 ) )
  ```

  Computed over the inlier rows only.

### Output

Write `output/result.json` containing **exactly these five fields**:

```json
{
  "outlier_indices": [49, 99, 149, ...],
  "n_iterations": 2,
  "final_intercept": <float>,
  "final_coefficients": [<float>, <float>, <float>],
  "final_rmse": <float>
}
```

Rules:

- `outlier_indices` — a JSON array of integers, the converged outlier
  set, **sorted in ascending numeric order**. These are the original
  0-based row indices into `data.csv` (the row position in the file,
  counting from the first data row after the header as row 0). Do not
  emit them as strings.
- `n_iterations` — a JSON integer, the value of `iteration` when the
  loop broke (the iteration count at which the outlier set first
  matched the previous iteration's set). For this dataset the expected
  value is small (single digits). If you emit `0` or a value > 50 the
  grader will reject the artifact regardless of the other fields.
- `final_intercept` — a JSON number, `model.intercept_` from the final
  fit. Do not round; emit full precision. Tolerance ±1e-4.
- `final_coefficients` — a JSON array of exactly three numbers, the
  `model.coef_` array from the final fit, in the column order
  `[x1, x2, x3]`. Tolerance ±1e-4 each.
- `final_rmse` — a JSON number, the in-sample RMSE of the final fit on
  the inlier rows. Tolerance ±1e-4.
- Extra fields are not allowed. Missing fields are not allowed.
- UTF-8 encoded. Trailing newline optional.

### Pinned details (read carefully — these eliminate ambiguity)

1. **Regressor**: `sklearn.linear_model.LinearRegression()` with its
   default constructor (`fit_intercept=True`, no other arguments).
2. **Standard deviation formula**: NumPy population std, `ddof=0`.
   This is `numpy.std`'s default — do not pass `ddof=1`.
3. **Threshold comparator**: strict `abs(z) > 3.0`. A row with exactly
   `abs(z) == 3.0` is **not** an outlier. (The dataset is engineered so
   no row is anywhere near the boundary — inliers sit at `|z| < 2.0`
   and outliers at `|z| > 5.0` — so this distinction is academic, but
   the comparator is pinned for completeness.)
4. **Index basis**: row indices are the original positions in
   `data.csv`, counted from 0 starting at the first data row after the
   header. Sorting, shuffling, or re-indexing the DataFrame after load
   is forbidden — the grader compares against original-order indices.
5. **Residual sigma scope**: computed over residuals of the CURRENTLY
   INCLUDED rows only (the rows the model was just fit on). Not over
   all N residuals.
6. **z-score evaluation scope**: residuals and z-scores are computed
   for ALL N rows in each iteration, against the included-rows sigma.
   The flag rule is then applied to all N rows. This permits a
   previously-excluded row to rejoin if it no longer looks like an
   outlier under the new fit (though in practice this dataset does not
   exercise that path).
7. **Convergence criterion**: the outlier index set produced in the
   current iteration equals the outlier index set from the previous
   iteration as Python sets (order-insensitive). The very first
   iteration cannot converge (there is no previous set yet) — start the
   comparison from iteration 2 onward.
8. **n_iterations definition**: the value of the iteration counter at
   the moment the loop breaks. If iteration 1 produces set S and
   iteration 2 produces the same set S, the loop breaks at iteration 2
   and `n_iterations = 2`.

### What the grader checks

The grader re-runs the same pipeline on `data.csv` and compares your
`result.json`:

- `outlier_indices` must equal the grader's outlier set (compared as a
  set; order-insensitive — but it must still be sorted ascending on
  disk to make diffs deterministic; the grader checks both).
- `n_iterations` must equal the grader's value exactly (integer).
- `final_intercept`, each entry of `final_coefficients`, and
  `final_rmse` must each be within `±1e-4` of the grader's value.

Scoring is all-or-nothing: any field failing yields score 0.0. Every
field within tolerance yields score 1.0.
