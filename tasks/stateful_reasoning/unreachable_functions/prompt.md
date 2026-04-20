# Task: Identify Unreachable Functions

You are given a small Python codebase in the `src/` directory:

```
src/
  main.py         — entry point; calls main() when run as __main__
  utils.py        — utility functions
  services.py     — service layer
  notifications.py — notification helpers
```

## Your goal

Perform **static call-graph analysis** to determine which functions are **never reachable** from `main()` in `src/main.py`.

A function is **reachable** if:
- It is `main()` itself, OR
- It is called (directly or transitively) by a reachable function

Use **BFS/DFS over explicit function calls** visible in the source code. Only consider direct function calls (`func(args)` or `obj.method(args)`). Do not follow import chains beyond the four files — treat any called name that matches a defined function in the codebase as an edge.

## Output

Write `output/unreachable.jsonl` — one JSONL line per unreachable function:

```json
{"function": "some_function", "module": "module_name"}
```

- `function`: the function's name (as defined, e.g. `_helper` or `process_data`)
- `module`: the Python module filename without `.py` (e.g. `utils`, `services`)

Order of lines does not matter. Do not include `main` itself (it is the root).

## Verification

Run `python verify.py` to check that your output has the correct schema.
The hidden grader re-analyzes the source tree independently and set-compares.
