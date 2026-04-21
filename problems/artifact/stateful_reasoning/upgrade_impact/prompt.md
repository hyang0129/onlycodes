# Task: Identify Package Upgrade Conflicts

You are given `packages.json` describing a set of packages and a planned upgrade.

## Input Format

```json
{
  "packages": {
    "<pkg-name>": {
      "version": "<current-version>",
      "dependencies": {
        "<dep-name>": "<semver-constraint>",
        ...
      }
    },
    ...
  },
  "upgrade": {
    "package": "<name-of-package-being-upgraded>",
    "from": "<current-version>",
    "to": "<new-version>"
  }
}
```

## Your goal

Determine which packages will have a **version conflict** after the upgrade.

A package has a conflict if it depends on the upgraded package with a constraint that is **NOT satisfied** by the new version.

### Semver constraint rules

| Constraint | Meaning |
|-----------|---------|
| `^X.Y.Z` | `>=X.Y.Z <(X+1).0.0` (if X>0) or `>=0.Y.Z <0.(Y+1).0` (if X=0, Y>0) |
| `~X.Y.Z` | `>=X.Y.Z <X.(Y+1).0` |
| `>=X.Y.Z` | any version ≥ X.Y.Z |
| `>X.Y.Z`  | any version > X.Y.Z |
| `X.Y.Z`   | exact match only |

## Output

Write `output/conflicts.jsonl` — one JSONL line per conflicting package:

```json
{"package": "web-server", "constraint": "^1.0.0"}
```

- `package`: name of the package with the conflict
- `constraint`: the dependency constraint that is violated (optional but recommended)

Order does not matter. Only include packages that actually depend on the upgraded package with a broken constraint.

## Verification

Run `python verify.py` to check output schema.
