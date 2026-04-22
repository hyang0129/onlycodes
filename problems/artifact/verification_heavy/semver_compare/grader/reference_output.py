"""Reference implementation of compare_semver for verification_heavy__semver_compare.

Implements SemVer v2.0.0 precedence rules:
  - numeric compare on MAJOR.MINOR.PATCH
  - pre-release lowers precedence vs no pre-release
  - pre-release identifier compare: numeric < alphanumeric; numerics by int;
    alphas by ASCII; shorter prefix wins when all shared identifiers equal
  - build metadata ignored
"""


def _split(version: str) -> tuple[tuple[int, int, int], list[str] | None]:
    # strip build metadata
    plus = version.find("+")
    if plus >= 0:
        version = version[:plus]
    # split pre-release
    dash = version.find("-")
    if dash >= 0:
        core, pre = version[:dash], version[dash + 1 :].split(".")
    else:
        core, pre = version, None
    major, minor, patch = (int(x) for x in core.split("."))
    return (major, minor, patch), pre


def _cmp_ident(x: str, y: str) -> int:
    x_num = x.isdigit()
    y_num = y.isdigit()
    if x_num and y_num:
        xi, yi = int(x), int(y)
        return -1 if xi < yi else (1 if xi > yi else 0)
    if x_num and not y_num:
        return -1  # numeric < alphanumeric
    if y_num and not x_num:
        return 1
    # both alphanumeric: ASCII lex
    return -1 if x < y else (1 if x > y else 0)


def compare_semver(a: str, b: str) -> int:
    (am, an, ap), apre = _split(a)
    (bm, bn, bp), bpre = _split(b)

    for x, y in ((am, bm), (an, bn), (ap, bp)):
        if x < y:
            return -1
        if x > y:
            return 1

    # Core equal. Pre-release rules: presence lowers precedence.
    if apre is None and bpre is None:
        return 0
    if apre is None:
        return 1
    if bpre is None:
        return -1

    # Both have pre-release lists.
    for xi, yi in zip(apre, bpre):
        c = _cmp_ident(xi, yi)
        if c != 0:
            return c
    # Shared identifiers equal — shorter list is lower.
    if len(apre) < len(bpre):
        return -1
    if len(apre) > len(bpre):
        return 1
    return 0
