"""Random forest van ondiepe bomen, alleen met numpy (geen sklearn nodig).

Het belang per facet (hoeveel de onzuiverheid daalt door splitsen op dat facet) is het gewicht
van dat facet."""

from dataclasses import dataclass, field

import numpy as np

CLASSES = 3  # 0 daling, 1 niets, 2 stijging


def balanced_weights(labels: np.ndarray) -> np.ndarray:
    """Gewicht per rij zodat elke klasse evenveel telt (zeldzame klassen tellen zwaarder)."""
    counts = np.bincount(labels, minlength=CLASSES).astype(float)
    per_class = np.where(counts > 0, len(labels) / (CLASSES * np.maximum(counts, 1)), 0.0)
    return per_class[labels]


def class_mass(labels: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Totaal gewicht per klasse."""
    return np.bincount(labels, weights=weights, minlength=CLASSES)


def gini(mass: np.ndarray) -> float:
    """Onzuiverheid van een groep: 0 = één klasse, hoger = meer gemengd."""
    total = mass.sum()
    return 0.0 if total == 0 else float(1.0 - ((mass / total) ** 2).sum())


@dataclass
class Split:
    feature: int
    threshold: float
    gain: float


def best_split_for_feature(column: np.ndarray, labels: np.ndarray, weights: np.ndarray,
                           min_leaf: int) -> tuple[float, float] | None:
    """Beste drempel voor één kolom als (drempel, winst), of None als er geen geldige is."""
    order = np.argsort(column, kind="stable")
    values, ys, ws = column[order], labels[order], weights[order]
    onehot = np.zeros((len(ys), CLASSES))
    onehot[np.arange(len(ys)), ys] = ws
    left = np.cumsum(onehot, axis=0)[:-1]          # massa links van elke mogelijke snede
    total = onehot.sum(axis=0)
    right = total - left
    left_n, right_n = left.sum(axis=1), right.sum(axis=1)
    counts = np.arange(1, len(ys))
    valid = (values[1:] > values[:-1]) & (counts >= min_leaf) & (len(ys) - counts >= min_leaf)
    if not valid.any():
        return None
    with np.errstate(divide="ignore", invalid="ignore"):
        left_gini = 1.0 - ((left / left_n[:, None]) ** 2).sum(axis=1)
        right_gini = 1.0 - ((right / right_n[:, None]) ** 2).sum(axis=1)
    weighted = (left_n * left_gini + right_n * right_gini) / total.sum()
    gain = np.where(valid, gini(total) - weighted, -np.inf)
    best = int(np.argmax(gain))
    return float((values[best] + values[best + 1]) / 2), float(gain[best])


def best_split(features: np.ndarray, labels: np.ndarray, weights: np.ndarray,
               candidates: np.ndarray, min_leaf: int) -> Split | None:
    """Beste snede over de kandidaat-kolommen."""
    best: Split | None = None
    for feature in candidates:
        found = best_split_for_feature(features[:, feature], labels, weights, min_leaf)
        if found and found[1] > 1e-12 and (best is None or found[1] > best.gain):
            best = Split(int(feature), found[0], found[1])
    return best


@dataclass
class Tree:
    """Een beslisboom als lijsten: knoop i heeft kinderen left[i], right[i] (-1 = blad)."""
    feature: list[int] = field(default_factory=list)
    threshold: list[float] = field(default_factory=list)
    left: list[int] = field(default_factory=list)
    right: list[int] = field(default_factory=list)
    proba: list[np.ndarray] = field(default_factory=list)

    def add_node(self, proba: np.ndarray) -> int:
        self.feature.append(-1)
        self.threshold.append(0.0)
        self.left.append(-1)
        self.right.append(-1)
        self.proba.append(proba)
        return len(self.feature) - 1

    def predict_proba(self, features: np.ndarray) -> np.ndarray:
        out = np.zeros((len(features), CLASSES))
        for row, values in enumerate(features):
            node = 0
            while self.left[node] != -1:
                node = self.left[node] if values[self.feature[node]] <= self.threshold[node] else self.right[node]
            out[row] = self.proba[node]
        return out


def grow(tree: Tree, features: np.ndarray, labels: np.ndarray, weights: np.ndarray, depth: int,
         max_depth: int, min_leaf: int, per_split: int, rng: np.random.Generator,
         importance: np.ndarray) -> int:
    """Bouw de boom recursief; geeft het knoopnummer terug."""
    mass = class_mass(labels, weights)
    node = tree.add_node(mass / mass.sum() if mass.sum() else np.full(CLASSES, 1 / CLASSES))
    if depth >= max_depth or len(labels) < 2 * min_leaf or gini(mass) == 0:
        return node
    candidates = rng.choice(features.shape[1], size=min(per_split, features.shape[1]), replace=False)
    split = best_split(features, labels, weights, candidates, min_leaf)
    if split is None:
        return node
    importance[split.feature] += split.gain * weights.sum()
    mask = features[:, split.feature] <= split.threshold
    tree.feature[node], tree.threshold[node] = split.feature, split.threshold
    args = (max_depth, min_leaf, per_split, rng, importance)
    tree.left[node] = grow(tree, features[mask], labels[mask], weights[mask], depth + 1, *args)
    tree.right[node] = grow(tree, features[~mask], labels[~mask], weights[~mask], depth + 1, *args)
    return node


class ForestModel:
    def __init__(self, trees: int = 100, depth: int = 4, min_leaf: int = 50, seed: int = 0):
        self.trees, self.depth, self.min_leaf, self.seed = trees, depth, min_leaf, seed
        self.members: list[Tree] = []
        self.importances = np.zeros(0)

    def fit(self, features: np.ndarray, labels: np.ndarray) -> None:
        rng = np.random.default_rng(self.seed)
        labels = labels.astype(int)
        weights = balanced_weights(labels)
        per_split = max(1, int(np.sqrt(features.shape[1])))
        importance = np.zeros(features.shape[1])
        self.members = []
        for _ in range(self.trees):
            rows = rng.integers(0, len(labels), len(labels))      # bootstrap
            tree = Tree()
            grow(tree, features[rows], labels[rows], weights[rows], 0, self.depth, self.min_leaf,
                 per_split, rng, importance)
            self.members.append(tree)
        total = importance.sum()
        self.importances = importance / total if total else np.full(features.shape[1], 1 / features.shape[1])

    def predict_proba(self, features: np.ndarray) -> np.ndarray:
        """Kans per klasse (rijen x 3), gemiddeld over alle bomen."""
        return np.mean([tree.predict_proba(features) for tree in self.members], axis=0)

    def weights(self, names: tuple[str, ...]) -> dict[str, float]:
        """Belang per facet, samen 1. Zonder teken: het zegt hoe belangrijk, niet welke kant op."""
        return {name: round(float(w), 4) for name, w in zip(names, self.importances)}

    def heaviest(self, names: tuple[str, ...], count: int = 2) -> list[str]:
        """De `count` facetten met het hoogste gewicht, zwaarste eerst."""
        ranked = sorted(self.weights(names).items(), key=lambda item: item[1], reverse=True)
        return [name for name, _ in ranked[:count]]
