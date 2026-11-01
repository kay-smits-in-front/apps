"""Random forest van ondiepe bomen: leert welke facetten er toe doen. Het belang per facet
(feature importance) is het gewicht van dat facet."""

import numpy as np
from sklearn.ensemble import RandomForestClassifier

CLASSES = 3  # 0 daling, 1 niets, 2 stijging


class ForestModel:
    def __init__(self, trees: int = 300, depth: int = 4, min_leaf: int = 50):
        self.forest = RandomForestClassifier(
            n_estimators=trees, max_depth=depth, min_samples_leaf=min_leaf,
            class_weight="balanced", random_state=0, n_jobs=-1)

    def fit(self, features: np.ndarray, labels: np.ndarray) -> None:
        self.forest.fit(features, labels)

    def predict_proba(self, features: np.ndarray) -> np.ndarray:
        """Kans per klasse (rijen x 3). Een klasse die in de training ontbrak krijgt kans 0."""
        found = self.forest.predict_proba(features)
        full = np.zeros((len(features), CLASSES))
        full[:, self.forest.classes_.astype(int)] = found
        return full

    def weights(self, names: tuple[str, ...]) -> dict[str, float]:
        """Belang per facet, samen 1. Zonder teken: het zegt hoe belangrijk, niet welke kant op."""
        return {name: round(float(w), 4) for name, w in zip(names, self.forest.feature_importances_)}

    def heaviest(self, names: tuple[str, ...], count: int = 2) -> list[str]:
        """De `count` facetten met het hoogste gewicht, zwaarste eerst."""
        ranked = sorted(self.weights(names).items(), key=lambda item: item[1], reverse=True)
        return [name for name, _ in ranked[:count]]
