"""Structural verifier for ml_engineering__repair_config_{easy,medium,hard}.

Checks that ``output/config.yaml`` exists, is valid YAML, and contains the
required top-level sections and sub-keys.

Does NOT check rule compliance — that is the hidden grader's job.
Run this to confirm output structure before a grading run.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import yaml  # type: ignore
except ImportError:
    print("FAIL: PyYAML is not installed; run: pip install pyyaml")
    sys.exit(1)

_REQUIRED_KEYS: dict[str, set[str]] = {
    "training": {
        "optimizer", "learning_rate", "momentum", "beta1", "beta2",
        "weight_decay", "batch_size", "num_epochs", "scheduler",
        "warmup_epochs", "step_size", "gamma",
    },
    "model": {"arch", "num_classes", "dropout"},
    "data": {"val_split", "test_split", "augmentation"},
}


def main(scratch_dir: str | None = None) -> None:
    base = Path(scratch_dir) if scratch_dir else Path(__file__).parent
    output_path = base / "output" / "config.yaml"

    if not output_path.is_file():
        print("FAIL: output/config.yaml not found")
        sys.exit(1)

    try:
        cfg = yaml.safe_load(output_path.read_text())
    except Exception as exc:
        print(f"FAIL: could not parse output/config.yaml: {exc}")
        sys.exit(1)

    if not isinstance(cfg, dict):
        print("FAIL: output/config.yaml must be a YAML mapping at the top level")
        sys.exit(1)

    errors: list[str] = []

    extra_top = set(cfg.keys()) - set(_REQUIRED_KEYS.keys())
    if extra_top:
        errors.append(f"unexpected top-level keys: {sorted(extra_top)}")

    for section, required_sub in _REQUIRED_KEYS.items():
        if section not in cfg:
            errors.append(f"missing top-level section: {section!r}")
            continue
        sub = cfg[section]
        if not isinstance(sub, dict):
            errors.append(f"section {section!r} must be a mapping")
            continue
        missing = required_sub - set(sub.keys())
        if missing:
            errors.append(f"section {section!r} missing keys: {sorted(missing)}")

    if errors:
        for err in errors:
            print(f"FAIL: {err}")
        sys.exit(1)

    print("OK: output/config.yaml is structurally valid")
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
