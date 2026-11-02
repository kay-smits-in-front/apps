"""Logistische regressie over de facetten, alleen met numpy (geen sklearn nodig).

Het simpelste model: elk facet telt lineair mee. In het onderzoek was dit vaak het beste model."""

import numpy as np

from lab.models.forest import CLASSES, balanced_weights
from lab.models.numeric import Adam, softmax


class LogitModel:
    def __init__(self, steps: int = 400, lr: float = 0.05, l2: float = 1e-2):
        self.steps, self.lr, self.l2 = steps, lr, l2
        self.mean = self.scale = self.params = None

    def standardise(self, features: np.ndarray) -> np.ndarray:
        return (features - self.mean) / self.scale

    def fit(self, features: np.ndarray, labels: np.ndarray) -> None:
        labels = labels.astype(int)
        self.mean = features.mean(axis=0)
        self.scale = np.where(features.std(axis=0) > 0, features.std(axis=0), 1.0)
        z = self.standardise(features)
        weights = balanced_weights(labels)
        onehot = np.eye(CLASSES)[labels]
        self.params = {"W": np.zeros((z.shape[1], CLASSES)), "b": np.zeros(CLASSES)}
        optimiser = Adam(self.params, self.lr)
        for _ in range(self.steps):
            error = (softmax(z @ self.params["W"] + self.params["b"]) - onehot) * (weights / weights.sum())[:, None]
            grads = {"W": z.T @ error + self.l2 * self.params["W"], "b": error.sum(axis=0)}
            optimiser.update(self.params, grads)

    def predict_proba(self, features: np.ndarray) -> np.ndarray:
        """Kans per klasse (rijen x 3)."""
        return softmax(self.standardise(features) @ self.params["W"] + self.params["b"])
