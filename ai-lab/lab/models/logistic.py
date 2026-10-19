"""Baseline: logistic regression on standardised features. The weights show what each
feature is worth."""

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


class LogisticModel:
    def __init__(self, strength: float = 1.0):
        self.pipeline = make_pipeline(
            StandardScaler(), LogisticRegression(C=strength, class_weight="balanced", max_iter=1000))

    def fit(self, features: np.ndarray, labels: np.ndarray) -> None:
        self.pipeline.fit(features, labels)

    def predict_proba(self, features: np.ndarray) -> np.ndarray:
        return self.pipeline.predict_proba(features)[:, 1]

    def weights(self, names: tuple[str, ...]) -> dict[str, float]:
        """Weight per feature on the standardised scale: positive means 'falls more likely'."""
        coefficients = self.pipeline[-1].coef_[0]
        return {name: round(float(w), 4) for name, w in zip(names, coefficients)}
