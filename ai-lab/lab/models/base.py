"""The contract of every model in the lab: fit on rows, give a probability of label 1."""

from typing import Protocol

import numpy as np


class Model(Protocol):
    def fit(self, features: np.ndarray, labels: np.ndarray) -> None: ...

    def predict_proba(self, features: np.ndarray) -> np.ndarray:
        """Probability of label 1 per row, between 0 and 1."""
        ...
