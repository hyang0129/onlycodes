# Task: Implement a Semantic Versioning comparator

Our release-pipeline tooling currently sorts tags alphabetically, which means
`v1.10.0` sorts before `v1.2.0` and we keep cutting hotfixes from the wrong
base. We want one reference function that does SemVer comparison per
[semver.org v2.0.0](https://semver.org/) so all the downstream scripts can call
into the same logic.

Implement `compare_semver(a: str, b: str) -> int` that returns:

- `-1` if `a` is a lower version than `b`,
- ` 0` if they are equal,
- `+1` if `a` is a higher version.

## SemVer rules (subset we need)

A valid version string has three dot-separated numeric components:
`MAJOR.MINOR.PATCH` (each a non-negative integer, no leading zeros except
literal `0`). Optionally followed by:

- A **pre-release** tag, introduced by `-`, consisting of one or more
  dot-separated identifiers. An identifier is either numeric
  (`[0-9]+`, no leading zeros) or alphanumeric (`[0-9A-Za-z-]+` with at least
  one non-digit). Example: `1.0.0-alpha.1`, `1.0.0-rc.2`.
- **Build metadata**, introduced by `+`, ignored for comparison. Example:
  `1.0.0+20240101`.

### Precedence (what "lower" and "higher" mean)

1. Compare MAJOR, then MINOR, then PATCH as integers.
2. A version **with** a pre-release tag is **lower** than the same version
   **without** one. So `1.0.0-alpha < 1.0.0`.
3. If both have pre-release tags, compare identifiers left to right:
   - Numeric identifiers compare as integers.
   - Alphanumeric identifiers compare lexicographically (ASCII).
   - Numeric identifiers are always **lower** than alphanumeric ones.
   - If all shared identifiers are equal, the shorter list is lower.
4. Build metadata (`+...`) is ignored in comparisons. So `1.0.0+a == 1.0.0+b`.

You may assume inputs are syntactically valid — no error handling required.

## Examples

| a | b | result |
|---|---|--------|
| `1.0.0` | `1.0.0` | `0` |
| `1.0.0` | `2.0.0` | `-1` |
| `1.10.0` | `1.2.0` | `+1` |
| `1.0.0-alpha` | `1.0.0` | `-1` |
| `1.0.0-alpha` | `1.0.0-alpha.1` | `-1` |
| `1.0.0-alpha.1` | `1.0.0-alpha.beta` | `-1` |
| `1.0.0-rc.1` | `1.0.0-rc.2` | `-1` |
| `1.0.0+build.1` | `1.0.0+build.2` | `0` |
| `1.0.0-alpha+a` | `1.0.0-alpha+b` | `0` |

## Output

Write your implementation to `output/solution.py`:

```python
def compare_semver(a: str, b: str) -> int:
    ...
```

Standard library only. No third-party semver packages.

## Verification

Run `python verify.py` to check the structural shape of your output. The hidden
grader runs 25 comparison cases.
