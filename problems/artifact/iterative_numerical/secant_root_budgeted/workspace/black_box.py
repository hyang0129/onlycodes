"""Black-box scalar functions for secant_root_budgeted.

Each f_i is continuous with a single root inside the bracket declared in
brackets.json. stdlib only.
"""
from __future__ import annotations
import math


def f1(x: float) -> float:
    # Root near sqrt(2) ~ 1.41421356
    return x * x - 2.0


def f2(x: float) -> float:
    # Root near x ≈ 1.7508 in [0.1, 3.0]
    # (f(x) = exp(x) - e*x - 1; f(1) = -1, NOT a root.)
    return math.exp(x) - math.e * x - 1.0


def f3(x: float) -> float:
    # Cubic with root near x ≈ 0.6823 in [0, 1]
    return x * x * x + x - 1.0


def f4(x: float) -> float:
    # Root near x = pi/4 in [0, 1.5]
    return math.cos(x) - math.sin(x)


def f5(x: float) -> float:
    # Root near x = ln(5) ~ 1.6094 in [0, 3]
    return math.exp(x) - 5.0
