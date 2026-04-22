# Task: Safe arithmetic expression evaluator

Users of our internal spreadsheet tool can type formulas into cells, and the
backend needs to evaluate them **without** using `eval()` or `exec()` (a pen
test flagged that last quarter). Implement a small arithmetic expression
evaluator that handles the four basic operators, unary minus, and parentheses.

Implement `evaluate(expr: str) -> float`.

## Grammar

- Operators: `+`, `-`, `*`, `/` (binary), plus unary `-` (prefix).
- Parentheses: `(` and `)` for grouping.
- Operands: non-negative integer or decimal literals, e.g. `0`, `42`, `3.14`,
  `0.5`. No scientific notation, no leading `+` on literals, no hex.
- Whitespace (` `, tab) is allowed anywhere between tokens and ignored.
- Standard precedence: `*` and `/` bind tighter than `+` and `-`; operators of
  equal precedence are left-associative. Parentheses override precedence.
- Division is ordinary float division (`/`). Division by zero must raise
  `ZeroDivisionError`.
- Any syntactic error (unexpected token, unbalanced parens, empty input after
  trimming whitespace) must raise `ValueError`. You may use a single message
  string — the grader does not inspect it.

Return the evaluated value as a Python `float`.

## Examples

| Input | Output |
|-------|--------|
| `"1+2"` | `3.0` |
| `"2 + 3 * 4"` | `14.0` |
| `"(2 + 3) * 4"` | `20.0` |
| `"10 - 2 - 3"` | `5.0` |
| `"10 / 2 / 5"` | `1.0` |
| `"-5 + 3"` | `-2.0` |
| `"-(2 + 3)"` | `-5.0` |
| `"2 * -3"` | `-6.0` |
| `"1 / 0"` | raises `ZeroDivisionError` |
| `"1 + "` | raises `ValueError` |

## Output

Write your implementation to `output/solution.py`:

```python
def evaluate(expr: str) -> float:
    ...
```

Standard library only. **You must not use `eval()`, `exec()`, `compile()`, or
the `ast` module's `literal_eval`** — the whole point is to avoid those.
Recursive descent or shunting-yard are both fine; you may use `re` for
tokenising.

## Verification

Run `python verify.py` to check the structural shape of your output. The hidden
grader runs 25 cases including error paths.
