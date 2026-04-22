# Task: Parse a single CSV line (RFC 4180 subset)

We have a data-ingest path that used to rely on `str.split(",")`. It breaks on
quoted fields that contain commas (e.g. addresses like `"Seattle, WA"`). Before
we swap in `csv.reader` across the pipeline, we need a small, auditable
reference function that implements the RFC 4180 rules we actually see in our
feeds so the behaviour is documented in one place.

Implement `parse_csv_line(line: str) -> list[str]` that splits **one** CSV
record into its fields according to the rules below.

## Rules

1. Fields are separated by `,`.
2. A field may optionally be enclosed in double quotes `"..."`. Inside a quoted
   field:
   - Commas are literal (not separators).
   - Two adjacent double quotes `""` represent a single literal `"`.
   - Any other character (including whitespace) is kept verbatim.
3. Unquoted fields are taken verbatim between the surrounding separators. No
   whitespace trimming.
4. The input is exactly one logical record, **without** a trailing newline.
   It will not contain embedded raw newlines.
5. An empty input string yields `[""]` (one empty field), matching the
   behaviour of `csv.reader(["", ])`.

## Examples

| Input | Expected output |
|-------|-----------------|
| `a,b,c` | `["a", "b", "c"]` |
| `"a","b","c"` | `["a", "b", "c"]` |
| `a,"b,c",d` | `["a", "b,c", "d"]` |
| `a,"b""c",d` | `["a", 'b"c', "d"]` |
| `,,` | `["", "", ""]` |
| `"Seattle, WA",98101` | `["Seattle, WA", "98101"]` |
| `` (empty) | `[""]` |

## Output

Write your implementation to `output/solution.py`. The file must define:

```python
def parse_csv_line(line: str) -> list[str]:
    ...
```

You may use any Python standard library module. No third-party packages are
needed. Using `csv.reader` is acceptable — we want a correct reference
implementation, not a from-scratch reimplementation.

## Verification

Run `python verify.py` to confirm `output/solution.py` imports and exposes
`parse_csv_line`. The hidden grader runs 20 fixed cases.
