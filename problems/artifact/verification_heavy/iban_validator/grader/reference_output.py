"""Reference validate_iban() for verification_heavy__iban_validator."""

import string


# (total_length, BBAN structure as list of (kind, n))
# kind: 'N' digits, 'A' letters, 'C' alphanumeric
_COUNTRIES: dict[str, tuple[int, list[tuple[str, int]]]] = {
    "DE": (22, [("N", 18)]),
    "GB": (22, [("A", 4), ("N", 14)]),
    "FR": (27, [("N", 10), ("C", 11), ("N", 2)]),
    "ES": (24, [("N", 20)]),
    "IT": (27, [("A", 1), ("N", 10), ("C", 12)]),
    "NL": (18, [("A", 4), ("N", 10)]),
    "CH": (21, [("N", 5), ("C", 12)]),
    "BE": (16, [("N", 12)]),
}


def _matches(bban: str, structure: list[tuple[str, int]]) -> bool:
    i = 0
    for kind, n in structure:
        piece = bban[i:i + n]
        if len(piece) != n:
            return False
        if kind == "N":
            if not piece.isdigit():
                return False
        elif kind == "A":
            if not all(c in string.ascii_uppercase for c in piece):
                return False
        elif kind == "C":
            if not all(c in string.ascii_uppercase or c.isdigit() for c in piece):
                return False
        i += n
    return i == len(bban)


def validate_iban(s) -> bool:
    if not isinstance(s, str):
        return False

    # 1. strip spaces + upper
    stripped = s.replace(" ", "").upper()
    if stripped == "":
        return False
    if not all(c.isalnum() and ord(c) < 128 for c in stripped):
        return False

    # 2. structure prefix
    if len(stripped) < 4:
        return False
    cc = stripped[:2]
    check = stripped[2:4]
    if not (cc[0] in string.ascii_uppercase and cc[1] in string.ascii_uppercase):
        return False
    if not check.isdigit():
        return False

    # 3. length per country
    if cc not in _COUNTRIES:
        return False
    expected_len, structure = _COUNTRIES[cc]
    if len(stripped) != expected_len:
        return False

    # 4. BBAN structure
    if not _matches(stripped[4:], structure):
        return False

    # 5. mod-97 checksum
    rearranged = stripped[4:] + stripped[:4]
    numeric = []
    for c in rearranged:
        if c.isdigit():
            numeric.append(c)
        else:  # must be uppercase ASCII letter (A-Z)
            numeric.append(str(ord(c) - ord("A") + 10))
    big = int("".join(numeric))
    return big % 97 == 1
