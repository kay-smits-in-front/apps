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


def accuracy(proba: np.ndarray, labels: np.ndarray) -> float:
    """Hoe vaak de klasse met de hoogste kans (daling, niets, stijging) de juiste was."""
    return float((proba.argmax(axis=1) == labels).mean())


def base_accuracy(labels: np.ndarray, classes: int = 3) -> float:
    """Accuracy van een model dat altijd de meest voorkomende klasse zegt."""
    return float(np.bincount(labels, minlength=classes).max() / len(labels))


def outcome_scores(labels: np.ndarray, full_scale: float = 5.0) -> np.ndarray:
    """Wat er echt gebeurde als score: daling -5, niets 0, stijging +5."""
    return (labels - 1) * full_scale


def score_mse(proba: np.ndarray, labels: np.ndarray, full_scale: float, score_max: float = 5.0) -> float:
    """Gemiddelde kwadratische fout tussen de score van het model (-5 tot +5) en wat er echt gebeurde."""
    predicted = np.clip((proba[:, 2] - proba[:, 0]) / full_scale * score_max, -score_max, score_max)
    return float(((predicted - outcome_scores(labels, score_max)) ** 2).mean())


def base_score_mse(labels: np.ndarray, score_max: float = 5.0) -> float:
    """MSE van een model dat altijd de gemiddelde uitkomst als score geeft. Het model moet hier onder blijven."""
    actual = outcome_scores(labels, score_max)
    return float(((actual - actual.mean()) ** 2).mean())
