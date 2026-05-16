#!/usr/bin/env python3
"""Validate an ML training config YAML against a fixed rule set.

Usage:
    python validate.py config.yaml

Prints one line per failing or skipped rule, then a summary.
Exits 0 if all applicable rules pass, 1 otherwise.

Rules
-----
R01  training.optimizer    must be in {sgd, adam, rmsprop, adamw}
R02  training.learning_rate must be float in (0, 1)
R03  training.momentum     must be float in [0, 1)   — only when optimizer in {sgd, rmsprop}
R04  training.beta1        must be float in (0, 1)   — only when optimizer in {adam, adamw}
R05  training.beta2        must be float in (0, 1)   — only when optimizer in {adam, adamw}
R06  training.weight_decay must be float >= 0
R07  training.batch_size   must be int >= 1
R08  training.num_epochs   must be int >= 1
R09  training.scheduler    must be in {cosine, step, linear, none}
R10  training.warmup_epochs must be int >= 0         — only when scheduler != none
R11  training.step_size    must be int >= 1          — only when scheduler == step
R12  training.gamma        must be float in (0, 1]   — only when scheduler == step
R13  model.arch            must be in {resnet18, resnet50, vgg16, efficientnet_b0}
R14  model.num_classes     must be int >= 1
R15  model.dropout         must be float in [0, 1)
R16  data.val_split        must be float in (0, 0.5)
R17  data.test_split       must be float in (0, 0.5)
R18  cross-field           val_split + test_split must be < 0.5
                           (only checked when R16 and R17 both pass)
R19  cross-field           warmup_epochs must be < num_epochs
                           (only checked when R08 and R10 both pass)
R20  data.augmentation     must be bool
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import yaml  # type: ignore
except ImportError:
    print("FAIL: PyYAML is not installed; run: pip install pyyaml")
    sys.exit(1)

_VALID_OPTIMIZERS = {"sgd", "adam", "rmsprop", "adamw"}
_VALID_SCHEDULERS = {"cosine", "step", "linear", "none"}
_VALID_ARCHS = {"resnet18", "resnet50", "vgg16", "efficientnet_b0"}


def _get(cfg: dict, *keys: str):
    """Navigate nested dict; raise KeyError on missing path."""
    node = cfg
    for k in keys:
        node = node[k]
    return node


def validate(cfg: dict) -> tuple[int, int, list[str]]:
    """Return (passing, total_applicable, failing_rule_ids)."""
    failures: list[str] = []
    skips: list[str] = []
    passes: list[str] = []

    def fail(rule: str, msg: str) -> None:
        failures.append(rule)
        print(f"FAIL: {rule} {msg}")

    def skip(rule: str, reason: str) -> None:
        skips.append(rule)
        print(f"SKIP: {rule} (condition not met: {reason})")

    def ok(rule: str) -> None:
        passes.append(rule)

    # ------------------------------------------------------------------ R01
    try:
        opt = _get(cfg, "training", "optimizer")
        if opt not in _VALID_OPTIMIZERS:
            fail("R01", f"training.optimizer={opt!r} must be one of {sorted(_VALID_OPTIMIZERS)}")
        else:
            ok("R01")
    except KeyError:
        fail("R01", "training.optimizer is missing")
        opt = None

    # ------------------------------------------------------------------ R02
    try:
        lr = _get(cfg, "training", "learning_rate")
        if not isinstance(lr, (int, float)) or not (0 < lr < 1):
            fail("R02", f"training.learning_rate={lr!r} must be float in (0, 1)")
        else:
            ok("R02")
    except KeyError:
        fail("R02", "training.learning_rate is missing")

    # ------------------------------------------------------------------ R03 (conditional)
    try:
        opt_val = _get(cfg, "training", "optimizer")
    except KeyError:
        opt_val = None
    if opt_val in {"sgd", "rmsprop"}:
        try:
            mom = _get(cfg, "training", "momentum")
            if not isinstance(mom, (int, float)) or not (0 <= mom < 1):
                fail("R03", f"training.momentum={mom!r} must be float in [0, 1)")
            else:
                ok("R03")
        except KeyError:
            fail("R03", "training.momentum is missing (required when optimizer is sgd or rmsprop)")
    else:
        skip("R03", f"optimizer={opt_val!r} is not sgd/rmsprop")

    # ------------------------------------------------------------------ R04 (conditional)
    if opt_val in {"adam", "adamw"}:
        try:
            b1 = _get(cfg, "training", "beta1")
            if not isinstance(b1, (int, float)) or not (0 < b1 < 1):
                fail("R04", f"training.beta1={b1!r} must be float in (0, 1)")
            else:
                ok("R04")
        except KeyError:
            fail("R04", "training.beta1 is missing (required when optimizer is adam or adamw)")
    else:
        skip("R04", f"optimizer={opt_val!r} is not adam/adamw")

    # ------------------------------------------------------------------ R05 (conditional)
    if opt_val in {"adam", "adamw"}:
        try:
            b2 = _get(cfg, "training", "beta2")
            if not isinstance(b2, (int, float)) or not (0 < b2 < 1):
                fail("R05", f"training.beta2={b2!r} must be float in (0, 1)")
            else:
                ok("R05")
        except KeyError:
            fail("R05", "training.beta2 is missing (required when optimizer is adam or adamw)")
    else:
        skip("R05", f"optimizer={opt_val!r} is not adam/adamw")

    # ------------------------------------------------------------------ R06
    try:
        wd = _get(cfg, "training", "weight_decay")
        if not isinstance(wd, (int, float)) or wd < 0:
            fail("R06", f"training.weight_decay={wd!r} must be float >= 0")
        else:
            ok("R06")
    except KeyError:
        fail("R06", "training.weight_decay is missing")

    # ------------------------------------------------------------------ R07
    try:
        bs = _get(cfg, "training", "batch_size")
        if not isinstance(bs, int) or bs < 1:
            fail("R07", f"training.batch_size={bs!r} must be int >= 1")
        else:
            ok("R07")
    except KeyError:
        fail("R07", "training.batch_size is missing")

    # ------------------------------------------------------------------ R08
    r08_passes = False
    try:
        ne = _get(cfg, "training", "num_epochs")
        if not isinstance(ne, int) or ne < 1:
            fail("R08", f"training.num_epochs={ne!r} must be int >= 1")
        else:
            ok("R08")
            r08_passes = True
    except KeyError:
        fail("R08", "training.num_epochs is missing")

    # ------------------------------------------------------------------ R09
    r09_passes = False
    try:
        sch = _get(cfg, "training", "scheduler")
        if sch not in _VALID_SCHEDULERS:
            fail("R09", f"training.scheduler={sch!r} must be one of {sorted(_VALID_SCHEDULERS)}")
        else:
            ok("R09")
            r09_passes = True
    except KeyError:
        fail("R09", "training.scheduler is missing")
        sch = None

    try:
        sch_val = _get(cfg, "training", "scheduler")
    except KeyError:
        sch_val = None

    # ------------------------------------------------------------------ R10 (conditional)
    r10_passes = False
    if r09_passes and sch_val != "none":
        try:
            we = _get(cfg, "training", "warmup_epochs")
            if not isinstance(we, int) or we < 0:
                fail("R10", f"training.warmup_epochs={we!r} must be int >= 0")
            else:
                ok("R10")
                r10_passes = True
        except KeyError:
            fail("R10", "training.warmup_epochs is missing (required when scheduler != none)")
    elif r09_passes and sch_val == "none":
        skip("R10", "scheduler is 'none' — warmup_epochs not required")
        r10_passes = True  # vacuously passes for cross-field purposes
    else:
        skip("R10", f"scheduler={sch_val!r} is invalid (fix R09 first)")

    # ------------------------------------------------------------------ R11 (conditional)
    if r09_passes and sch_val == "step":
        try:
            ss = _get(cfg, "training", "step_size")
            if not isinstance(ss, int) or ss < 1:
                fail("R11", f"training.step_size={ss!r} must be int >= 1")
            else:
                ok("R11")
        except KeyError:
            fail("R11", "training.step_size is missing (required when scheduler == step)")
    else:
        skip("R11", f"scheduler={sch_val!r} is not 'step'")

    # ------------------------------------------------------------------ R12 (conditional)
    if r09_passes and sch_val == "step":
        try:
            gm = _get(cfg, "training", "gamma")
            if not isinstance(gm, (int, float)) or not (0 < gm <= 1):
                fail("R12", f"training.gamma={gm!r} must be float in (0, 1]")
            else:
                ok("R12")
        except KeyError:
            fail("R12", "training.gamma is missing (required when scheduler == step)")
    else:
        skip("R12", f"scheduler={sch_val!r} is not 'step'")

    # ------------------------------------------------------------------ R13
    try:
        arch = _get(cfg, "model", "arch")
        if arch not in _VALID_ARCHS:
            fail("R13", f"model.arch={arch!r} must be one of {sorted(_VALID_ARCHS)}")
        else:
            ok("R13")
    except KeyError:
        fail("R13", "model.arch is missing")

    # ------------------------------------------------------------------ R14
    try:
        nc = _get(cfg, "model", "num_classes")
        if not isinstance(nc, int) or nc < 1:
            fail("R14", f"model.num_classes={nc!r} must be int >= 1")
        else:
            ok("R14")
    except KeyError:
        fail("R14", "model.num_classes is missing")

    # ------------------------------------------------------------------ R15
    try:
        dp = _get(cfg, "model", "dropout")
        if not isinstance(dp, (int, float)) or not (0 <= dp < 1):
            fail("R15", f"model.dropout={dp!r} must be float in [0, 1)")
        else:
            ok("R15")
    except KeyError:
        fail("R15", "model.dropout is missing")

    # ------------------------------------------------------------------ R16
    r16_passes = False
    try:
        vs = _get(cfg, "data", "val_split")
        if not isinstance(vs, (int, float)) or not (0 < vs < 0.5):
            fail("R16", f"data.val_split={vs!r} must be float in (0, 0.5)")
        else:
            ok("R16")
            r16_passes = True
    except KeyError:
        fail("R16", "data.val_split is missing")

    # ------------------------------------------------------------------ R17
    r17_passes = False
    try:
        ts = _get(cfg, "data", "test_split")
        if not isinstance(ts, (int, float)) or not (0 < ts < 0.5):
            fail("R17", f"data.test_split={ts!r} must be float in (0, 0.5)")
        else:
            ok("R17")
            r17_passes = True
    except KeyError:
        fail("R17", "data.test_split is missing")

    # ------------------------------------------------------------------ R18 (cross-field)
    if r16_passes and r17_passes:
        vs2 = _get(cfg, "data", "val_split")
        ts2 = _get(cfg, "data", "test_split")
        total = vs2 + ts2
        if total >= 0.5:
            fail("R18", f"val_split + test_split = {total:.4f} must be < 0.5")
        else:
            ok("R18")
    else:
        skip("R18", "val_split or test_split is invalid (fix R16/R17 first)")

    # ------------------------------------------------------------------ R19 (cross-field)
    if r08_passes and r10_passes:
        we2 = _get(cfg, "training", "warmup_epochs")
        ne2 = _get(cfg, "training", "num_epochs")
        if we2 >= ne2:
            fail("R19", f"warmup_epochs={we2} must be < num_epochs={ne2}")
        else:
            ok("R19")
    else:
        skip("R19", "num_epochs or warmup_epochs is invalid (fix R08/R10 first)")

    # ------------------------------------------------------------------ R20
    try:
        aug = _get(cfg, "data", "augmentation")
        if not isinstance(aug, bool):
            fail("R20", f"data.augmentation={aug!r} must be bool (true or false)")
        else:
            ok("R20")
    except KeyError:
        fail("R20", "data.augmentation is missing")

    total_applicable = len(passes) + len(failures)
    return len(passes), total_applicable, failures


def main(config_path_arg: str | None = None) -> None:
    if config_path_arg is None:
        if len(sys.argv) < 2:
            print("Usage: python validate.py <config.yaml>")
            sys.exit(1)
        config_path_arg = sys.argv[1]

    config_path = Path(config_path_arg)
    if not config_path.is_file():
        print(f"FAIL: {config_path} not found")
        sys.exit(1)

    try:
        cfg = yaml.safe_load(config_path.read_text())
    except Exception as exc:
        print(f"FAIL: could not parse YAML: {exc}")
        sys.exit(1)

    if not isinstance(cfg, dict):
        print("FAIL: config must be a YAML mapping (dict at the top level)")
        sys.exit(1)

    passing, total, failing_ids = validate(cfg)

    if failing_ids:
        print(f"\nRESULT: {passing}/{total} rules passing — FAIL ({', '.join(failing_ids)})")
        sys.exit(1)
    else:
        print(f"\nRESULT: {passing}/{total} rules passing — PASS")
        sys.exit(0)


if __name__ == "__main__":
    main()
