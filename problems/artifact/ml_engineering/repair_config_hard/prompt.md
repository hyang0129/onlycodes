# Repair ML Training Config — Hard

The file `config.yaml` in your workspace contains an ML training configuration
with multiple invalid field values, including some that are only revealed after
earlier violations are corrected.

A validation script is provided at `validate.py`. Run it to see which rules are
currently failing:

```
python validate.py config.yaml
```

Work iteratively: fix the reported violations, re-run `validate.py`, and
repeat until all rules pass.  Some rules are conditional — they are only
checked once a prerequisite field is valid — so new failures may appear
after each round of fixes.

Fix every failing rule so that `validate.py` exits with code 0 and reports all
rules passing.  Write the corrected config to `output/config.yaml`.

## Output format

`output/config.yaml` must be a valid YAML file with the same top-level
structure as the input (`training`, `model`, `data` sections).  All fields
from the input must be present.

## Constraints

- Do **not** add or remove fields; only change values that are currently invalid.
- All values must satisfy the rules printed by `validate.py`.
- The output file must be valid YAML parseable by PyYAML.
