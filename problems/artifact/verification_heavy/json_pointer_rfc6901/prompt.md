# Task: Implement a JSON Pointer (RFC 6901) resolver and setter

Our config system stores nested JSON blobs, and reviewers keep pasting things
like `/services/api/timeouts/read_s` into PR comments to refer to specific
fields. We want a small utility that supports **JSON Pointer** (RFC 6901) on
in-memory Python objects loaded from JSON (so `dict`, `list`, `str`, `int`,
`float`, `bool`, `None`).

Implement two functions in `output/solution.py`:

```python
def resolve(doc, pointer: str):
    """Return the value in doc referenced by pointer.

    Raise KeyError if any step cannot be resolved (missing dict key,
    out-of-range array index, or traversal into a non-container).
    Raise ValueError for syntactically invalid pointers.
    """

def set_at(doc, pointer: str, value):
    """Mutate doc in place: set the value referenced by pointer.

    For array targets, an index equal to the current length (or the literal
    '-') APPENDS. Out-of-range positive indices beyond length raise KeyError.
    The parent of the target must exist; intermediate containers are NOT
    auto-created.
    Raise ValueError for syntactically invalid pointers.
    Setting at the root pointer ("") is not supported — raise ValueError.
    """
```

## Pointer syntax (RFC 6901)

- A pointer is a possibly-empty string.
- The empty string `""` refers to the whole document.
- Otherwise, a pointer starts with `/` and is a sequence of reference tokens
  separated by `/`.
- A syntactically invalid pointer (non-empty, does not start with `/`) raises
  `ValueError`.
- Inside a reference token:
  - `~1` decodes to `/`
  - `~0` decodes to `~`
  - The order matters: decode `~1` first, then `~0`.
- Array indices are decimal strings with no leading zeros (except the literal
  `"0"`). Negative indices are not allowed.
- The literal token `-` on an array refers to "one past the last element"
  (used by `set_at` to append; `resolve` must raise `KeyError` on `-`).

## Examples

```python
doc = {"a": {"b": [10, 20, {"c~d/e": "ok"}]}, "": "empty-key"}

resolve(doc, "")                       == doc
resolve(doc, "/a/b/0")                 == 10
resolve(doc, "/a/b/2/c~0d~1e")         == "ok"
resolve(doc, "/")                      == "empty-key"   # key = ""
resolve(doc, "/a/b/5")  # raises KeyError

set_at(doc, "/a/b/0", 99)              # doc["a"]["b"][0] == 99
set_at(doc, "/a/b/-", 40)              # appends 40 to doc["a"]["b"]
set_at(doc, "/a/b/3", 50)              # appends (index == len) 50
set_at(doc, "/a/new", {"x": 1})        # creates new key on existing dict
set_at(doc, "/nope/inner", 1)  # raises KeyError — parent missing
set_at(doc, "", {"wipe": True})  # raises ValueError — root not supported
```

## Output

Write your implementation to `output/solution.py`. Standard library only.

## Verification

Run `python verify.py` to confirm the module loads and exposes both
functions. The hidden grader runs 30 mixed resolve/set cases.
