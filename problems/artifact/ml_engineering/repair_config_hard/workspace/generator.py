#!/usr/bin/env python3
"""Workspace generator for ``ml_engineering__repair_config_*``.

Produces a broken ML training config YAML at ``config.yaml`` in the output
directory.  A companion ``validate.py`` in the workspace lets the agent
iteratively check which rules are failing.

Difficulty parameters (selected by ``--instance-id``):

  * ``repair_config_easy``   — 2 independent violations (R02, R07)
  * ``repair_config_medium`` — 5 violations: R01→R03 chain, R09→R10 chain, R06
  * ``repair_config_hard``   — 12 violations: two cascading chains + cross-field rules

The ``(seed, instance_id)`` pair fully determines the output.  Valid field
values are randomised within their legal ranges using the seed; violation
mutations are then applied on top.
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Difficulty table
# Each entry lists the violation keys to inject.  Order matters for
# documentation only — the generator applies all at once.
# ---------------------------------------------------------------------------

_DIFFICULTY: Dict[str, List[str]] = {
    "repair_config_easy": [
        "lr_negative",          # R02: learning_rate < 0
        "batch_zero",           # R07: batch_size == 0
    ],
    "repair_config_medium": [
        "optimizer_invalid",    # R01: optimizer not in valid set
        "momentum_negative",    # R03: momentum < 0 (hidden until optimizer fixed)
        "weight_decay_negative", # R06: weight_decay < 0
        "scheduler_invalid",    # R09: scheduler not in valid set
        "warmup_negative",      # R10: warmup_epochs < 0 (hidden until scheduler fixed)
    ],
    "repair_config_hard": [
        "optimizer_invalid",    # R01
        "lr_too_large",         # R02: learning_rate > 1
        "momentum_negative",    # R03 (hidden until optimizer fixed)
        "weight_decay_negative", # R06
        "scheduler_invalid",    # R09
        "step_size_zero",       # R11 (hidden until scheduler == step)
        "gamma_too_large",      # R12 (hidden until scheduler == step)
        "warmup_overflow",      # R19 cross-field (warmup_epochs >= num_epochs)
        "arch_invalid",         # R13
        "num_classes_zero",     # R14
        "dropout_too_large",    # R15
        "splits_sum_too_large", # R18 cross-field (val_split + test_split >= 0.5)
    ],
}


def _slug_from_instance_id(instance_id: str) -> str:
    parts = instance_id.split("__", 1)
    return parts[1] if len(parts) == 2 else instance_id


def _build_golden(rng: random.Random) -> Dict[str, Any]:
    """Return a fully-valid config with seed-randomised values."""
    lr = round(rng.uniform(0.001, 0.09), 5)
    momentum = round(rng.uniform(0.80, 0.95), 3)
    beta1 = round(rng.uniform(0.85, 0.95), 3)
    beta2 = round(rng.uniform(0.990, 0.999), 4)
    weight_decay = round(rng.uniform(1e-5, 1e-3), 6)
    batch_size = rng.choice([16, 32, 64, 128])
    num_epochs = rng.randint(50, 200)
    warmup_epochs = rng.randint(2, min(10, num_epochs - 1))
    step_size = rng.randint(5, 20)
    gamma = round(rng.uniform(0.1, 0.5), 2)
    num_classes = rng.randint(2, 1000)
    dropout = round(rng.uniform(0.0, 0.4), 2)
    val_split = round(rng.uniform(0.05, 0.15), 3)
    test_split = round(rng.uniform(0.05, 0.15), 3)

    return {
        "training": {
            "optimizer": "sgd",
            "learning_rate": lr,
            "momentum": momentum,
            "beta1": beta1,
            "beta2": beta2,
            "weight_decay": weight_decay,
            "batch_size": batch_size,
            "num_epochs": num_epochs,
            "scheduler": "step",
            "warmup_epochs": warmup_epochs,
            "step_size": step_size,
            "gamma": gamma,
        },
        "model": {
            "arch": "resnet50",
            "num_classes": num_classes,
            "dropout": dropout,
        },
        "data": {
            "val_split": val_split,
            "test_split": test_split,
            "augmentation": True,
        },
    }


def _apply_violations(cfg: Dict[str, Any], violations: List[str], rng: random.Random) -> None:
    """Mutate *cfg* in-place to introduce the listed violations."""
    tr = cfg["training"]
    mo = cfg["model"]
    da = cfg["data"]

    for v in violations:
        if v == "lr_negative":
            tr["learning_rate"] = round(-rng.uniform(0.001, 0.1), 5)
        elif v == "lr_too_large":
            tr["learning_rate"] = round(rng.uniform(1.1, 5.0), 3)
        elif v == "batch_zero":
            tr["batch_size"] = 0
        elif v == "optimizer_invalid":
            tr["optimizer"] = "sgd_v2"
        elif v == "momentum_negative":
            tr["momentum"] = round(-rng.uniform(0.1, 0.9), 3)
        elif v == "weight_decay_negative":
            tr["weight_decay"] = round(-rng.uniform(1e-4, 1e-3), 6)
        elif v == "scheduler_invalid":
            tr["scheduler"] = "plateau"
        elif v == "warmup_negative":
            tr["warmup_epochs"] = -rng.randint(1, 10)
        elif v == "warmup_overflow":
            # warmup_epochs >= num_epochs — individually valid (>= 0) but cross-field fail
            tr["warmup_epochs"] = tr["num_epochs"] + rng.randint(10, 50)
        elif v == "step_size_zero":
            tr["step_size"] = 0
        elif v == "gamma_too_large":
            tr["gamma"] = round(rng.uniform(1.1, 2.0), 2)
        elif v == "arch_invalid":
            mo["arch"] = "vgg19"
        elif v == "num_classes_zero":
            mo["num_classes"] = 0
        elif v == "dropout_too_large":
            mo["dropout"] = round(rng.uniform(1.0, 1.9), 2)
        elif v == "splits_sum_too_large":
            # Each individually valid (< 0.5) but sum >= 0.5
            da["val_split"] = 0.28
            da["test_split"] = 0.28


def _dump_yaml(cfg: Dict[str, Any]) -> str:
    """Minimal YAML serialiser — avoids a PyYAML import in the generator."""
    lines: List[str] = []
    for section, fields in cfg.items():
        lines.append(f"{section}:")
        for key, val in fields.items():
            if isinstance(val, bool):
                lines.append(f"  {key}: {'true' if val else 'false'}")
            elif isinstance(val, float):
                lines.append(f"  {key}: {val}")
            elif isinstance(val, int):
                lines.append(f"  {key}: {val}")
            else:
                lines.append(f"  {key}: {val}")
        lines.append("")
    return "\n".join(lines)


def generate(output_dir: Path, seed: int, instance_id: str) -> None:
    slug = _slug_from_instance_id(instance_id)
    violations = _DIFFICULTY.get(slug)
    if violations is None:
        raise ValueError(f"Unknown instance_id slug: {slug!r}")

    rng = random.Random(seed)
    cfg = _build_golden(rng)
    viol_rng = random.Random((seed * 1_000_003) & 0xFFFF_FFFF)
    _apply_violations(cfg, violations, viol_rng)

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "config.yaml").write_text(_dump_yaml(cfg))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--instance-id", type=str, required=True)
    args = ap.parse_args()
    generate(args.output_dir, args.seed, args.instance_id)


if __name__ == "__main__":
    main()
