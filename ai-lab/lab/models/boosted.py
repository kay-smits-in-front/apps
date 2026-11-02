"""Gradient boosting met kleine bomen, alleen met numpy (geen xgboost of sklearn nodig).

Elke ronde leert per klasse een kleine boom die de fout van de vorige rondes verbetert (zoals XGBoost).
Met `depth=1` zijn het stompjes: elk facet draagt apart bij en dat is een additief model (GAM)."""

import numpy as np

from lab.models.forest import CLASSES, balanced_weights
from lab.models.numeric import softmax


class RegressionTree:
    """Een kleine boom op gradiënten. Knoop i heeft kinderen left[i] en right[i] (-1 = blad)."""

    def __init__(self):
        self.feature, self.threshold, self.left, self.right, self.value = [], [], [], [], []

    def add_node(self, value: float) -> int:
        self.feature.append(-1)
        self.threshold.append(0.0)
        self.left.append(-1)
        self.right.append(-1)
        self.value.append(value)
        return len(self.value) - 1

    def finish(self) -> None:
        self.feature, self.threshold = np.array(self.feature), np.array(self.threshold)
        self.left, self.right, self.value = np.array(self.left), np.array(self.right), np.array(self.value)

    def predict(self, features: np.ndarray, depth: int) -> np.ndarray:
        """De bladwaarde voor elke rij."""
        node = np.zeros(len(features), dtype=int)
        for _ in range(depth):
            internal = self.left[node] != -1
            rows = np.flatnonzero(internal)
            at = node[rows]
            goes_left = features[rows, self.feature[at]] <= self.threshold[at]
            node[rows] = np.where(goes_left, self.left[at], self.right[at])
        return self.value[node]


def leaf_value(g: float, h: float, l2: float) -> float:
    return -g / (h + l2)


def best_split(column: np.ndarray, g: np.ndarray, h: np.ndarray, min_leaf: int, l2: float) -> tuple[float, float] | None:
    """Beste drempel voor één kolom als (drempel, winst), of None."""
    order = np.argsort(column, kind="stable")
    values, gs, hs = column[order], np.cumsum(g[order])[:-1], np.cumsum(h[order])[:-1]
    total_g, total_h = g.sum(), h.sum()
    counts = np.arange(1, len(column))
    valid = (values[1:] > values[:-1]) & (counts >= min_leaf) & (len(column) - counts >= min_leaf)
    if not valid.any():
        return None
    gain = gs ** 2 / (hs + l2) + (total_g - gs) ** 2 / (total_h - hs + l2) - total_g ** 2 / (total_h + l2)
    gain = np.where(valid, gain, -np.inf)
    best = int(np.argmax(gain))
    return float((values[best] + values[best + 1]) / 2), float(gain[best])


def grow(tree: RegressionTree, features: np.ndarray, g: np.ndarray, h: np.ndarray, rows: np.ndarray,
         level: int, depth: int, min_leaf: int, l2: float, update: np.ndarray) -> int:
    """Bouw de boom recursief. Schrijft ook de bladwaarde van elke rij in `update`."""
    value = leaf_value(g[rows].sum(), h[rows].sum(), l2)
    node = tree.add_node(value)
    best = None
    if level < depth:
        for feature in range(features.shape[1]):
            found = best_split(features[rows, feature], g[rows], h[rows], min_leaf, l2)
            if found and found[1] > 1e-9 and (best is None or found[1] > best[2]):
                best = (feature, found[0], found[1])
    if best is None:
        update[rows] = value
        return node
    feature, threshold, _ = best
    mask = features[rows, feature] <= threshold
    tree.feature[node], tree.threshold[node] = feature, threshold
    tree.left[node] = grow(tree, features, g, h, rows[mask], level + 1, depth, min_leaf, l2, update)
    tree.right[node] = grow(tree, features, g, h, rows[~mask], level + 1, depth, min_leaf, l2, update)
    return node


class BoostedModel:
    def __init__(self, rounds: int = 100, depth: int = 3, lr: float = 0.1, min_leaf: int = 50, l2: float = 1.0):
        self.rounds, self.depth, self.lr, self.min_leaf, self.l2 = rounds, depth, lr, min_leaf, l2
        self.rounds_trees: list[list[RegressionTree]] = []

    def fit(self, features: np.ndarray, labels: np.ndarray) -> None:
        labels = labels.astype(int)
        weights = balanced_weights(labels)
        onehot = np.eye(CLASSES)[labels]
        scores = np.zeros((len(labels), CLASSES))
        everything = np.arange(len(labels))
        self.rounds_trees = []
        for _ in range(self.rounds):
            proba = softmax(scores)
            this_round = []
            for k in range(CLASSES):
                g = (proba[:, k] - onehot[:, k]) * weights
                h = np.maximum(proba[:, k] * (1 - proba[:, k]), 1e-6) * weights
                tree, update = RegressionTree(), np.zeros(len(labels))
                grow(tree, features, g, h, everything, 0, self.depth, self.min_leaf, self.l2, update)
                tree.finish()
                scores[:, k] += self.lr * update
                this_round.append(tree)
            self.rounds_trees.append(this_round)

    def predict_proba(self, features: np.ndarray) -> np.ndarray:
        """Kans per klasse (rijen x 3)."""
        scores = np.zeros((len(features), CLASSES))
        for this_round in self.rounds_trees:
            for k, tree in enumerate(this_round):
                scores[:, k] += self.lr * tree.predict(features, self.depth)
        return softmax(scores)
