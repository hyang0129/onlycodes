import math

def f(x: float) -> float:
    """
    Black-box function. Find x* in [0, 100] such that |f(x*)| < 1e-6.
    """
    return math.exp(x / 20) + math.log(x + 1) - 10
