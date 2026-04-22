"""Hidden grader for verification_heavy__iban_validator.

25 cases: well-known valid IBANs (DE/GB/FR/ES/IT/NL/CH/BE), space-formatted
inputs, bad-checksum mutations, wrong length, wrong country, letter/digit
class violations, and non-string inputs.
"""

from __future__ import annotations

import importlib.util
import traceback
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GradeResult:
    passed: bool
    score: float
    detail: str


OUTPUT_REL = "output/solution.py"


def _import_module(solution_path: Path):
    spec = importlib.util.spec_from_file_location("agent_solution", solution_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# (input, expected)
_TESTS: list[tuple[object, bool]] = [
    # Valid examples (all verified mod-97-ok)
    ("DE89370400440532013000",                  True),
    ("DE89 3704 0044 0532 0130 00",             True),
    ("de89370400440532013000",                  True),  # lowercase ok
    ("GB82WEST12345698765432",                  True),
    ("FR1420041010050500013M02606",             True),
    ("ES9121000418450200051332",                True),
    ("IT60X0542811101000000123456",             True),
    ("NL91ABNA0417164300",                      True),
    ("CH9300762011623852957",                   True),
    ("BE68539007547034",                        True),
    # Bad checksum (toggle last digit)
    ("DE89370400440532013001",                  False),
    ("GB82WEST12345698765431",                  False),
    ("BE68539007547035",                        False),
    # Wrong length
    ("DE8937040044053201300",                   False),   # 21, need 22
    ("DE893704004405320130001",                 False),  # 23
    # Unknown country code
    ("XX89370400440532013000",                  False),
    ("US89370400440532013000",                  False),
    # Structure violations
    ("GB82W3ST12345698765432",                  False),   # digit in letter slot
    ("NL91ABNA041716430A",                      False),   # letter where digit expected
    # Garbage / missing bits
    ("",                                        False),
    ("DE",                                      False),
    ("DE89",                                    False),
    ("DE893704004405320130AB",                  False),   # letters in all-digit BBAN
    # Non-string / None
    (None,                                      False),
    (1234567890,                                False),
]


def grade(scratch_dir: Path) -> GradeResult:
    scratch_dir = Path(scratch_dir).resolve()
    solution_path = scratch_dir / OUTPUT_REL

    if not solution_path.is_file():
        return GradeResult(False, 0.0, "output artifact not produced (output/solution.py missing)")

    try:
        mod = _import_module(solution_path)
    except Exception as exc:
        tb = traceback.format_exc()
        return GradeResult(False, 0.0, f"failed to import solution.py: {exc}\n{tb[:400]}")

    if not hasattr(mod, "validate_iban"):
        return GradeResult(False, 0.0, "solution.py does not define 'validate_iban'")

    fn = mod.validate_iban
    failures: list[str] = []
    for inp, expected in _TESTS:
        try:
            got = fn(inp)
        except Exception as exc:
            failures.append(f"  validate_iban({inp!r}): raised {type(exc).__name__}: {exc}")
            continue
        if got is not expected:  # strict True/False (not truthy)
            failures.append(f"  validate_iban({inp!r}): expected {expected}, got {got!r}")

    n_pass = len(_TESTS) - len(failures)
    if failures:
        detail = f"{n_pass}/{len(_TESTS)} cases passed. Failures:\n" + "\n".join(failures)
        return GradeResult(False, round(n_pass / len(_TESTS), 4), detail)
    return GradeResult(True, 1.0, f"all {len(_TESTS)} cases passed")
