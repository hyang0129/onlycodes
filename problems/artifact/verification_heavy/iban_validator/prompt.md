# Task: Validate IBAN numbers (ISO 13616)

Our payments microservice keeps letting through payment instructions with
malformed IBAN numbers — usually because someone transcribed them by hand and
a digit was wrong. We need a validator that catches both **format** errors
(wrong length for the country, wrong character class in the BBAN) and the
**mod-97 checksum** (ISO 13616 / ISO 7064) that IBAN uses to detect single-
digit typos and most two-digit transpositions.

Implement `validate_iban(s: str) -> bool` in `output/solution.py`.

## Validation rules

1. Strip ASCII spaces from `s` and uppercase the result. After stripping the
   IBAN must consist only of ASCII letters and digits.
2. The first two characters must be letters (the country code) and must be one
   of the supported countries in the length table below. The next two
   characters must be digits (the check digits).
3. The **total length** after stripping must match the length associated with
   the country code in the table.
4. The BBAN (everything after the 4th character) must match the BBAN structure
   in the table (see below). If any character is outside its declared class,
   the IBAN is invalid.
5. **Mod-97 check**: move the first 4 characters to the end, then replace each
   letter with two digits (A=10, B=11, ..., Z=35). Interpret the resulting
   digit string as a single integer; it must equal `1 mod 97`.

Return `True` iff all checks pass. Return `False` for any violation (including
None / non-string inputs). Do not raise.

## Supported countries and structures

| CC | Total length | BBAN structure (after `CCkk`) |
|----|--------------|-------------------------------|
| DE | 22 | 18 digits |
| GB | 22 | 4 letters, 14 digits |
| FR | 27 | 10 digits, 11 alphanumeric, 2 digits |
| ES | 24 | 20 digits |
| IT | 27 | 1 letter, 10 digits, 12 alphanumeric |
| NL | 18 | 4 letters, 10 digits |
| CH | 21 | 5 digits, 12 alphanumeric |
| BE | 16 | 12 digits |

Any country code not in this table → `False` (do not attempt to validate).

"alphanumeric" means ASCII letter or ASCII digit.

## Examples

| Input | Output |
|-------|--------|
| `"DE89 3704 0044 0532 0130 00"` | `True` |
| `"DE89370400440532013000"` | `True` |
| `"GB82WEST12345698765432"` | `True` |
| `"FR1420041010050500013M02606"` | `True` |
| `"BE68539007547034"` | `True` |
| `"DE89370400440532013001"` | `False` (wrong checksum) |
| `"DE8937040044053201300"` | `False` (wrong length) |
| `"XX89370400440532013000"` | `False` (unknown country) |
| `"GB82XEST12345698765432"` | `True` if checksum holds — but this example is synthetic; real graders use known-valid / deliberately-broken IBANs |
| `""` | `False` |
| `None` | `False` |

## Output

Write your implementation to `output/solution.py`:

```python
def validate_iban(s) -> bool:
    ...
```

Standard library only. No third-party `schwifty`, `iban`, `pycountry`, etc.

## Verification

Run `python verify.py` for a structural check. The hidden grader runs 25
positive and negative cases including malformed inputs, unknown countries,
character-class violations, and checksum mutations.
