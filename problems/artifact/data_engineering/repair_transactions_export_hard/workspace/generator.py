#!/usr/bin/env python3
"""Workspace generator for ``data_engineering__repair_transactions_export_hard``.

Produces ``transactions_raw.csv``: a single CSV with nine columns whose
values exhibit the schema problems described in the task prompt.

Run with ``--seed 42`` (the canonical seed) to reproduce the committed
fixture, or omit ``--out`` to write into the same directory as this script
during local authoring.

Realistic messiness injected:

* ``amount`` — drawn from a wide pool of formatting variants (plain, ``$``
  prefix, comma thousands separator, ``USD`` suffix, parenthesised negative,
  literal ``free``), with ~3% empty (must be dropped).
* ``tx_type``, ``status``, ``channel`` — drawn from a pool of synonyms plus
  a small (~5%) unmapped pool (``?``, ``unknown``, empty) which must be
  dropped.
* ``is_disputed`` / ``is_refunded`` — drawn from the eight accepted boolean
  variants.
* ``notes`` — ~40% are placeholder null markers (``N/A``, ``none``, ``-``,
  ``—``, ``?``, ``null``, empty) which must collapse to empty string; the
  rest are short free-text strings.
"""

from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

_N_ROWS = 600
_N_ACCOUNTS = 50

_TYPE_VARIANTS = {
    "deposit": ["deposit", "DEP", "depo", "D", "Deposit", "dep"],
    "withdrawal": ["withdrawal", "wd", "with", "W", "WD", "Withdrawal"],
    "transfer": ["transfer", "xfer", "TRF", "X", "Transfer"],
    "fee": ["fee", "F", "FEE", "Fee"],
}
_TYPE_UNMAPPED = ["", "?", "unknown", "refund", "chargeback"]

_STATUS_VARIANTS = {
    "completed": ["completed", "complete", "DONE", "ok", "OK", "Done"],
    "pending": ["pending", "PEND", "in progress", "wait", "Pending"],
    "failed": ["failed", "FAIL", "err", "error", "Failed"],
}
_STATUS_UNMAPPED = ["", "?", "unknown", "cancelled"]

_CHANNEL_VARIANTS = {
    "web": ["web", "WEB", "Web", "www"],
    "mobile": ["mobile", "MOB", "app", "ios", "android"],
    "branch": ["branch", "BR", "in_person", "in-person"],
    "api": ["api", "API"],
}
_CHANNEL_UNMAPPED = ["", "?", "unknown", "kiosk"]

_BOOL_TRUE = ["yes", "Y", "true", "TRUE", "1"]
_BOOL_FALSE = ["no", "N", "false", "FALSE", "0", ""]

_NOTE_NULLS = ["N/A", "n/a", "none", "None", "NULL", "null", "-", "—", "?", ""]
_NOTE_TEXTS = [
    "customer-requested refund",
    "duplicate charge flagged",
    "manual review required",
    "fraud alert resolved",
    "ATM withdrawal",
    "monthly maintenance fee",
    "wire transfer to vendor",
    "refund approved by ops",
    "scheduled payment",
    "transfer to savings",
]


def _gen_amount_string(rng: random.Random) -> str:
    """Return an amount as one of several formatting variants.

    Empty string ~3% of the time (must be dropped).
    Literal "free"/"FREE" ~2% (parses to 0.00).
    Negative-in-parens ~12%.
    Otherwise a positive amount with various formatting flourishes.
    """
    r = rng.random()
    if r < 0.03:
        return ""
    if r < 0.05:
        return rng.choice(["free", "FREE", "Free"])

    # Pick magnitude: ~30% large (>= 1000, so commas matter), rest small.
    if rng.random() < 0.30:
        value = round(rng.uniform(1000, 250000), 2)
    else:
        value = round(rng.uniform(0.5, 999.99), 2)

    negative = rng.random() < 0.12

    # Decide formatting flags.
    use_dollar = rng.random() < 0.45
    use_commas = value >= 1000 and rng.random() < 0.70
    use_usd_suffix = rng.random() < 0.20

    if use_commas:
        # Build with thousands separators.
        body = f"{value:,.2f}"
    else:
        body = f"{value:.2f}"

    if use_dollar:
        body = "$" + body
    if use_usd_suffix:
        sep = " " if rng.random() < 0.6 else ""
        body = body + sep + "USD"

    if negative:
        body = "(" + body + ")"

    return body


def _gen_tx_type(rng: random.Random) -> str:
    if rng.random() < 0.05:
        return rng.choice(_TYPE_UNMAPPED)
    canon = rng.choice(list(_TYPE_VARIANTS.keys()))
    return rng.choice(_TYPE_VARIANTS[canon])


def _gen_status(rng: random.Random) -> str:
    if rng.random() < 0.05:
        return rng.choice(_STATUS_UNMAPPED)
    canon = rng.choice(list(_STATUS_VARIANTS.keys()))
    return rng.choice(_STATUS_VARIANTS[canon])


def _gen_channel(rng: random.Random) -> str:
    if rng.random() < 0.05:
        return rng.choice(_CHANNEL_UNMAPPED)
    canon = rng.choice(list(_CHANNEL_VARIANTS.keys()))
    return rng.choice(_CHANNEL_VARIANTS[canon])


def _gen_bool(rng: random.Random) -> str:
    if rng.random() < 0.5:
        return rng.choice(_BOOL_TRUE)
    return rng.choice(_BOOL_FALSE)


def _gen_notes(rng: random.Random) -> str:
    if rng.random() < 0.40:
        return rng.choice(_NOTE_NULLS)
    return rng.choice(_NOTE_TEXTS)


def generate(out_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    rows = []
    for i in range(1, _N_ROWS + 1):
        rows.append(
            {
                "tx_id": f"T-{i:06d}",
                "account_id": f"ACCT-{rng.randint(1, _N_ACCOUNTS):03d}",
                "amount": _gen_amount_string(rng),
                "tx_type": _gen_tx_type(rng),
                "status": _gen_status(rng),
                "is_disputed": _gen_bool(rng),
                "is_refunded": _gen_bool(rng),
                "channel": _gen_channel(rng),
                "notes": _gen_notes(rng),
            }
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    cols = [
        "tx_id", "account_id", "amount", "tx_type", "status",
        "is_disputed", "is_refunded", "channel", "notes",
    ]
    with open(out_dir / "transactions_raw.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=False,
        default=Path(__file__).parent,
        help="Directory to write generated files (default: alongside generator.py)",
    )
    parser.add_argument("--instance-id", type=str, required=False, default="")
    args = parser.parse_args()
    generate(args.output_dir, args.seed)


if __name__ == "__main__":
    main()
