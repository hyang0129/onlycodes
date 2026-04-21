"""Toy model for hparam_search benchmark.

evaluate(learning_rate, hidden_size, dropout) -> accuracy

Deterministic function simulating a model training result.
This is the SAME function the grader uses to verify your answer.
"""

import math


def evaluate(learning_rate: float, hidden_size: int, dropout: float) -> float:
    """Return the model accuracy for the given hyperparameters.

    Parameters
    ----------
    learning_rate : float
        Learning rate. Try values around 0.001 – 0.1.
    hidden_size : int
        Number of hidden units. Try powers of 2: 16, 32, 64, 128, 256, 512.
    dropout : float
        Dropout rate in [0.0, 0.8].

    Returns
    -------
    float
        Accuracy in [0.0, 0.95].
    """
    lr_score = math.exp(-3.0 * (math.log10(learning_rate / 0.01)) ** 2)
    hs_score = math.exp(-((hidden_size - 128) / 128.0) ** 2)
    do_score = math.exp(-((dropout - 0.3) / 0.2) ** 2)
    return round(0.95 * lr_score * hs_score * do_score, 6)
