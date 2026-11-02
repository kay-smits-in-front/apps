"""Kleine rekenhulpjes die meerdere numpy-modellen delen."""

import numpy as np


def softmax(logits: np.ndarray) -> np.ndarray:
    """Kansen per rij uit scores per klasse."""
    shifted = np.exp(logits - logits.max(axis=1, keepdims=True))
    return shifted / shifted.sum(axis=1, keepdims=True)


class Adam:
    """Adam-optimaliseerder voor een dict met parameters."""

    def __init__(self, params: dict, lr: float, weight_decay: float = 0.0):
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
