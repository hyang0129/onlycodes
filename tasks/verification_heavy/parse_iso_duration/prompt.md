# Task: Implement `parse_iso_duration`

Implement the function `parse_iso_duration(s: str) -> datetime.timedelta` that parses an ISO 8601 duration string into a Python `timedelta`.

## ISO 8601 Duration Format

An ISO 8601 duration looks like: `P[n]W[n]DT[n]H[n]M[n]S`

- Starts with `P`
- Date section (before `T`): `W` (weeks), `D` (days)
- Time section (after `T`): `H` (hours), `M` (minutes), `S` (seconds)
- All components are optional but at least one must be present
- Numbers may be integers or decimals (e.g. `PT1.5H`, `PT0.5S`)
- Year (`Y`) and month (`M` in date part) are **not required** — this implementation only needs to handle weeks, days, hours, minutes, and seconds

### Examples

| Input | Expected timedelta |
|-------|-------------------|
| `"PT0S"` | `timedelta(0)` |
| `"PT1H30M"` | `timedelta(hours=1, minutes=30)` |
| `"P1W2DT3H4M5S"` | `timedelta(weeks=1, days=2, hours=3, minutes=4, seconds=5)` |
| `"PT0.5S"` | `timedelta(seconds=0.5)` |
| `"P7D"` | `timedelta(days=7)` |

## Output

Write your implementation to `output/solution.py`.

The file must define:

```python
from datetime import timedelta

def parse_iso_duration(s: str) -> timedelta:
    ...
```

You may import any standard library modules (no third-party packages required).

## Verification

Run `python verify.py` to check that `output/solution.py` imports and exports `parse_iso_duration`. The hidden test suite will run 15 property tests against your implementation.
