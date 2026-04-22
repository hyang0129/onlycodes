#!/usr/bin/env python3
"""Workspace generator for stateful_reasoning__feature_flag_timeline.

Writes ``flag_events.jsonl`` with enable/disable events across a set of
flag names, deliberately including idempotent events (re-enable while
already enabled) to exercise the toggle_count rule. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

_N_EVENTS = 300
_FLAGS = [
    "checkout.v2",
    "search.fuzzy",
    "ranking.ml",
    "onboarding.tour",
    "billing.usage_meter",
    "inbox.priority",
    "notifications.digest",
    "dashboard.beta",
    "auth.mfa_required",
    "api.gzip",
]


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    path = output_dir / "flag_events.jsonl"
    with open(path, "w") as f:
        for _ in range(_N_EVENTS):
            flag = rng.choice(_FLAGS)
            action = "enable" if rng.random() < 0.5 else "disable"
            f.write(json.dumps({"flag": flag, "action": action}) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--instance-id", type=str, required=False, default="")
    args = ap.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    generate(args.output_dir, args.seed)


if __name__ == "__main__":
    main()
