"""LSTM over de laatste N dagen van één aandeel, alleen met numpy (geen torch nodig).

Eén model voor alle aandelen: per aandeel zijn er te weinig rijen om iets te leren. Voorspelt
kans op daling, niets of stijging. Training met backpropagation door de tijd en Adam."""

import numpy as np

CLASSES = 3
CLIP = 1.0  # grootste toegestane gradiënt-norm, tegen ontsporen


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -30, 30)))


def softmax(logits: np.ndarray) -> np.ndarray:
    shifted = np.exp(logits - logits.max(axis=1, keepdims=True))
    return shifted / shifted.sum(axis=1, keepdims=True)


def init_params(channels: int, hidden: int, rng: np.random.Generator) -> dict[str, np.ndarray]:
    """Startwaarden. De forget-gate begint op +1 zodat de cel in het begin onthoudt."""
    scale = 1.0 / np.sqrt(hidden)
    bias = np.zeros(4 * hidden)
    bias[hidden:2 * hidden] = 1.0
    return {"W": rng.uniform(-scale, scale, (channels + hidden, 4 * hidden)), "b": bias,
            "Wo": rng.uniform(-scale, scale, (hidden, CLASSES)), "bo": np.zeros(CLASSES)}


def forward(params: dict, x: np.ndarray) -> tuple[np.ndarray, list]:
    """Loop de reeks door. Geeft de logits (rijen x 3) en wat de terugweg nodig heeft."""
    rows, steps, channels = x.shape
    hidden = params["Wo"].shape[0]
    h, c = np.zeros((rows, hidden)), np.zeros((rows, hidden))
    cache = []
    for t in range(steps):
        z = np.concatenate([x[:, t], h], axis=1)
        gates = z @ params["W"] + params["b"]
        i, f = sigmoid(gates[:, :hidden]), sigmoid(gates[:, hidden:2 * hidden])
        g, o = np.tanh(gates[:, 2 * hidden:3 * hidden]), sigmoid(gates[:, 3 * hidden:])
        c_new = f * c + i * g
        h_new = o * np.tanh(c_new)
        cache.append((z, i, f, g, o, c, c_new))
        h, c = h_new, c_new
    return h @ params["Wo"] + params["bo"], [h, cache]


def backward(params: dict, cache: list, dlogits: np.ndarray) -> dict[str, np.ndarray]:
    """Gradiënt van de loss naar elke parameter, door de tijd terug."""
    last_h, steps = cache
    hidden = params["Wo"].shape[0]
    grads = {"Wo": last_h.T @ dlogits, "bo": dlogits.sum(axis=0),
             "W": np.zeros_like(params["W"]), "b": np.zeros_like(params["b"])}
    dh, dc = dlogits @ params["Wo"].T, np.zeros_like(last_h)
    for z, i, f, g, o, c_prev, c in reversed(steps):
        tanh_c = np.tanh(c)
        dc = dc + dh * o * (1 - tanh_c ** 2)
        dgates = np.concatenate([dc * g * i * (1 - i), dc * c_prev * f * (1 - f),
                                 dc * i * (1 - g ** 2), dh * tanh_c * o * (1 - o)], axis=1)
        grads["W"] += z.T @ dgates
        grads["b"] += dgates.sum(axis=0)
        dh = (dgates @ params["W"].T)[:, -hidden:]
        dc = dc * f
    return grads


def loss_and_grads(params: dict, x: np.ndarray, y: np.ndarray, class_weight: np.ndarray):
    """Gewogen cross-entropy en de gradiënten ervan."""
    logits, cache = forward(params, x)
    proba = softmax(logits)
    w = class_weight[y]
    loss = float(-(w * np.log(np.clip(proba[np.arange(len(y)), y], 1e-12, 1))).sum() / w.sum())
    dlogits = proba.copy()
    dlogits[np.arange(len(y)), y] -= 1
    return loss, backward(params, cache, dlogits * (w / w.sum())[:, None])


def clip(grads: dict, limit: float = CLIP) -> dict:
    norm = np.sqrt(sum((g ** 2).sum() for g in grads.values()))
    return grads if norm <= limit else {k: g * (limit / norm) for k, g in grads.items()}


class Adam:
    def __init__(self, params: dict, lr: float, weight_decay: float = 1e-4):
        self.lr, self.decay, self.step = lr, weight_decay, 0
        self.m = {k: np.zeros_like(v) for k, v in params.items()}
        self.v = {k: np.zeros_like(v) for k, v in params.items()}

    def update(self, params: dict, grads: dict) -> None:
        self.step += 1
        for key, grad in grads.items():
            grad = grad + self.decay * params[key]
            self.m[key] = 0.9 * self.m[key] + 0.1 * grad
            self.v[key] = 0.999 * self.v[key] + 0.001 * grad ** 2
            m_hat = self.m[key] / (1 - 0.9 ** self.step)
            v_hat = self.v[key] / (1 - 0.999 ** self.step)
            params[key] -= self.lr * m_hat / (np.sqrt(v_hat) + 1e-8)


class LstmModel:
    def __init__(self, hidden: int = 32, epochs: int = 8, lr: float = 3e-3, batch: int = 128, seed: int = 0):
        self.hidden, self.epochs, self.lr, self.batch, self.seed = hidden, epochs, lr, batch, seed
        self.params: dict[str, np.ndarray] | None = None

    def class_weights(self, labels: np.ndarray) -> np.ndarray:
        """Zeldzame klassen tellen zwaarder, anders voorspelt het model altijd 'niets'."""
        counts = np.bincount(labels, minlength=CLASSES).clip(min=1)
        return len(labels) / (CLASSES * counts)

    def fit(self, features: np.ndarray, labels: np.ndarray) -> None:
        rng = np.random.default_rng(self.seed)
        labels = labels.astype(int)
        self.params = init_params(features.shape[2], self.hidden, rng)
        optimiser = Adam(self.params, self.lr)
        weights = self.class_weights(labels)
        for _ in range(self.epochs):
            order = rng.permutation(len(features))
            for start in range(0, len(order), self.batch):
                pick = order[start:start + self.batch]
                _, grads = loss_and_grads(self.params, features[pick], labels[pick], weights)
                optimiser.update(self.params, clip(grads))

    def predict_proba(self, features: np.ndarray) -> np.ndarray:
        """Kans per klasse (rijen x 3)."""
        out = [softmax(forward(self.params, features[s:s + 1024])[0]) for s in range(0, len(features), 1024)]
        return np.concatenate(out)

    def save(self, path) -> None:
        with open(path, "wb") as file:
            np.savez(file, hidden=self.hidden, **self.params)

    @classmethod
    def load(cls, path) -> "LstmModel":
        with np.load(path) as saved:
            model = cls(hidden=int(saved["hidden"]))
            model.params = {key: saved[key] for key in ("W", "b", "Wo", "bo")}
        return model
