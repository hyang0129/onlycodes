# Find the Broken Training Runs

## Background

A nightly training sweep launched a batch of jobs onto a shared cluster.
Each job writes its own JSONL log to `runs/run_NNNN.jsonl` (one event
per line). Most of the runs finished cleanly. A handful did not — the
cluster's disk filled, a few losses went non-finite, a few diverged.
The on-call engineer needs a quick list of which runs broke and *how*,
so they can decide which to relaunch.

The workspace contains a `runs/` directory with one `run_NNNN.jsonl`
file per training job. You will need to determine the count yourself
from the directory listing.

## Log file format

Every healthy run looks like this:

```jsonl
{"event": "start", "run_id": "run_0000", "total_steps": 800, "lr": 0.000123}
{"step": 1, "train_loss": 4.91, "val_loss": 5.02}
{"step": 2, "train_loss": 4.67, "val_loss": 4.88}
...
{"step": 800, "train_loss": 0.41, "val_loss": 0.55}
{"event": "done", "run_id": "run_0000"}
```

A **healthy** run is one whose **last line is a valid JSON object with
`"event": "done"`**. Healthy runs are never in your output.

## Failure modes

A broken run is one that did **not** finish with a `done` event. There
are exactly three failure modes; every broken run is in exactly one
mode. Distinguish them by these signatures:

| Mode | How to recognize it |
|---|---|
| `nan` | The bareword `NaN` appears somewhere in the file (typically as a `train_loss` or `val_loss` value), and there is no `done` event. |
| `truncated` | The file's last line is **not parseable as JSON** (cut off mid-record), and there is no `done` event. The file does not contain the substring `NaN`. |
| `diverged` | All lines parse as valid JSON, there is no `done` event, no `NaN` anywhere, **and** the final ~20 step lines show `val_loss` increasing monotonically and ending above `1000.0` (the values are finite — they just blew up). |

These signatures are mutually exclusive. Check them in the order above:
if a file has `NaN`, it is `nan` (do not also flag truncated/diverged
even if the file is short or the tail looks high).

## Your task

Write `output/broken.csv` with **exactly these columns, in this order**:

```
run_id,failure_mode
```

- One row per **broken** run. **Do not list healthy runs.**
- `run_id` is the bare run identifier from the filename (e.g. `run_0007`,
  not `run_0007.jsonl` and not the full path).
- `failure_mode` is one of `nan`, `truncated`, `diverged`.
- Sort rows by `run_id` ascending (lexicographic).
- Standard CSV with a header row matching the column list above. UTF-8.
  Trailing newline at end of file.

There is no fixed number of broken runs to find — figure out the count
from the data. The reference answer is the exact set; an extra row or a
missing row both count as wrong.
