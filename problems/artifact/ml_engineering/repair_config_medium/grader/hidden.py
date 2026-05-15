"""Hidden grader for ml_engineering__repair_config_{easy,medium,hard}.

Scores the agent's ``output/config.yaml`` by counting how many of the 20
defined validation rules pass.

    score = rules_passing / total_applicable_rules

A rule is "applicable" if its condition is met (e.g. R03 is only applicable
when optimizer is sgd/rmsprop).  Skipped rules do not count toward
``total_applicable_rules``, so an agent that changes the optimizer to adam
is not penalised for not having a valid momentum.

``passed`` is True only when ``score == 1.0`` (all applicable rules pass).
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import yaml  # type: ignore
except ImportError:
    # This should not happen in normal harness operation.
    yaml = None  # type: ignore

# Grader must be importable as a module from any CWD.
_THIS_DIR = Path(__file__).parent


def _safe_yaml_load(text: str):
    if yaml is None:
        raise ImportError("PyYAML not available")
    return yaml.safe_load(text)


_VALID_OPTIMIZERS = {"sgd", "adam", "rmsprop", "adamw"}
_VALID_SCHEDULERS = {"cosine", "step", "linear", "none"}
_VALID_ARCHS = {"resnet18", "resnet50", "vgg16", "efficientnet_b0"}


def _get(cfg: dict, *keys: str):
    node = cfg
    for k in keys:
        node = node[k]
    return node


def _count_rules(cfg: dict) -> tuple[int, int, list[str]]:
    """Return (passing, total_applicable, list_of_failing_rule_ids)."""
    passing = 0
    total = 0
    failing: list[str] = []

    def check(rule_id: str, ok: bool) -> None:
        nonlocal passing, total
        total += 1
        if ok:
            passing += 1
        else:
            failing.append(rule_id)

    # R01
    try:
        opt = _get(cfg, "training", "optimizer")
        r01_ok = opt in _VALID_OPTIMIZERS
    except KeyError:
        opt = None
        r01_ok = False
    check("R01", r01_ok)

    # R02
    try:
        lr = _get(cfg, "training", "learning_rate")
        check("R02", isinstance(lr, (int, float)) and 0 < lr < 1)
    except KeyError:
        check("R02", False)

    # R03 — conditional on optimizer in {sgd, rmsprop}
    try:
        opt_val = _get(cfg, "training", "optimizer")
    except KeyError:
        opt_val = None
    if opt_val in {"sgd", "rmsprop"}:
        try:
            mom = _get(cfg, "training", "momentum")
            check("R03", isinstance(mom, (int, float)) and 0 <= mom < 1)
        except KeyError:
            check("R03", False)
    # else: skipped, not counted

    # R04 — conditional on optimizer in {adam, adamw}
    if opt_val in {"adam", "adamw"}:
        try:
            b1 = _get(cfg, "training", "beta1")
            check("R04", isinstance(b1, (int, float)) and 0 < b1 < 1)
        except KeyError:
            check("R04", False)

    # R05 — conditional on optimizer in {adam, adamw}
    if opt_val in {"adam", "adamw"}:
        try:
            b2 = _get(cfg, "training", "beta2")
            check("R05", isinstance(b2, (int, float)) and 0 < b2 < 1)
        except KeyError:
            check("R05", False)

    # R06
    try:
        wd = _get(cfg, "training", "weight_decay")
        check("R06", isinstance(wd, (int, float)) and wd >= 0)
    except KeyError:
        check("R06", False)

    # R07
    try:
        bs = _get(cfg, "training", "batch_size")
        check("R07", isinstance(bs, int) and bs >= 1)
    except KeyError:
        check("R07", False)

    # R08
    r08_ok = False
    try:
        ne = _get(cfg, "training", "num_epochs")
        r08_ok = isinstance(ne, int) and ne >= 1
        check("R08", r08_ok)
    except KeyError:
        check("R08", False)

    # R09
    r09_ok = False
    try:
        sch = _get(cfg, "training", "scheduler")
        r09_ok = sch in _VALID_SCHEDULERS
        check("R09", r09_ok)
    except KeyError:
        sch = None
        check("R09", False)

    try:
        sch_val = _get(cfg, "training", "scheduler")
    except KeyError:
        sch_val = None

    # R10 — conditional on scheduler being valid and != none
    r10_ok = False
    if r09_ok and sch_val != "none":
        try:
            we = _get(cfg, "training", "warmup_epochs")
            r10_ok = isinstance(we, int) and we >= 0
            check("R10", r10_ok)
        except KeyError:
            check("R10", False)
    elif r09_ok and sch_val == "none":
        r10_ok = True  # vacuously passes for cross-field R19

    # R11 — conditional on scheduler == step
    if r09_ok and sch_val == "step":
        try:
            ss = _get(cfg, "training", "step_size")
            check("R11", isinstance(ss, int) and ss >= 1)
        except KeyError:
            check("R11", False)

    # R12 — conditional on scheduler == step
    if r09_ok and sch_val == "step":
        try:
            gm = _get(cfg, "training", "gamma")
            check("R12", isinstance(gm, (int, float)) and 0 < gm <= 1)
        except KeyError:
            check("R12", False)

    # R13
    try:
        arch = _get(cfg, "model", "arch")
        check("R13", arch in _VALID_ARCHS)
    except KeyError:
        check("R13", False)

    # R14
    try:
        nc = _get(cfg, "model", "num_classes")
        check("R14", isinstance(nc, int) and nc >= 1)
    except KeyError:
        check("R14", False)

    # R15
    try:
        dp = _get(cfg, "model", "dropout")
        check("R15", isinstance(dp, (int, float)) and 0 <= dp < 1)
    except KeyError:
        check("R15", False)

    # R16
    r16_ok = False
    try:
        vs = _get(cfg, "data", "val_split")
        r16_ok = isinstance(vs, (int, float)) and 0 < vs < 0.5
        check("R16", r16_ok)
    except KeyError:
        check("R16", False)

    # R17
    r17_ok = False
    try:
        ts = _get(cfg, "data", "test_split")
        r17_ok = isinstance(ts, (int, float)) and 0 < ts < 0.5
        check("R17", r17_ok)
    except KeyError:
        check("R17", False)

    # R18 — cross-field, conditional on R16+R17 passing
    if r16_ok and r17_ok:
        vs2 = _get(cfg, "data", "val_split")
        ts2 = _get(cfg, "data", "test_split")
        check("R18", vs2 + ts2 < 0.5)

    # R19 — cross-field, conditional on R08+R10 passing
    if r08_ok and r10_ok:
        we2 = _get(cfg, "training", "warmup_epochs")
        ne2 = _get(cfg, "training", "num_epochs")
        check("R19", we2 < ne2)

    # R20
    try:
        aug = _get(cfg, "data", "augmentation")
        check("R20", isinstance(aug, bool))
    except KeyError:
        check("R20", False)

    return passing, total, failing


def grade(scratch_dir: str) -> "GradeResult":  # noqa: F821
    # Import here to avoid circular import when module is loaded directly.
    sys.path.insert(0, str(Path(__file__).parents[4]))
    from swebench.artifact_models import GradeResult  # type: ignore

    output_path = Path(scratch_dir) / "output" / "config.yaml"

    if not output_path.is_file():
        return GradeResult(
            passed=False,
            score=0.0,
            detail="output/config.yaml not found",
        )

    try:
        cfg = _safe_yaml_load(output_path.read_text())
    except Exception as exc:
        return GradeResult(
            passed=False,
            score=0.0,
            detail=f"could not parse output/config.yaml: {exc}",
        )

    if not isinstance(cfg, dict):
        return GradeResult(
            passed=False,
            score=0.0,
            detail="output/config.yaml must be a YAML mapping",
        )

    passing, total, failing_ids = _count_rules(cfg)

    if total == 0:
        return GradeResult(
            passed=False,
            score=0.0,
            detail="no applicable rules found — config may be empty or malformed",
        )

    score = passing / total
    passed = score == 1.0
    if failing_ids:
        detail = f"rules {passing}/{total} passing; failing: {', '.join(failing_ids)}"
    else:
        detail = f"rules {passing}/{total} passing — all applicable rules satisfied"

    return GradeResult(passed=passed, score=score, detail=detail)
