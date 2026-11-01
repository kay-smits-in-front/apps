"""Reeksen voor een LSTM: de facetten van de laatste N dagen, dag voor dag."""

import numpy as np

from lab.facets import Facet, facet_row
from lab.features import WARMUP

DAY_RETURN_CLIP = 0.5


def facet_matrix(closes: list[float], volumes: list[float], facets: dict[str, Facet]) -> np.ndarray:
    """Eén rij per dag vanaf WARMUP: rij k hoort bij dag WARMUP + k. Eindigt op de laatste dag."""
    rows = [facet_row(closes, volumes, i, facets) for i in range(WARMUP, len(closes))]
    return np.array(rows, dtype=float).reshape(len(rows), len(facets))


def channels(matrix: np.ndarray, closes: list[float]) -> np.ndarray:
    """Wat de LSTM ziet per dag: de facetten gedeeld door 5 (dus -1 tot +1) en het dagrendement."""
    prices = np.array(closes, dtype=float)
    returns = np.clip(prices[WARMUP:] / prices[WARMUP - 1:-1] - 1, -DAY_RETURN_CLIP, DAY_RETURN_CLIP) * 2
    return np.column_stack([matrix / 5.0, returns])


def window_ending_at(channel_rows: np.ndarray, k: int, length: int) -> np.ndarray:
    """De `length` dagen tot en met rij k. Vereist k >= length - 1."""
    return channel_rows[k - length + 1:k + 1]
