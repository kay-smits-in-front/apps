"""Hoe goed is een model op dagen die het niet kende? Altijd tegen een simpele maatstaf gezet."""

import numpy as np


def log_loss(proba: np.ndarray, labels: np.ndarray) -> float:
    """Gemiddelde straf voor de kans die het model gaf aan wat er echt gebeurde. Lager is beter."""
    chosen = proba[np.arange(len(labels)), labels]
    return float(-np.log(np.clip(chosen, 1e-9, 1)).mean())


def base_rate_loss(labels: np.ndarray, classes: int = 3) -> float:
    """De straf van een model dat alleen weet hoe vaak elke klasse voorkomt. Het model moet hier onder blijven."""
    shares = np.bincount(labels, minlength=classes) / len(labels)
    return log_loss(np.tile(shares, (len(labels), 1)), labels)


def hit_rate(proba: np.ndarray, labels: np.ndarray, min_gap: float = 0.0) -> tuple[float, int]:
    """Op dagen dat de koers echt bewoog (daling of stijging) en het model een kant koos (kans stijging
    min kans daling groter dan `min_gap`): hoe vaak had het de goede kant, en op hoeveel dagen."""
    gap = proba[:, 2] - proba[:, 0]
    rows = (labels != 1) & (np.abs(gap) > min_gap)
    if not rows.any():
        return 0.0, 0
    return float(((gap[rows] > 0) == (labels[rows] == 2)).mean()), int(rows.sum())
