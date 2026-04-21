#!/usr/bin/env python3
"""Workspace generator for data_processing__p95_latency_easy.

Writes ``access.jsonl`` into the output directory: 10,000 synthetic
access-log rows with realistic per-endpoint latency distributions and a
few high-latency outliers so nearest-rank p95 is non-trivial.

Invoked by :func:`swebench.artifact_materialize.materialize`; never runs
inside the agent's sandbox. See issue #118.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

# (endpoint, base_latency_ms, tail_latency_ms, tail_fraction)
# Tail fraction is the probability a row draws from the heavy-tail range.
_ENDPOINTS = [
    ("/health",                 1.5,   5.0,   0.0),
    ("/health/live",            1.0,   4.0,   0.0),
    ("/api/v1/users",          25.0, 150.0,   0.05),
    ("/api/v1/users/:id",      20.0, 120.0,   0.04),
    ("/api/v1/auth/login",     80.0, 300.0,   0.10),
    ("/api/v1/auth/refresh",   30.0, 120.0,   0.06),
    ("/api/v1/catalog",       120.0, 450.0,   0.12),
    ("/api/v1/search",        150.0, 600.0,   0.15),
    ("/api/v1/orders",         90.0, 350.0,   0.10),
    ("/api/v1/orders/:id",     60.0, 250.0,   0.08),
    ("/api/v1/cart",           40.0, 180.0,   0.05),
    ("/api/v2/search",         90.0, 380.0,   0.10),
    ("/api/v2/recommendations", 180.0, 700.0, 0.18),
    ("/api/metrics",           10.0,  40.0,   0.02),
    ("/api/admin/reports",    300.0, 900.0,   0.20),
]

_STATUS_CHOICES = (200, 200, 200, 200, 200, 200, 200, 200, 204, 301, 404, 500)

_N_ROWS = 10_000
_TS_BASE = 1_700_000_000.0
_TS_SPAN = 1_000.0  # seconds


def generate(output_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    out = output_dir / "access.jsonl"
    with open(out, "w") as f:
        for _ in range(_N_ROWS):
            ep, base, tail, tail_frac = rng.choice(_ENDPOINTS)
            if rng.random() < tail_frac:
                latency = rng.uniform(base, tail) + rng.expovariate(1.0 / max(base, 5.0))
            else:
                latency = max(0.1, rng.gauss(base, base * 0.35))
            ts = _TS_BASE + rng.uniform(0, _TS_SPAN)
            status = rng.choice(_STATUS_CHOICES) if not ep.startswith("/health") else 200
            row = {
                "ts": round(ts, 4),
                "endpoint": ep,
                "latency_ms": round(latency, 4),
                "status": status,
            }
            f.write(json.dumps(row) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--instance-id", type=str, required=False, default="")
    args = ap.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    generate(args.output_dir, args.seed)


if __name__ == "__main__":
    main()
